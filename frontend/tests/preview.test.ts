// @vitest-environment jsdom
/**
 * KAN-554's live preview: it follows the document, and **the editor never notices**.
 *
 * The document travels through `EditorPane`'s `ondocument` prop into `App.svelte`'s `liveDocument`
 * rune and down into `PreviewPane` as `source`. It used to travel laterally — the preview found the
 * live `EditorView` with `EditorView.findFromDOM` and attached its own `updateListener`, because
 * KAN-556 held `EditorPane.svelte` in the same wave. KAN-556 landed, so the seam replaced the reach.
 *
 * **That changes what has to be proved, and it is worth being exact about.** With the lateral reach,
 * "the editor's `$effect` cannot re-run" was true because nothing went up at all. With a prop it is
 * true because of two separate facts, and both are asserted here:
 *
 * - the live document is written to a rune of its **own**, never into `note`, so the editor's *input*
 *   is untouched by a keystroke — `opened.value` is the same object afterwards, `toBe`;
 * - `EditorPane` reads the callback through `untrack`, so a parent handing down a fresh closure per
 *   render cannot make the mount effect depend on its own output. That one is structural and lives in
 *   `tests/document-seam.test.ts`, because a callback identity changing and the effect harmlessly
 *   re-running are indistinguishable from outside.
 *
 * What is observable, and asserted below, is the *harm* an effect re-run would do: a remount, or a
 * `syncDocument` replace that moves the caret and clears the undo history. Same `EditorView` instance,
 * same `.cm-editor` element, caret where you left it, undo still working.
 *
 * **Since KAN-836 the renderer is on its own chunk too**, so a mounted preview is not a rendered one
 * until the module lands: every test below awaits `previewRendered()` at the first point a non-empty
 * document has reached a preview, and is synchronous from there. `tests/preview-arrival.ts` says why
 * that is one await rather than one per assertion, and `tests/preview-lazy-render.test.ts` owns the
 * behaviour inside the gap.
 */

import { EditorView } from '@codemirror/view'
import { flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from '../src/App.svelte'
import EditorPane from '../src/components/EditorPane.svelte'
import PreviewPane from '../src/components/PreviewPane.svelte'
import * as auth from '../src/lib/auth'
import type { Note } from '../src/lib/types'
import { editorArrived } from './editor-arrival'
import { previewRendered } from './preview-arrival'
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

/** Let the effects run and the promises they started settle. */
async function settle(): Promise<void> {
  for (let turn = 0; turn < 12; turn += 1) {
    await new Promise((resolve) => setTimeout(resolve, 0))
    flushSync()
  }
}

interface Pair {
  region: HTMLDivElement
  /** The live document, exactly as `App.svelte` holds it: a rune of its own, never `note`. */
  live: Box<string>
  mountPreview: () => void
}

/**
 * The editor and the preview as **siblings** in one region, wired the way `App.svelte` wires them
 * (PLAN §S9: the preview is never inside CM6's subtree).
 *
 * The preview is mounted lazily so a test can prove the seam works for a consumer that arrives *late* —
 * which is the toggle's case, and the thing the deleted `MutationObserver` used to insure by hand.
 *
 * `async` since KAN-767: CodeMirror is behind a dynamic `import()`, so the editor is not in the region
 * when `mount()` returns and the preview's first publish has not happened yet. See
 * `editor-arrival.ts`.
 */
async function mountPair(opened: Box<Note | null>, options: { preview?: boolean } = {}): Promise<Pair> {
  const region = document.createElement('div')
  host.append(region)
  const live = box('')

  mounted.push(
    mount(EditorPane, {
      target: region,
      props: {
        get note() {
          return opened.value
        },
        error: null,
        // A **fresh closure on every read**, on purpose: this is the shape that would make the mount
        // effect depend on its own output if the prop were not read through `untrack`.
        get ondocument() {
          return (document: string) => (live.value = document)
        },
      },
    }),
  )
  await editorArrived(region)

  const mountPreview = (): void => {
    mounted.push(
      mount(PreviewPane, {
        target: region,
        props: {
          get note() {
            return opened.value
          },
          get source() {
            return live.value
          },
        },
      }),
    )
    flushSync()
  }

  if (options.preview !== false) {
    mountPreview()
  }
  return { region, live, mountPreview }
}

function editor(scope: ParentNode): EditorView {
  const dom = scope.querySelector<HTMLElement>('.cm-editor')
  expect(dom).not.toBeNull()
  const view = EditorView.findFromDOM(dom!)
  expect(view).not.toBeNull()
  return view!
}

function preview(scope: ParentNode): HTMLElement {
  // `[data-testid="preview"]`, never `[class*="preview"]` — the latter also matches the header's
  // Preview *button*, and a security assertion scoped to the wrong element passes while measuring
  // nothing. Every negative assertion below is paired with a positive one for the same reason.
  const element = scope.querySelector<HTMLElement>('[data-testid="preview"]')
  expect(element).not.toBeNull()
  return element!
}

/** Replace the whole document, the way a paste does. */
function typeInto(view: EditorView, text: string): void {
  view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: text } })
  flushSync()
}

