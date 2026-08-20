// @vitest-environment jsdom
/**
 * KAN-567's two CodeMirror-value-holding pieces, against a real `EditorView` —
 * `tests/editor-view.test.ts`'s sibling for the pill and the `[[` autocomplete, rather than
 * `tests/wikilinks.test.ts`'s pure predicates in `node`.
 *
 * The pill is asserted over the rendered DOM: `Decoration.mark` wraps the matched text in a real
 * `<span>` carrying the class and the `title` this card puts there, so a query for
 * `.cm-wikilink-resolved` is the same instrument `tests/editor-view.test.ts` already uses for
 * `.cm-editor`/`.cm-content`. Autocomplete goes through `@codemirror/autocomplete`'s own public API
 * (`startCompletion`, `currentCompletions`, `acceptCompletion`) rather than reaching for the private
 * source function, which is the same black-box approach that package's own test suite takes.
 */

import { acceptCompletion, currentCompletions, startCompletion } from '@codemirror/autocomplete'
import type { EditorView } from '@codemirror/view'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as auth from '../src/lib/auth'
import { createView, setWikilinks } from '../src/lib/codemirror'
import type { Link, Note } from '../src/lib/types'
import { FAKE_TOKEN } from './token'

const views: EditorView[] = []
let parent: HTMLDivElement

function open(doc: string, links: readonly Link[] = []): EditorView {
  parent = document.createElement('div')
  document.body.append(parent)
  const view = createView({
    parent,
    doc,
    editable: true,
    placeholder: '',
    links,
    onSave: () => true,
    onChange: () => {},
  })
  views.push(view)
  return view
}

function link(overrides: Partial<Link> = {}): Link {
  return {
    target_kind: 'KAN',
    target_ref: 'KAN-501',
    resolved_ref: 'KAN-501',
    title: 'MCP read tools: add a fields argument',
    column: 'in_progress',
    ...overrides,
  }
}

function note(overrides: Partial<Note> = {}): Note {
  return {
    ref: 'NOTE-9',
    id: 9,
    title: 'Weekly review',
    body: '',
    path: '',
    created_at: '2026-08-09T09:00:00+00:00',
    updated_at: '2026-08-09T09:00:00.000000+00:00',
    ...overrides,
  }
}

interface Call {
  url: string
}

function stubFetch(status: number, payload: unknown): Call[] {
  const calls: Call[] = []
  vi.stubGlobal('fetch', (url: string) => {
    calls.push({ url })
    return Promise.resolve(new Response(JSON.stringify(payload), { status }))
  })
  return calls
}

beforeEach(() => {
  auth.setToken(FAKE_TOKEN)
})

afterEach(() => {
  for (const view of views.splice(0)) {
    view.destroy()
  }
  parent?.remove()
  auth.clearToken()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('the wikilink pill', () => {
  it('renders the demo string as a resolved pill, over the raw text unchanged', () => {
    const view = open('See [[KAN-501]] for details.\n', [link()])

    const pill = view.dom.querySelector('.cm-wikilink-resolved')
    expect(pill).not.toBeNull()
    // The mark, not a widget: the caret can still select and edit exactly what was typed.
    expect(pill!.textContent).toBe('[[KAN-501]]')
    expect(pill!.getAttribute('title')).toBe(
      'KAN-501 · in_progress · "MCP read tools: add a fields argument"',
    )
  })

  it('renders a span `/links` never mentioned as muted, not as a pill', () => {
    const view = open('See [[KAN-999]] please.\n', [])

    expect(view.dom.querySelector('.cm-wikilink-resolved')).toBeNull()
    const unresolved = view.dom.querySelector('.cm-wikilink-unresolved')
    expect(unresolved).not.toBeNull()
    expect(unresolved!.getAttribute('title')).toContain('KAN-999')
  })

  it('does not decorate a wikilink written inside a fenced code block', () => {
    const view = open('```\n[[KAN-501]]\n```\n', [link()])

    expect(view.dom.querySelector('.cm-wikilink')).toBeNull()
  })

  it('updates an already-live view when a later `/links` answer arrives', () => {
    const view = open('[[KAN-501]]\n', [])
    expect(view.dom.querySelector('.cm-wikilink-resolved')).toBeNull()

    setWikilinks(view, [link()])

    expect(view.dom.querySelector('.cm-wikilink-resolved')).not.toBeNull()
  })

  it('recomputes the pill when the document changes', () => {
    const view = open('no link yet\n', [link()])
    expect(view.dom.querySelector('.cm-wikilink')).toBeNull()

    view.dispatch({ changes: { from: 0, insert: '[[KAN-501]] ' } })

    expect(view.dom.querySelector('.cm-wikilink-resolved')).not.toBeNull()
  })
})

/** Type `text` at the end of the document, as a real keystroke would leave the caret. */
function type(view: EditorView, text: string): void {
  const from = view.state.doc.length
  view.dispatch({ changes: { from, insert: text }, selection: { anchor: from + text.length } })
}

describe('`[[` autocomplete', () => {
  it('opens on `[[` and offers a note title from GET /api/v1/notes', async () => {
    const calls = stubFetch(200, { notes: [note()] })
    const view = open('')

    type(view, '[[')
    startCompletion(view)

    await vi.waitFor(() => expect(currentCompletions(view.state).length).toBeGreaterThan(0))

    expect(calls).toHaveLength(1)
    // An empty query sends no `q` at all — the same rule `App.svelte`'s cleared search box follows.
    expect(calls[0].url).toBe('/api/v1/notes')
    expect(currentCompletions(view.state).map((option) => option.label)).toContain('Weekly review')
  })

  it('searches by the text typed since `[[`', async () => {
    const calls = stubFetch(200, { notes: [note()] })
    const view = open('')

    type(view, '[[week')
    startCompletion(view)

    await vi.waitFor(() => expect(calls.length).toBeGreaterThan(0))
    expect(calls[0].url).toBe('/api/v1/notes?q=week')
  })

  it('inserts `[[Title]]` when a suggestion is accepted', async () => {
    stubFetch(200, { notes: [note({ title: 'Weekly review' })] })
    const view = open('')

    type(view, '[[')
    startCompletion(view)
    await vi.waitFor(() => expect(currentCompletions(view.state).length).toBeGreaterThan(0))
    // `acceptCompletion` refuses within `interactionDelay` of the panel opening, to guard against an
    // accidental accept on the same keystroke that opened it — not this card's concern, but real
    // enough that the test has to out-wait it.
    await new Promise((resolve) => setTimeout(resolve, 150))

    expect(acceptCompletion(view)).toBe(true)
    expect(view.state.doc.toString()).toBe('[[Weekly review]]')
  })

  it('offers nothing once the brackets are already closed', async () => {
    const calls = stubFetch(200, { notes: [note()] })
    const view = open('[[KAN-501]]')
    view.dispatch({ selection: { anchor: view.state.doc.length } })

    // `startCompletion` only reports whether the extension is present, not whether a source found
    // anything (`@codemirror/autocomplete`'s own implementation checks a state field and nothing
    // else) — so the source's actual decision is asserted the same way the tests above assert a
    // *positive* one: by settling and reading `currentCompletions`.
    startCompletion(view)
    await new Promise((resolve) => setTimeout(resolve, 20))

    expect(currentCompletions(view.state)).toEqual([])
    expect(calls).toHaveLength(0)
  })
})
