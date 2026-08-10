// @vitest-environment jsdom
/**
 * KAN-554's live preview: it follows the document, and **the editor never notices**.
 *
 * The second half is the interesting one, and it is why `lib/livedoc.ts` exists. The obvious wiring
 * for a live preview is to lift the document into the parent and hand it back down as `note.body`,
 * which puts a per-keystroke round trip through Svelte's reactive graph between CM6 and the `$effect`
 * that owns the `EditorView` — see `EditorPane.svelte`'s docstrings and `lib/editor.ts` on the two
 * guards. So this file asserts the *data path*, not just the outcome:
 *
 * - the preview updates when the document changes (liveness),
 * - the parent's `note` object is **the same object** afterwards (nothing was lifted),
 * - the `EditorView` and its DOM element are **the same instances** afterwards (nothing remounted),
 * - and attaching the preview does not mark the note dirty.
 *
 * The last one is not decoration: `watchDocument` extends a *live* view with
 * `StateEffect.appendConfig`, which is a real transaction through `EditorPane`'s own
 * `updateListener`. If it ever carried a change, opening a note would show "unsaved changes" on a
 * note nobody edited, and `⌘S` would `PATCH` a body identical to the stored one.
 */

import { EditorView } from '@codemirror/view'
import { type Component, flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from '../src/App.svelte'
import EditorPane from '../src/components/EditorPane.svelte'
import PreviewPane from '../src/components/PreviewPane.svelte'
import * as auth from '../src/lib/auth'
import type { Note } from '../src/lib/types'
import { box, type Box } from './reactive.svelte'
import { FAKE_TOKEN } from './token'

function note(overrides: Partial<Note> = {}): Note {
  return {
    ref: 'NOTE-6',
    id: 6,
    title: 'Weekly review',
    body: '# Week of 2026-08-03\n',
    path: 'journal/2026/08/weekly-review.md',
    created_at: '2026-08-09T10:00:00+00:00',
    updated_at: '2026-08-09T10:00:00.123456+00:00',
    ...overrides,
  }
}

let host: HTMLDivElement
const mounted: unknown[] = []
const realFetch = globalThis.fetch

beforeEach(() => {
  host = document.createElement('div')
  document.body.append(host)
})

afterEach(() => {
  for (const instance of mounted.splice(0)) {
    unmount(instance as never)
  }
  host.remove()
  auth.clearToken()
  globalThis.fetch = realFetch
  globalThis.history.pushState({}, '', '/')
})

/**
 * The editor and the preview as **siblings** in one region, which is how `App.svelte` places them
 * (PLAN §S9: the preview is never inside CM6's subtree) and what `lib/livedoc.ts` needs — the preview
 * finds the view in its own `parentElement`.
 *
 * Mounted in markup order, editor first, because that is the order `App.svelte` uses and therefore the
 * effect order the synchronous attach path depends on. `trackEditor`'s `MutationObserver` covers the
 * other order asynchronously; nothing here relies on it, which is the point of mounting them this way.
 */
function mountPair(opened: Box<Note | null>): HTMLDivElement {
  const split = document.createElement('div')
  host.append(split)

  for (const component of [EditorPane, PreviewPane]) {
    mounted.push(
      mount(component as Component<Record<string, unknown>, Record<string, unknown>>, {
        target: split,
        props: {
          get note() {
            return opened.value
          },
          error: null,
        },
      }),
    )
    flushSync()
  }
  return split
}

/** Let the effects run, the observers fire and the promises they started settle. */
async function settle(): Promise<void> {
  for (let turn = 0; turn < 12; turn += 1) {
    await new Promise((resolve) => setTimeout(resolve, 0))
    flushSync()
  }
}

function editor(scope: ParentNode): EditorView {
  const dom = scope.querySelector<HTMLElement>('.cm-editor')
  expect(dom).not.toBeNull()
  const view = EditorView.findFromDOM(dom!)
  expect(view).not.toBeNull()
  return view!
}

function preview(scope: ParentNode): HTMLElement {
  const element = scope.querySelector<HTMLElement>('[data-testid="preview"]')
  expect(element).not.toBeNull()
  return element!
}

/** Replace the whole document, the way `syncDocument` does and the way a paste does. */
function typeInto(view: EditorView, text: string): void {
  view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: text } })
  flushSync()
}