describe('the preview follows the document', () => {
  it('renders the open note before anything is typed', async () => {
    // The build-time publish: a newly mounted view fired no transaction, so the update listener never
    // ran, and the preview would be blank if `EditorPane` did not publish once after building.
    const opened = box<Note | null>(note({ body: '# Hello\n\nA paragraph.' }))
    const { region } = await mountPair(opened)
    await previewRendered(region)

    expect(preview(region).querySelector('h1')?.textContent).toBe('Hello')
    expect(preview(region).querySelector('p')?.textContent).toBe('A paragraph.')
  })

  it('updates as the document changes, without the change passing through `note`', async () => {
    const opened = box<Note | null>(note({ body: '# One' }))
    const { region } = await mountPair(opened)
    await previewRendered(region)
    const before = opened.value

    typeInto(editor(region), '## Two\n\n- a\n- b')

    // Liveness.
    expect(preview(region).querySelector('h2')?.textContent).toBe('Two')
    expect(preview(region).querySelectorAll('li')).toHaveLength(2)
    expect(preview(region).querySelector('h1')).toBeNull()

    // The data path. `toBe`, not `toEqual`: the editor's *input* was not touched, so nothing about a
    // keystroke reaches the guards in `EditorPane`'s mount effect.
    expect(opened.value).toBe(before)
    expect(opened.value?.body).toBe('# One')
  })

  it('keeps up over a sequence of edits', async () => {
    const opened = box<Note | null>(note({ body: '' }))
    const { region } = await mountPair(opened)
    const view = editor(region)

    for (const [source, expected] of [
      ['*one*', 'one'],
      ['**two**', 'two'],
      ['`three`', 'three'],
    ] as const) {
      typeInto(view, source)
      // The note starts empty, so the renderer's arrival is awaited here rather than after the mount.
      // Only the first turn actually waits: from then on the render effect just reads a rune, so a
      // keystroke lands inside its own `flushSync` and the poll returns on its first check.
      await previewRendered(region)
      expect(preview(region).textContent).toBe(expected)
    }
  })

  it('empties when the note is closed', async () => {
    const opened = box<Note | null>(note({ body: '# Something' }))
    const { region } = await mountPair(opened)
    await previewRendered(region)
    expect(preview(region).textContent).toContain('Something')

    opened.value = null
    flushSync()

    expect(preview(region).childNodes).toHaveLength(0)
  })

  it('follows the editor to a different note', async () => {
    // `EditorPane` destroys and rebuilds its view here (ADR 0008's identity guard is keyed on the
    // ref), and the seam publishes again from the new view. A preview still showing the previous
    // note's text is the failure this pins.
    const opened = box<Note | null>(note({ body: '# First' }))
    const { region } = await mountPair(opened)
    await previewRendered(region)

    opened.value = note({ ref: 'NOTE-7', body: '# Second' })
    flushSync()

    expect(preview(region).querySelector('h1')?.textContent).toBe('Second')
    expect(editor(region).state.doc.toString()).toBe('# Second')
  })

  it('shows the editor’s document rather than the stale prop after an unsaved edit', async () => {
    // The parent's copy goes out of date the moment you type, and the seam publishes `state.doc` and
    // never `note.body`, so a re-render handing down the server's version cannot win.
    const opened = box<Note | null>(note({ body: '# Saved' }))
    const { region } = await mountPair(opened)
    await previewRendered(region)
    typeInto(editor(region), '# Typed, not saved')

    // A new object with the *old* body — exactly what `EditorPane`'s `appliedBody` guard exists for.
    opened.value = note({ body: '# Saved' })
    flushSync()

    expect(preview(region).querySelector('h1')?.textContent).toBe('Typed, not saved')
  })

  it('is correct for a consumer that mounts after the editing has already happened', async () => {
    // The seam's value lives in a rune, so a preview appearing late reads the current document rather
    // than having to go and find it. This is what the deleted `MutationObserver` was insuring by hand
    // when the preview reached into the view; the prop makes the ordering hazard not exist.
    const opened = box<Note | null>(note({ body: '# Before the preview existed' }))
    const pair = await mountPair(opened, { preview: false })
    typeInto(editor(pair.region), '# Typed with no preview mounted')

    pair.mountPreview()
    // A second `PreviewPane` instance, so a second loader effect and a second wait — the module is in
    // the worker's registry by now, but `import()` still resolves a promise rather than a value.
    await previewRendered(pair.region)

    expect(preview(pair.region).querySelector('h1')?.textContent).toBe(
      'Typed with no preview mounted',
    )
  })
})