describe('the preview follows the document', () => {
  it('renders the open note before anything is typed', () => {
    const opened = box<Note | null>(note({ body: '# Hello\n\nA paragraph.' }))
    const split = mountPair(opened)

    expect(preview(split).querySelector('h1')?.textContent).toBe('Hello')
    expect(preview(split).querySelector('p')?.textContent).toBe('A paragraph.')
  })

  it('updates as the document changes, without the change passing through a prop', () => {
    const opened = box<Note | null>(note({ body: '# One' }))
    const split = mountPair(opened)
    const before = opened.value

    typeInto(editor(split), '## Two\n\n- a\n- b')

    // Liveness.
    expect(preview(split).querySelector('h2')?.textContent).toBe('Two')
    expect(preview(split).querySelectorAll('li')).toHaveLength(2)
    expect(preview(split).querySelector('h1')).toBeNull()

    // The data path. `toBe`, not `toEqual`: the claim is that the parent's state was not touched at
    // all, so nothing above these two components could have re-run because of a keystroke.
    expect(opened.value).toBe(before)
    expect(opened.value?.body).toBe('# One')
  })

  it('keeps up over a sequence of edits', () => {
    const opened = box<Note | null>(note({ body: '' }))
    const split = mountPair(opened)
    const view = editor(split)

    for (const [source, expected] of [
      ['*one*', 'one'],
      ['**two**', 'two'],
      ['`three`', 'three'],
    ] as const) {
      typeInto(view, source)
      expect(preview(split).textContent).toBe(expected)
    }
  })

  it('empties when the note is closed', () => {
    const opened = box<Note | null>(note({ body: '# Something' }))
    const split = mountPair(opened)
    expect(preview(split).textContent).toContain('Something')

    opened.value = null
    flushSync()

    expect(preview(split).childNodes).toHaveLength(0)
  })

  it('follows the editor to a different note', () => {
    // `EditorPane` destroys and rebuilds its view here (ADR 0008's identity guard is keyed on the
    // ref), so the preview's listener has to move with it. A preview still showing the previous
    // note's text is the failure this pins.
    const opened = box<Note | null>(note({ body: '# First' }))
    const split = mountPair(opened)

    opened.value = note({ ref: 'NOTE-7', body: '# Second' })
    flushSync()

    expect(preview(split).querySelector('h1')?.textContent).toBe('Second')
    expect(editor(split).state.doc.toString()).toBe('# Second')
  })

  it('finds the editor even when the preview mounts first', async () => {
    // **`trackEditor`'s `MutationObserver` is the only thing that makes this pass, and this test
    // exists because a mutation proved it was otherwise dead code.** Removing the observer reddened
    // nothing: `App.svelte` puts `EditorPane` earlier in its markup, so its effect is always created
    // and flushed first and the synchronous lookup always succeeds. That ordering is a property of a
    // *third* file, and "someone swaps two lines and the preview silently stops following the
    // document" is exactly the failure the observer is for — so it needs a test that does not depend
    // on the ordering it is insuring against.
    const split = document.createElement('div')
    host.append(split)
    const opened = box<Note | null>(note({ body: '# Seeded from the prop' }))
    const props = {
      get note() {
        return opened.value
      },
      error: null,
    }

    // Preview first. There is no view for it to find at this point.
    mounted.push(mount(PreviewPane, { target: split, props }))
    flushSync()
    mounted.push(mount(EditorPane, { target: split, props }))
    await settle()

    typeInto(editor(split), '# Typed after the editor arrived')
    await settle()

    // The seed would still be on screen if nothing had re-attached.
    expect(preview(split).querySelector('h1')?.textContent).toBe('Typed after the editor arrived')
  })

  it('shows the editor’s document rather than the stale prop after an unsaved edit', () => {
    // The parent's copy goes out of date the moment you type. `PreviewPane` seeds itself from
    // `note.body` inside an `untrack`, so a re-render that changes nothing cannot reseed the preview
    // from the version on the server.
    const opened = box<Note | null>(note({ body: '# Saved' }))
    const split = mountPair(opened)
    typeInto(editor(split), '# Typed, not saved')

    // A new object with the *old* body — exactly the parent `EditorPane`'s `appliedBody` guard exists
    // for.
    opened.value = note({ body: '# Saved' })
    flushSync()

    expect(preview(split).querySelector('h1')?.textContent).toBe('Typed, not saved')
  })
})

describe('the preview costs the editor nothing', () => {
  it('does not rebuild the view or its element when the document changes', () => {
    const opened = box<Note | null>(note({ body: 'a' }))
    const split = mountPair(opened)
    const view = editor(split)
    const element = split.querySelector('.cm-editor')

    typeInto(view, 'a longer document, typed')

    expect(editor(split)).toBe(view)
    expect(split.querySelector('.cm-editor')).toBe(element)
    // A remount would have thrown the undo history away; `EditorPane` builds `history()` in from its
    // first commit precisely so this is observable.
    expect(view.state.doc.toString()).toBe('a longer document, typed')
  })

  it('does not mark the note dirty by attaching', () => {
    // `watchDocument` dispatches a real transaction (`StateEffect.appendConfig`) into a live view. It
    // carries no changes, so `EditorPane`'s own `updateListener` must not see `docChanged`.
    const opened = box<Note | null>(note())
    const split = mountPair(opened)

    expect(split.querySelector('[data-testid="save-state"]')?.textContent?.trim()).toBe('no changes')
    expect(split.querySelector('button')?.hasAttribute('disabled')).toBe(true)
  })

  it('renders nothing inside CM6’s subtree', () => {
    // PLAN §S9 from this card's side. `tests/shell.test.ts` and `tests/editor-container.test.ts` own
    // the claim about `EditorPane`; this says the *preview* did not become a way around it.
    const opened = box<Note | null>(note({ body: '# H' }))
    const split = mountPair(opened)

    expect(split.querySelector('.editor-host [data-testid="preview"]')).toBeNull()
    expect(preview(split).closest('.editor-host')).toBeNull()
    expect(preview(split).querySelector('.cm-editor')).toBeNull()
  })
})