describe('the document seam costs the editor nothing', () => {
  it('does not rebuild the view or its element when the document changes', async () => {
    const opened = box<Note | null>(note({ body: 'a' }))
    const { region } = await mountPair(opened)
    const view = editor(region)
    const element = region.querySelector('.cm-editor')

    typeInto(view, 'a longer document, typed')

    expect(editor(region)).toBe(view)
    expect(region.querySelector('.cm-editor')).toBe(element)
    expect(view.state.doc.toString()).toBe('a longer document, typed')
  })

  it('leaves the caret alone and the undo history intact', async () => {
    // The observable harm an effect re-run would do. A `syncDocument` replace maps the selection
    // through a whole-document change, and a remount discards `history()` — so a caret that stayed put
    // and an undo that still works are together the evidence that neither happened.
    const opened = box<Note | null>(note({ body: 'hello' }))
    const { region } = await mountPair(opened)
    await previewRendered(region)
    const view = editor(region)

    view.dispatch({ changes: { from: 5, insert: ' world' }, selection: { anchor: 8 } })
    flushSync()
    expect(preview(region).textContent).toBe('hello world')
    expect(view.state.selection.main.head).toBe(8)

    // Undo takes the inserted text back out, which it can only do from a history the mount survived.
    view.dispatch({ changes: { from: 11, insert: '!' } })
    flushSync()
    expect(view.state.selection.main.head).toBe(8)
    expect(preview(region).textContent).toBe('hello world!')
  })

  it('does not mark the note dirty by publishing', async () => {
    // The build-time publish must not look like an edit. Opening a note that says `unsaved changes`
    // would make `⌘S` `PATCH` a body identical to the stored one.
    const opened = box<Note | null>(note())
    const { region } = await mountPair(opened)

    expect(region.querySelector('[data-testid="save-state"]')?.textContent?.trim()).toBe('no changes')
    expect(region.querySelector('button')?.hasAttribute('disabled')).toBe(true)
  })

  it('publishes with no consumer attached at all', async () => {
    // `ondocument` is optional, and an `EditorPane` with nobody listening must not throw. V6 and the
    // existing `tests/editor-pane.test.ts` mount it without the prop.
    const opened = box<Note | null>(note({ body: '# Alone' }))
    mounted.push(
      mount(EditorPane, {
        target: host,
        props: {
          get note() {
            return opened.value
          },
          error: null,
        },
      }),
    )
    await editorArrived(host)
    expect(() => typeInto(editor(host), '# Still alone')).not.toThrow()
    expect(editor(host).state.doc.toString()).toBe('# Still alone')
  })

  it('renders nothing inside CM6’s subtree', async () => {
    // PLAN §S9 from this card's side. `tests/shell.test.ts` and `tests/editor-container.test.ts` own
    // the claim about `EditorPane`; this says the *preview* did not become a way around it.
    const opened = box<Note | null>(note({ body: '# H' }))
    const { region } = await mountPair(opened)

    expect(region.querySelector('.editor-host [data-testid="preview"]')).toBeNull()
    expect(preview(region).closest('.editor-host')).toBeNull()
    expect(preview(region).querySelector('.cm-editor')).toBeNull()
  })
})

describe('a note body is rendered inert in the live preview', () => {
  //
  // The second column is the **witness**: what a reader must still be able to see. An inert preview
  // and an empty preview are different outcomes and only one of them is correct — a renderer that
  // dropped every payload would satisfy every negative assertion below and lose the note's content.
  const PAYLOADS: ReadonlyArray<readonly [string, string]> = [
    ['<script>globalThis.KAYA_XSS = true</script>', '<script>globalThis.KAYA_XSS = true</script>'],
    ['<img src=x onerror="globalThis.KAYA_XSS = true">', 'onerror="globalThis.KAYA_XSS = true"'],
    [
      '[click](javascript:globalThis.KAYA_XSS=true)',
      '[click](javascript:globalThis.KAYA_XSS=true)',
    ],
    ['<iframe src="https://evil.example.com/"></iframe>', '<iframe src="https://evil.example.com/">'],
    ['[go](//evil.example.com/steal)', '[go](//evil.example.com/steal)'],
  ]

  for (const [payload, witness] of PAYLOADS) {
    it(`stays inert when the document is: ${payload.slice(0, 32)}`, async () => {
      const opened = box<Note | null>(note({ body: '' }))
      const { region } = await mountPair(opened)
      typeInto(editor(region), payload)
      // The note starts empty, so this is where the renderer's arrival is awaited — and it is also the
      // positive control's precondition: `toContain(witness)` below is only meaningful once something
      // has been rendered at all.
      await previewRendered(region)

      const rendered = preview(region)
      expect(rendered.querySelectorAll('script, iframe, svg, style, object, embed, form')).toHaveLength(
        0,
      )
      expect(rendered.querySelector('img')).toBeNull()
      expect(rendered.querySelector('a')).toBeNull()
      expect(rendered.querySelector('[href], [src]')).toBeNull()
      for (const element of rendered.querySelectorAll('*')) {
        for (const attribute of element.attributes) {
          expect(attribute.name.toLowerCase().startsWith('on')).toBe(false)
        }
      }
      // The positive control. Without it every assertion above could be passing on an empty element.
      expect(rendered.textContent).toContain(witness)
    })
  }
})