describe('a note body is rendered inert in the live preview', () => {
  // End to end through the real components, not just through `renderMarkdown`: the payload goes into
  // CM6's document and comes out of the preview, which is the path an attacker actually has.
  //
  // The second column is the **witness**: what a reader must still be able to see. An inert preview
  // and an empty preview are different outcomes and only one of them is correct — a renderer that
  // dropped every payload would satisfy every negative assertion below and lose the note's content.
  // A refused link keeps its label and loses only the destination, which is why its witness is the
  // words rather than the source line.
  const PAYLOADS: ReadonlyArray<readonly [string, string]> = [
    ['<script>globalThis.KAYA_XSS = true</script>', '<script>globalThis.KAYA_XSS = true</script>'],
    ['<img src=x onerror="globalThis.KAYA_XSS = true">', 'onerror="globalThis.KAYA_XSS = true"'],
    ['[click](javascript:globalThis.KAYA_XSS=true)', 'click'],
    ['<iframe src="https://evil.example.com"></iframe>', '<iframe src="https://evil.example.com">'],
  ]

  for (const [payload, witness] of PAYLOADS) {
    it(`stays inert when the document is: ${payload.slice(0, 32)}`, () => {
      const opened = box<Note | null>(note({ body: '' }))
      const split = mountPair(opened)
      typeInto(editor(split), payload)

      const rendered = preview(split)
      expect(rendered.querySelectorAll('script, iframe, svg, style')).toHaveLength(0)
      expect(rendered.querySelector('img')).toBeNull()
      expect(rendered.querySelector('a')).toBeNull()
      for (const element of rendered.querySelectorAll('*')) {
        for (const attribute of element.attributes) {
          expect(attribute.name.toLowerCase().startsWith('on')).toBe(false)
        }
      }
      // Inert rather than absent. See the table's second column.
      expect(rendered.textContent).toContain(witness)
      // And the browser agrees it is text: the payload is escaped in the serialized markup.
      expect(rendered.innerHTML).not.toContain(payload)
    })
  }
})

describe('the preview toggle', () => {
  const NOTE = note()

  beforeEach(() => {
    auth.setToken(FAKE_TOKEN)
    globalThis.history.pushState({}, '', `/notes/${NOTE.ref}`)
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      const body =
        url === '/api/v1/notes'
          ? { notes: [NOTE] }
          : url === `/api/v1/notes/${NOTE.ref}`
            ? NOTE
            : { error: { code: 'not_found', message: `nothing fake at ${url}` } }
      return new Response(JSON.stringify(body), {
        status: 'error' in body ? 404 : 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }) as unknown as typeof fetch
  })

  function click(testid: string): void {
    host.querySelector<HTMLButtonElement>(`[data-testid="${testid}"]`)!.click()
    flushSync()
  }

  it('keeps the very same editor across a hide and a show, with the typed text intact', async () => {
    // **This is the assertion that `EditorPane` being outside the toggle's `{#if}` is what makes
    // true.** Inside it, the editor would be a different component instance every time the preview
    // appeared or disappeared — a fresh `EditorState`, a destroyed view, no undo history — so a
    // command about the pane beside it would silently discard unsaved work.
    mounted.push(mount(App, { target: host, props: {} }))
    await settle()

    const view = editor(host)
    const element = host.querySelector('.cm-editor')
    typeInto(view, '# Typed before hiding')

    click('toggle-preview')
    expect(host.querySelector('[data-testid="preview"]')).toBeNull()
    click('toggle-preview')
    await settle()

    expect(editor(host)).toBe(view)
    expect(host.querySelector('.cm-editor')).toBe(element)
    expect(view.state.doc.toString()).toBe('# Typed before hiding')
    // And the preview came back live rather than showing the note as it was on the server.
    expect(preview(host).querySelector('h1')?.textContent).toBe('Typed before hiding')
  })

  it('puts the preview beside the editor inside the shell, not inside it', async () => {
    mounted.push(mount(App, { target: host, props: {} }))
    await settle()

    const rendered = preview(host)
    expect(rendered.closest('.editor-host')).toBeNull()
    expect(rendered.parentElement?.parentElement?.classList.contains('split')).toBe(true)
    expect(host.querySelector('.split > .pane')).not.toBeNull()
  })
})