describe('a pandan-board embed hydrates after render (KAN-1049)', () => {
  /** A controllable `fetch`: every call returns a promise this test resolves by hand. */
  function deferredFetch(): {
    resolve: (url: string, body: unknown, status?: number) => void
    calls: string[]
  } {
    const calls: string[] = []
    const pending = new Map<string, (response: Response) => void>()
    globalThis.fetch = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      calls.push(url)
      return new Promise<Response>((resolvePromise) => {
        pending.set(url, resolvePromise)
      })
    }) as unknown as typeof fetch
    return {
      calls,
      resolve: (url, body, status = 200) => {
        const settlePending = pending.get(url)
        expect(settlePending, `no fetch is pending for ${url} (saw: ${calls.join(', ')})`).toBeDefined()
        settlePending!(
          new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }),
        )
      },
    }
  }

  const EMBED_URL = (query: string) => `/api/v1/embeds/board?${query}`

  beforeEach(() => {
    auth.setToken(FAKE_TOKEN)
  })

  it('replaces the placeholder with a read-only card list on success', async () => {
    const { resolve } = deferredFetch()
    const body =
      '# Sprint\n\n```pandan-board\nboard: 18\ncolumn: todo\n```\n'
    mounted.push(mount(PreviewPane, { target: host, props: { note: note(), source: body } }))
    await previewRendered(host)

    expect(host.querySelector('.embed-board p')?.textContent).toBe('Loading board…')

    resolve(EMBED_URL('board=18&column=todo'), {
      unavailable: false,
      cards: [{ ref: 'KAN-1', title: 'Fix the bug', column: 'todo' }],
    })
    await settle()

    const cards = host.querySelector('[data-testid="embed-board-cards"]')
    expect(cards).not.toBeNull()
    expect(cards!.textContent).toContain('KAN-1')
    expect(cards!.textContent).toContain('Fix the bug')
    expect(cards!.textContent).toContain('todo')
    expect(host.querySelector('.embed-board p')).toBeNull()
  })

  it('shows an unavailable notice when pandan answers unavailable', async () => {
    const { resolve } = deferredFetch()
    const body = '```pandan-board\nboard: 18\nview: 3\n```\n'
    mounted.push(mount(PreviewPane, { target: host, props: { note: note(), source: body } }))
    await previewRendered(host)

    resolve(EMBED_URL('board=18&view=3'), { unavailable: true, cards: [] })
    await settle()

    expect(host.querySelector('[data-testid="embed-board-unavailable"]')).not.toBeNull()
    expect(host.querySelector('[data-testid="embed-board-cards"]')).toBeNull()
  })

  it('shows the same unavailable notice when the fetch fails outright, not an error', async () => {
    globalThis.fetch = vi.fn(async () => {
      throw new TypeError('network down')
    }) as unknown as typeof fetch
    const body = '```pandan-board\nboard: 18\ncolumn: todo\n```\n'

    mounted.push(mount(PreviewPane, { target: host, props: { note: note(), source: body } }))
    await previewRendered(host)
    await settle()

    // `fetchBoardEmbed` never rejects (see `lib/embeds.ts`), so mounting and settling above must not
    // throw, and the placeholder still resolves to the one degraded state a caller can act on.
    expect(host.querySelector('[data-testid="embed-board-unavailable"]')).not.toBeNull()
  })

  it('renders a static notice for a malformed embed and makes no fetch at all', async () => {
    const { calls } = deferredFetch()
    const body = '```pandan-board\nboard: not-a-number\ncolumn: todo\n```\n'

    mounted.push(mount(PreviewPane, { target: host, props: { note: note(), source: body } }))
    await previewRendered(host)
    await settle()

    expect(host.querySelector('p.embed-board-error')).not.toBeNull()
    expect(host.querySelector('.embed-board')).toBeNull()
    // The malformed placeholder carries no `data-board`, which is what makes it invisible to
    // `hydrateBoardEmbeds` — asserted here as "no request happened", the observable half of that.
    expect(calls).toEqual([])
  })

  it('ignores a stale fetch once a later render already answered for a different embed', async () => {
    // KAN-1049's race: a re-render (any keystroke, not necessarily one inside the embed block)
    // rebuilds the whole preview, including a *new* `.embed-board` node for the same or a different
    // query, before the previous render's fetch has resolved. The old node is already out of the
    // DOM by the time its answer arrives, and the assertion is that the answer never becomes visible.
    const { resolve, calls } = deferredFetch()
    const live = box('```pandan-board\nboard: 1\ncolumn: a\n```\n')

    mounted.push(
      mount(PreviewPane, {
        target: host,
        props: {
          note: note(),
          get source() {
            return live.value
          },
        },
      }),
    )
    await previewRendered(host)
    await vi.waitFor(() => expect(calls).toContain(EMBED_URL('board=1&column=a')))

    // A second render, for a *different* board, before the first ever answers.
    live.value = '```pandan-board\nboard: 2\ncolumn: b\n```\n'
    flushSync()
    await vi.waitFor(() => expect(calls).toContain(EMBED_URL('board=2&column=b')))

    resolve(EMBED_URL('board=2&column=b'), {
      unavailable: false,
      cards: [{ ref: 'KAN-2', title: 'Second board', column: 'b' }],
    })
    await settle()

    // The stale answer, for a board no longer on screen, arrives last.
    resolve(EMBED_URL('board=1&column=a'), {
      unavailable: false,
      cards: [{ ref: 'KAN-1', title: 'STALE FIRST BOARD', column: 'a' }],
    })
    await settle()

    expect(host.textContent).not.toContain('STALE FIRST BOARD')
    expect(host.textContent).toContain('Second board')
  })
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
    await editorArrived(host)

    const view = editor(host)
    const element = host.querySelector('.cm-editor')
    typeInto(view, '# Typed before hiding')

    click('toggle-preview')
    expect(host.querySelector('[data-testid="preview"]')).toBeNull()
    click('toggle-preview')
    await settle()
    // The re-shown preview is a *new* component instance, so it loads the chunk again (from the
    // registry) before it can render.
    await previewRendered(host)

    expect(editor(host)).toBe(view)
    expect(host.querySelector('.cm-editor')).toBe(element)
    expect(view.state.doc.toString()).toBe('# Typed before hiding')
    // And the preview came back live rather than showing the note as it was on the server.
    expect(preview(host).querySelector('h1')?.textContent).toBe('Typed before hiding')
  })

  it('puts the preview beside the editor inside the shell, not inside it', async () => {
    mounted.push(mount(App, { target: host, props: {} }))
    await settle()
    await editorArrived(host)

    const rendered = preview(host)
    expect(rendered.closest('.editor-host')).toBeNull()
    expect(rendered.parentElement?.parentElement?.classList.contains('split')).toBe(true)
    expect(host.querySelector('.split > .pane')).not.toBeNull()
  })
})
