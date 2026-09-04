// @vitest-environment jsdom
/**
 * `EditorPane` as the app mounts it: the guards wired through Svelte 5's reactivity, the save, and
 * ADR 0009's `409`.
 *
 * The three files stack deliberately. `editor-guards.test.ts` is the decisions, in `node`, where
 * jsdom cannot get in the way. `editor-view.test.ts` is those decisions against a real `EditorView`.
 * This one is the part neither can see: whether the effect *calls* them at the right moments, which
 * is where the update loop actually lives — CLAUDE.md, "a structural guard does not cover a
 * behavioural claim, even when it reads as though it does".
 *
 * **Node identity is the instrument.** `container.firstElementChild` is CM6's own root, so "the view
 * was not rebuilt" is `toBe` on a DOM node rather than a count of constructor calls, and it is exactly
 * the check the browser run does by hand.
 */

import { undo } from '@codemirror/commands'
import { EditorView } from '@codemirror/view'
import { flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import EditorPane from '../src/components/EditorPane.svelte'
import * as auth from '../src/lib/auth'
import type { Note } from '../src/lib/types'
import { editorArrived } from './editor-arrival'
import { box, type Box } from './reactive.svelte'
import { FAKE_TOKEN } from './token'

/**
 * Six fractional digits, everywhere, on purpose.
 *
 * ADR 0009's comparison is exact to the microsecond and `new Date(s).toISOString()` rounds to
 * milliseconds, so a fixture ending in `.123456` is what makes "carried as an opaque string" a claim a
 * test can refute rather than a comment.
 */
const READ_AT = '2026-08-09T10:00:00.123456+00:00'
const SAVED_AT = '2026-08-09T10:07:31.987654+00:00'
const THEIRS_AT = '2026-08-09T10:05:12.246802+00:00'

function note(overrides: Partial<Note> = {}): Note {
  return {
    ref: 'NOTE-6',
    id: 6,
    title: 'Weekly review',
    body: '# Week of 2026-08-03\n',
    path: 'journal/2026/08/weekly-review.md',
    created_at: '2026-08-09T09:00:00+00:00',
    updated_at: READ_AT,
    team_id: null,
    ...overrides,
  }
}

let host: HTMLDivElement
const mounted: unknown[] = []

/**
 * Mount the pane with a *reactive* note, so a test can hand down a new object and watch.
 *
 * `async` since KAN-767: CodeMirror is behind a dynamic `import()`, so `flushSync()` alone leaves the
 * container empty and every assertion about a view has to await the chunk. See `editor-arrival.ts`.
 */
async function open(initial: Note | null): Promise<{
  opened: Box<Note | null>
  container: HTMLElement
}> {
  const opened = box<Note | null>(initial)
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
  flushSync()
  await editorArrived(host)
  return { opened, container: host.querySelector('.editor-host')! }
}

/** The live `EditorView` inside the container, reached the way CM6 itself offers. */
function editor(container: HTMLElement): EditorView {
  return EditorView.findFromDOM(container.querySelector('.cm-editor')!)!
}

/** A keystroke, as CM6 sees one: a transaction the user caused. */
function type(view: EditorView, text: string): void {
  view.dispatch({
    changes: { from: view.state.doc.length, insert: text },
    userEvent: 'input.type',
  })
  flushSync()
}

interface Call {
  url: string
  method: string
  body: Record<string, unknown>
}

/** Answer every request with one status and one payload, and record what was asked. */
function stubFetch(status: number, payload: unknown): Call[] {
  const calls: Call[] = []
  vi.stubGlobal('fetch', (url: string, init: RequestInit) => {
    calls.push({
      url,
      method: init.method ?? 'GET',
      body: JSON.parse(String(init.body)) as Record<string, unknown>,
    })
    return Promise.resolve(new Response(JSON.stringify(payload), { status }))
  })
  return calls
}

const settled = () => vi.waitFor(() => expect(host.querySelector('[data-testid]')).not.toBeNull())

beforeEach(() => {
  host = document.createElement('div')
  document.body.append(host)
  auth.setToken(FAKE_TOKEN)
})

afterEach(() => {
  for (const instance of mounted.splice(0)) {
    unmount(instance as never)
  }
  host.remove()
  auth.clearToken()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('the identity guard, through Svelte', () => {
  it('does not rebuild the view when the parent hands down a new object for the same note', async () => {
    // The card. The parent replaces the whole `Note` — which is what a parent bound to a keystroke
    // does — and the effect re-runs, because reading the prop at all registers it. What must not
    // happen is a second `EditorView`.
    const destroy = vi.spyOn(EditorView.prototype, 'destroy')
    const { opened, container } = await open(note())
    const first = container.firstElementChild

    for (let n = 0; n < 20; n += 1) {
      opened.value = note({ body: `# Week of 2026-08-03\nline ${n}\n` })
      flushSync()
    }

    expect(container.firstElementChild).toBe(first)
    expect(container.querySelectorAll('.cm-editor')).toHaveLength(1)
    expect(destroy).not.toHaveBeenCalled()
  })

  it('keeps the caret and the undo history across those re-renders', async () => {
    // What a rebuild would cost, stated as the thing a user notices: the cursor jumping to the start.
    const { opened, container } = await open(note())
    const view = editor(container)
    type(view, 'X')
    const caret = view.state.selection.main.head

    opened.value = note({ title: 'Renamed in the sidebar' })
    flushSync()

    expect(editor(container)).toBe(view)
    expect(view.state.selection.main.head).toBe(caret)
  })

  it('rebuilds exactly once when the ref changes, because that is a different note', async () => {
    const destroy = vi.spyOn(EditorView.prototype, 'destroy')
    const { opened, container } = await open(note())
    const first = container.firstElementChild

    opened.value = note({ ref: 'NOTE-7', id: 7, title: 'Architecture', body: 'other\n' })
    flushSync()

    expect(destroy).toHaveBeenCalledTimes(1)
    expect(container.firstElementChild).not.toBe(first)
    // One view per container at all times. A missing `destroy()` shows up here as two.
    expect(container.querySelectorAll('.cm-editor')).toHaveLength(1)
    expect(container.querySelector('.cm-content')!.textContent).toContain('other')
  })

  it('tears down on unmount rather than leaking the view', async () => {
    const destroy = vi.spyOn(EditorView.prototype, 'destroy')
    const instance = mount(EditorPane, { target: host, props: { note: note(), error: null } })
    await editorArrived(host)

    unmount(instance)
    flushSync()

    expect(destroy).toHaveBeenCalledTimes(1)
    expect(host.querySelector('.cm-editor')).toBeNull()
  })

  it('visits five notes and leaves five nothings behind', async () => {
    // SLICES §V3, "no leaked listeners", counted. An `EditorView` per visited note, all still
    // listening, is a leak that looks like nothing until the app is slow.
    const destroy = vi.spyOn(EditorView.prototype, 'destroy')
    const { opened, container } = await open(note())

    for (const ref of ['NOTE-7', 'NOTE-8', 'NOTE-9', 'NOTE-10']) {
      opened.value = note({ ref })
      flushSync()
      expect(container.querySelectorAll('.cm-editor')).toHaveLength(1)
    }

    expect(destroy).toHaveBeenCalledTimes(4)
  })
})

describe('the echo guard, through Svelte', () => {
  it('dispatches nothing when the parent re-sends the body already in the editor', async () => {
    // The loop's shape without the loop: whatever put the value there, if the editor already holds it
    // there is nothing to write. Asserted through `dispatch` rather than through the document, because
    // the document would look identical either way — a no-op transaction is still a transaction, and a
    // transaction is what wakes the listener that starts the cycle.
    const { opened, container } = await open(note({ body: 'same\n' }))
    const view = editor(container)
    const dispatch = vi.spyOn(view, 'dispatch')

    opened.value = note({ body: 'same\n' })
    flushSync()

    expect(dispatch).not.toHaveBeenCalled()
  })

  it('does not overwrite in-flight typing when the parent re-sends an unchanged note', async () => {
    // The other half, and the reason it is a separate check from the echo guard: here the incoming
    // body *does* differ from the document, because the user typed — so the echo guard would let it
    // through and the edit would vanish on a re-render that changed nothing.
    const { opened, container } = await open(note({ body: 'server\n' }))
    const view = editor(container)
    type(view, 'mine')

    opened.value = note({ body: 'server\n' })
    flushSync()

    expect(view.state.doc.toString()).toBe('server\nmine')
  })

  it('applies a genuinely new body for the same note as a transaction', async () => {
    const { opened, container } = await open(note({ body: 'first\n' }))
    const view = editor(container)
    const node = container.firstElementChild

    opened.value = note({ body: 'second\n' })
    flushSync()

    expect(view.state.doc.toString()).toBe('second\n')
    expect(container.firstElementChild).toBe(node)
  })
})

describe('what the mounted editor actually is', () => {
  it('installs the markdown language, in the component and not only in a test', async () => {
    // `editor-view.test.ts` proves the grammar parses what the product needs; that test builds its own
    // view, so on its own it would stay green if this component installed no language at all. CM6
    // stamps the active language onto `.cm-content`, which closes the gap from this side.
    const { container } = await open(note())

    expect(container.querySelector('.cm-content')!.getAttribute('data-language')).toBe('markdown')
  })

  it('is editable, wraps lines, and has an undo history', async () => {
    const { container } = await open(note())
    const view = editor(container)

    expect(container.querySelector('.cm-content')!.getAttribute('contenteditable')).toBe('true')
    expect(container.querySelector('.cm-lineWrapping')).not.toBeNull()

    type(view, 'undo me')
    expect(view.state.doc.toString()).toContain('undo me')
    expect(undo(view)).toBe(true)
    expect(view.state.doc.toString()).not.toContain('undo me')
  })
})

describe('the zero state', () => {
  it("is CM6's own placeholder, so the container still holds nothing Svelte made", async () => {
    const { container } = await open(null)

    expect(container.querySelectorAll(':scope > .cm-editor')).toHaveLength(1)
    expect(container.textContent).toContain('No note open')
    // Not editable, because there is nothing to edit and no ref to save it to.
    expect(container.querySelector('.cm-content')!.getAttribute('contenteditable')).toBe('false')
  })
})

describe('KAN-969: the dirty seam and beforeunload', () => {
  /** Mount with `ondirty` wired to a spy, so a test can read every value the pane ever published. */
  async function openWithDirtySpy(initial: Note | null): Promise<{
    opened: Box<Note | null>
    container: HTMLElement
    dirtyValues: boolean[]
  }> {
    const opened = box<Note | null>(initial)
    const dirtyValues: boolean[] = []
    mounted.push(
      mount(EditorPane, {
        target: host,
        props: {
          get note() {
            return opened.value
          },
          error: null,
          ondirty: (value: boolean) => dirtyValues.push(value),
        },
      }),
    )
    flushSync()
    await editorArrived(host)
    return { opened, container: host.querySelector('.editor-host')!, dirtyValues }
  }

  it('reports clean on mount and dirty on the first keystroke', async () => {
    const { container, dirtyValues } = await openWithDirtySpy(note())
    // The initial mount already published one value (see the mount effect: `dirty = false`, which
    // this seam's own effect turns into one call), so the interesting read starts from there.
    expect(dirtyValues.at(-1)).toBe(false)

    type(editor(container), 'X')

    expect(dirtyValues.at(-1)).toBe(true)
  })

  it('reports clean again once a save with no failure resolves', async () => {
    stubFetch(200, note({ body: '# Week of 2026-08-03\nX', updated_at: SAVED_AT }))
    const { container, dirtyValues } = await openWithDirtySpy(note())

    type(editor(container), 'X')
    expect(dirtyValues.at(-1)).toBe(true)

    host.querySelector('button')!.click()
    await settled()
    await vi.waitFor(() => expect(dirtyValues.at(-1)).toBe(false))
  })

  it('reports clean on a remount — opening a different note without saving', async () => {
    // This is the case the identity guard already handles; the seam only has to notice. It also
    // means the parent's own "may I navigate" answer stops citing stale content the moment the
    // remount actually happens, which is only reachable once a navigation was already allowed.
    const { opened, container, dirtyValues } = await openWithDirtySpy(note())
    type(editor(container), 'X')
    expect(dirtyValues.at(-1)).toBe(true)

    opened.value = note({ ref: 'NOTE-7', id: 7, title: 'Architecture', body: 'other\n' })
    flushSync()

    expect(dirtyValues.at(-1)).toBe(false)
  })

  it('never lets the mount effect read dirty back — a rebuild happens exactly once either way', async () => {
    // The constraint from CLAUDE.md/the card: `ondirty` must not be a way for the mount effect to
    // depend on its own output. `tests/document-seam.test.ts` proves this structurally (the callback
    // is read only inside `untrack`); this is the behavioural half — if the wiring somehow *did*
    // create a feedback loop, the identity guard would still refuse to remount for an unchanged ref,
    // so the only observable symptom would be `destroy()` firing more than once for one ref change.
    const destroy = vi.spyOn(EditorView.prototype, 'destroy')
    const { opened, container } = await openWithDirtySpy(note())
    type(editor(container), 'X')

    opened.value = note({ ref: 'NOTE-7', id: 7, body: 'other\n' })
    flushSync()

    expect(destroy).toHaveBeenCalledTimes(1)
  })

  /** Fire a real `beforeunload` on `window` and report what the listener decided. */
  function unload(): { defaultPrevented: boolean } {
    const event = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(event)
    return { defaultPrevented: event.defaultPrevented }
  }

  it('does not ask to stay when there is nothing unsaved', async () => {
    await open(note())

    expect(unload().defaultPrevented).toBe(false)
  })

  it('asks to stay while the editor is dirty', async () => {
    const { container } = await open(note())
    type(editor(container), 'X')

    expect(unload().defaultPrevented).toBe(true)
  })

  it('stops asking once the edit is saved', async () => {
    stubFetch(200, note({ body: '# Week of 2026-08-03\nX', updated_at: SAVED_AT }))
    const { container } = await open(note())
    type(editor(container), 'X')
    expect(unload().defaultPrevented).toBe(true)

    host.querySelector('button')!.click()
    // `now at`, not merely "does not contain `unsaved`" — `saving…` does not contain it either, and
    // waiting on that would assert nothing about whether the request actually finished (see the
    // comment on the identically-shaped wait a few tests up).
    await vi.waitFor(() =>
      expect(host.querySelector('[data-testid="save-state"]')!.textContent).toContain('now at'),
    )

    expect(unload().defaultPrevented).toBe(false)
  })

  it('removes its own listener on unmount, so a destroyed pane cannot still ask', async () => {
    const instance = mount(EditorPane, { target: host, props: { note: note(), error: null } })
    await editorArrived(host)
    type(editor(host.querySelector('.editor-host')!), 'X')
    expect(unload().defaultPrevented).toBe(true)

    unmount(instance)
    flushSync()

    expect(unload().defaultPrevented).toBe(false)
  })
})

describe("saving, and ADR 0009's precondition", () => {
  it('PATCHes the body with the updated_at it read, to the microsecond', async () => {
    const calls = stubFetch(200, note({ body: '# Week of 2026-08-03\nX', updated_at: SAVED_AT }))
    const { container } = await open(note())
    type(editor(container), 'X')

    host.querySelector('button')!.click()
    await settled()
    await vi.waitFor(() => expect(calls).toHaveLength(1))

    expect(calls[0].url).toBe('/api/v1/notes/NOTE-6')
    expect(calls[0].method).toBe('PATCH')
    expect(calls[0].body).toEqual({ body: '# Week of 2026-08-03\nX', if_updated_at: READ_AT })
    // Verbatim, not merely equal after parsing. `.123456` survives or every correct write is refused.
    expect(calls[0].body.if_updated_at).toBe(READ_AT)
  })

  it('bases the next write on the stamp the response returned, and never on a fresh read', async () => {
    // The rule from `kaya note edit`: the client never fetches the precondition. A read-before-write
    // looks safer and disables the guarantee, because the token would then name a version read
    // microseconds ago instead of the version this edit was made against. So exactly one request per
    // save, and its precondition comes from the previous *response*.
    const calls = stubFetch(200, note({ updated_at: SAVED_AT }))
    const { container } = await open(note())
    const view = editor(container)

    type(view, 'one')
    host.querySelector('button')!.click()
    // `now at`, not `saved` — "unsaved changes" contains "saved", so waiting on that substring
    // matches the state it is meant to wait *past* and the second click lands mid-flight.
    await vi.waitFor(() =>
      expect(host.querySelector('[data-testid="save-state"]')!.textContent).toContain('now at'),
    )

    type(view, 'two')
    flushSync()
    host.querySelector('button')!.click()
    await vi.waitFor(() => expect(calls).toHaveLength(2))

    expect(calls[0].body.if_updated_at).toBe(READ_AT)
    expect(calls[1].body.if_updated_at).toBe(SAVED_AT)
    // Two saves, two requests. A read-before-write would make it four.
    expect(calls).toHaveLength(2)
  })

  it('still reads as unsaved when you typed during the round trip', async () => {
    // Found by the test above going red, so it is written down here rather than fixed quietly
    // (CLAUDE.md: every bug becomes a test). The first version cleared `dirty` unconditionally on
    // success, which marked keystrokes saved that the finished request had never seen — and the
    // *next* save would then send them under a precondition it had already used, so the mystery
    // arrived later as a `409`. `dirty` is now compared against the body that was actually sent.
    const calls = stubFetch(200, note({ updated_at: SAVED_AT }))
    const { container } = await open(note())
    const view = editor(container)

    type(view, 'one')
    host.querySelector('button')!.click()
    // Typed while the request is in flight: the click above has not resolved yet.
    type(view, 'two')

    await vi.waitFor(() => expect(calls).toHaveLength(1))
    await vi.waitFor(() =>
      expect(host.querySelector('[data-testid="save-state"]')!.textContent).toContain('unsaved'),
    )
    expect(host.querySelector('button')!.disabled).toBe(false)
  })

  it('reports the stamp the editor is now guarded against, not the stale prop', async () => {
    stubFetch(200, note({ updated_at: SAVED_AT }))
    const { container } = await open(note())
    expect(host.querySelector('.stamp')!.textContent).toContain(READ_AT)

    type(editor(container), 'X')
    host.querySelector('button')!.click()

    await vi.waitFor(() => expect(host.querySelector('.stamp')!.textContent).toContain(SAVED_AT))
  })
})

describe("ADR 0009's 409, which must not be swallowed", () => {
  const attempted = note({ body: 'mine\n', updated_at: READ_AT })
  const stored = note({ body: 'theirs\n', updated_at: THEIRS_AT })

  function refuse() {
    return stubFetch(409, {
      error: {
        code: 'note_conflict',
        message: 'This note changed since you read it.',
        attempted,
        stored,
      },
    })
  }

  it('shows the refusal and both timestamps', async () => {
    refuse()
    const { container } = await open(note())
    type(editor(container), 'mine')
    host.querySelector('button')!.click()

    await vi.waitFor(() => expect(host.querySelector('[data-testid="conflict"]')).not.toBeNull())

    const banner = host.querySelector('[data-testid="conflict"]')!
    expect(banner.textContent).toContain('nothing was written')
    expect(host.querySelector('[data-testid="conflict-attempted"]')!.textContent).toBe(READ_AT)
    expect(host.querySelector('[data-testid="conflict-stored"]')!.textContent).toBe(THEIRS_AT)
  })

  it('leaves the edit in the editor and the note still unsaved', async () => {
    // Nothing was written, so nothing may be discarded either — least of all the text the refusal is
    // about. KAN-556's "keep mine" has nothing to keep if this is wrong.
    refuse()
    const { container } = await open(note())
    const view = editor(container)
    type(view, 'mine')
    host.querySelector('button')!.click()

    await vi.waitFor(() => expect(host.querySelector('[data-testid="conflict"]')).not.toBeNull())

    expect(view.state.doc.toString()).toContain('mine')
    expect(host.querySelector('[data-testid="save-state"]')!.textContent).toContain('unsaved')
  })

  it("says something on a 409 whose extras it cannot read, because it is still a 409", async () => {
    // A conflict that fails to parse is a conflict. Silence here is the exact failure ADR 0009 exists
    // to prevent — the user believing a save happened.
    stubFetch(409, { error: { code: 'note_conflict', message: 'Refused: stale precondition.' } })
    const { container } = await open(note())
    type(editor(container), 'mine')
    host.querySelector('button')!.click()

    await vi.waitFor(() => expect(host.querySelector('[data-testid="save-error"]')).not.toBeNull())

    expect(host.querySelector('[data-testid="save-error"]')!.textContent).toContain('stale')
    expect(host.querySelector('[data-testid="conflict"]')).toBeNull()
  })

  it('surfaces any other refusal rather than looking saved', async () => {
    stubFetch(404, { error: { code: 'note_not_found', message: 'No note NOTE-6.' } })
    const { container } = await open(note())
    type(editor(container), 'X')
    host.querySelector('button')!.click()

    await vi.waitFor(() => expect(host.querySelector('[data-testid="save-error"]')).not.toBeNull())

    expect(host.querySelector('[data-testid="save-error"]')!.textContent).toContain('No note NOTE-6')
    expect(host.querySelector('[data-testid="save-state"]')!.textContent).toContain('unsaved')
  })

  it('never puts the credential anywhere a screenshot would catch it', async () => {
    refuse()
    const { container } = await open(note())
    type(editor(container), 'mine')
    host.querySelector('button')!.click()
    await vi.waitFor(() => expect(host.querySelector('[data-testid="conflict"]')).not.toBeNull())

    // Four-character fragments, as `kaya config show` is checked: a mask is a fragment with asterisks
    // in front of it. A save error is prose from the API and a conflict carries two whole notes, so
    // both are places a token could arrive by accident.
    for (let start = 0; start + 4 <= FAKE_TOKEN.length; start += 1) {
      expect(document.body.innerHTML).not.toContain(FAKE_TOKEN.slice(start, start + 4))
    }
  })
})

describe('the Delete control (KAN-1041, BREADBOARD.md A2)', () => {
  /**
   * Answers a `DELETE` with `204` (no body — `stubFetch` above assumes every request sends a JSON
   * body, which a `DELETE` never does) and anything else with a JSON error. Records every request.
   */
  function stubDelete(status: number, errorBody: unknown = { error: { code: 'not_found', message: 'Gone.' } }) {
    const calls: { url: string; method: string }[] = []
    vi.stubGlobal('fetch', (url: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET'
      calls.push({ url, method })
      if (method !== 'DELETE') {
        // The `/links` fetch the mount effect always makes. Its own failures are silent (see
        // `loadLinks`), so a 404 here changes nothing this block asserts.
        return Promise.resolve(new Response(JSON.stringify({ error: { code: 'not_found', message: 'x' } }), { status: 404 }))
      }
      if (status === 204) {
        return Promise.resolve(new Response(null, { status: 204 }))
      }
      return Promise.resolve(new Response(JSON.stringify(errorBody), { status }))
    })
    return calls
  }

  function deleteButton(): HTMLButtonElement {
    return host.querySelector<HTMLButtonElement>('[data-testid="delete-button"]')!
  }

  it('reads "Delete" before anything is clicked', async () => {
    stubDelete(204)
    await open(note())
    expect(deleteButton().textContent?.trim()).toBe('Delete')
    expect(host.querySelector('[data-testid="delete-cancel"]')).toBeNull()
  })

  it('arms on the first click without calling the API', async () => {
    const calls = stubDelete(204)
    await open(note())

    deleteButton().click()
    flushSync()

    expect(deleteButton().textContent?.trim()).toBe('Confirm delete?')
    expect(calls.some((call) => call.method === 'DELETE')).toBe(false)
    expect(host.querySelector('[data-testid="delete-cancel"]')).not.toBeNull()
  })

  it('Cancel disarms without calling the API', async () => {
    const calls = stubDelete(204)
    await open(note())

    deleteButton().click()
    flushSync()
    host.querySelector<HTMLButtonElement>('[data-testid="delete-cancel"]')!.click()
    flushSync()

    expect(deleteButton().textContent?.trim()).toBe('Delete')
    expect(host.querySelector('[data-testid="delete-cancel"]')).toBeNull()
    expect(calls.some((call) => call.method === 'DELETE')).toBe(false)
  })

  it('deletes on the second click and fires ondeleted with the ref', async () => {
    const calls = stubDelete(204)
    const ondeleted = vi.fn()
    const opened = box<Note | null>(note())
    mounted.push(
      mount(EditorPane, {
        target: host,
        props: {
          get note() {
            return opened.value
          },
          error: null,
          ondeleted,
        },
      }),
    )
    flushSync()
    await editorArrived(host)

    deleteButton().click()
    flushSync()
    deleteButton().click()
    await vi.waitFor(() => expect(ondeleted).toHaveBeenCalledTimes(1))

    expect(ondeleted).toHaveBeenCalledWith('NOTE-6')
    const deleteCall = calls.find((call) => call.method === 'DELETE')
    expect(deleteCall?.url).toBe('/api/v1/notes/NOTE-6')
  })

  it('shows a refusal and disarms rather than calling ondeleted', async () => {
    stubDelete(404, { error: { code: 'note_not_found', message: 'No note NOTE-6.' } })
    const ondeleted = vi.fn()
    mounted.push(mount(EditorPane, { target: host, props: { note: note(), error: null, ondeleted } }))
    flushSync()
    await editorArrived(host)

    deleteButton().click()
    flushSync()
    deleteButton().click()

    await vi.waitFor(() => expect(host.querySelector('[data-testid="delete-error"]')).not.toBeNull())
    expect(host.querySelector('[data-testid="delete-error"]')!.textContent).toContain('No note NOTE-6')
    expect(ondeleted).not.toHaveBeenCalled()
    expect(deleteButton().textContent?.trim()).toBe('Delete')
  })

  it('resets arming when a different note opens, so a stray second click cannot delete it', async () => {
    // This component is mounted once for the app's whole lifetime (PLAN §S9) — only `note` changes as
    // you navigate. Arming Delete on NOTE-6 and then opening NOTE-7 without confirming must not leave
    // NOTE-7's button one click from deleting it.
    const calls = stubDelete(204)
    const opened = box<Note | null>(note())
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
    flushSync()
    await editorArrived(host)

    deleteButton().click()
    flushSync()
    expect(deleteButton().textContent?.trim()).toBe('Confirm delete?')

    opened.value = note({ ref: 'NOTE-7', title: 'Architecture notes' })
    flushSync()
    await editorArrived(host)

    expect(deleteButton().textContent?.trim()).toBe('Delete')
    deleteButton().click()
    flushSync()
    expect(deleteButton().textContent?.trim()).toBe('Confirm delete?')
    expect(calls.some((call) => call.method === 'DELETE')).toBe(false)
  })
})

describe('the title field (KAN-1042, BREADBOARD.md A4)', () => {
  /** Every `PATCH` to `title`; every other request (the mount effect's own `/links` fetch) is a
   *  harmless 404, since a failed `/links` fetch is silent (see `loadLinks`). */
  function stubTitlePatch(status: number, payload: unknown) {
    const calls: { url: string; body: Record<string, unknown> }[] = []
    vi.stubGlobal('fetch', (url: string, init: RequestInit = {}) => {
      if ((init.method ?? 'GET') !== 'PATCH') {
        return Promise.resolve(new Response(JSON.stringify({ error: { code: 'not_found', message: 'x' } }), { status: 404 }))
      }
      calls.push({ url, body: JSON.parse(String(init.body)) as Record<string, unknown> })
      return Promise.resolve(new Response(JSON.stringify(payload), { status }))
    })
    return calls
  }

  function titleInput(): HTMLInputElement {
    return host.querySelector<HTMLInputElement>('[data-testid="title-input"]')!
  }

  function retype(value: string): void {
    titleInput().value = value
    titleInput().dispatchEvent(new Event('input'))
    flushSync()
  }

  it('starts with the note title, editable', async () => {
    stubTitlePatch(200, note())
    await open(note())
    expect(titleInput().value).toBe('Weekly review')
    expect(titleInput().disabled).toBe(false)
  })

  it('PATCHes only the title on blur, with no if_updated_at', async () => {
    const calls = stubTitlePatch(200, note({ title: 'New title', updated_at: SAVED_AT }))
    await open(note())

    retype('New title')
    titleInput().dispatchEvent(new Event('blur'))
    await vi.waitFor(() => expect(calls).toHaveLength(1))

    expect(calls[0].url).toBe('/api/v1/notes/NOTE-6')
    expect(calls[0].body).toEqual({ title: 'New title' })
  })

  it('sends nothing when the title did not change', async () => {
    const calls = stubTitlePatch(200, note())
    await open(note())

    titleInput().dispatchEvent(new Event('blur'))
    flushSync()

    expect(calls).toHaveLength(0)
  })

  it('Enter commits the same way blur does', async () => {
    const calls = stubTitlePatch(200, note({ title: 'Via Enter', updated_at: SAVED_AT }))
    await open(note())

    // `titleKeydown` calls `.blur()` imperatively, and `.blur()` only fires a `blur` event in jsdom
    // (as in a real browser) when the element was actually focused — which typing into it, here, is.
    // `bubbles: true` matters here for a reason unrelated to focus: Svelte 5 delegates common events
    // like `keydown` to one root listener and relies on bubbling to reach it, so a keydown dispatched
    // without it never reaches the handler at all — unlike `blur`, which does not bubble and so is
    // attached directly, which is why the plain `Event('blur')` used elsewhere in this file works.
    titleInput().focus()
    retype('Via Enter')
    titleInput().dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    await vi.waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].body).toEqual({ title: 'Via Enter' })
  })

  it("fires onupdated with the fresh note, so App.svelte's separate sidebar list can update", async () => {
    stubTitlePatch(200, note({ title: 'New title', updated_at: SAVED_AT }))
    const onupdated = vi.fn()
    mounted.push(mount(EditorPane, { target: host, props: { note: note(), error: null, onupdated } }))
    flushSync()
    await editorArrived(host)

    retype('New title')
    titleInput().dispatchEvent(new Event('blur'))
    await vi.waitFor(() => expect(onupdated).toHaveBeenCalledTimes(1))

    expect(onupdated).toHaveBeenCalledWith(expect.objectContaining({ ref: 'NOTE-6', title: 'New title' }))
  })

  it('refreshes the body-save precondition from the response, so the next Save is not a spurious 409', async () => {
    // `updated_at` is `onupdate=func.now()` on the backend, so a title-only write moves it exactly as
    // a body write would. Leaving `basedOn` at the value read on open would guard the next Save
    // against a stamp the row no longer has.
    stubTitlePatch(200, note({ title: 'New title', updated_at: SAVED_AT }))
    await open(note())

    retype('New title')
    titleInput().dispatchEvent(new Event('blur'))
    await vi.waitFor(() => expect(host.querySelector('.stamp')!.textContent).toContain(SAVED_AT))
  })

  it('shows a refusal and leaves what was typed rather than reverting it', async () => {
    stubTitlePatch(422, { error: { code: 'validation_error', message: 'Title is too long.' } })
    await open(note())

    retype('New title')
    titleInput().dispatchEvent(new Event('blur'))

    await vi.waitFor(() => expect(host.querySelector('[data-testid="title-error"]')).not.toBeNull())
    expect(host.querySelector('[data-testid="title-error"]')!.textContent).toContain('too long')
    expect(titleInput().value).toBe('New title')
  })

  it('resets to the new note when a different note opens, discarding an unsaved draft', async () => {
    stubTitlePatch(200, note())
    const { opened } = await open(note())

    retype('Not sent anywhere')
    opened.value = note({ ref: 'NOTE-7', title: 'Architecture notes' })
    flushSync()
    await editorArrived(host)

    expect(titleInput().value).toBe('Architecture notes')
  })
})

describe('the path field (KAN-1043, BREADBOARD.md A3)', () => {
  /** Every `PATCH` to `path`; every other request (the mount effect's own `/links` fetch) is a
   *  harmless 404, since a failed `/links` fetch is silent (see `loadLinks`). */
  function stubPathPatch(status: number, payload: unknown) {
    const calls: { url: string; body: Record<string, unknown> }[] = []
    vi.stubGlobal('fetch', (url: string, init: RequestInit = {}) => {
      if ((init.method ?? 'GET') !== 'PATCH') {
        return Promise.resolve(new Response(JSON.stringify({ error: { code: 'not_found', message: 'x' } }), { status: 404 }))
      }
      calls.push({ url, body: JSON.parse(String(init.body)) as Record<string, unknown> })
      return Promise.resolve(new Response(JSON.stringify(payload), { status }))
    })
    return calls
  }

  function pathInput(): HTMLInputElement {
    return host.querySelector<HTMLInputElement>('[data-testid="path-input"]')!
  }

  function retype(value: string): void {
    pathInput().value = value
    pathInput().dispatchEvent(new Event('input'))
    flushSync()
  }

  it('starts with the note path, editable', async () => {
    stubPathPatch(200, note())
    await open(note())
    expect(pathInput().value).toBe('journal/2026/08/weekly-review.md')
    expect(pathInput().disabled).toBe(false)
  })

  it('shows "(no folder)" as a placeholder, not text, for a note with no path', async () => {
    stubPathPatch(200, note({ path: '' }))
    await open(note({ path: '' }))
    expect(pathInput().value).toBe('')
    expect(pathInput().placeholder).toBe('(no folder)')
  })

  it('PATCHes only the path on blur, with no if_updated_at', async () => {
    const calls = stubPathPatch(200, note({ path: 'archive/weekly-review.md', updated_at: SAVED_AT }))
    await open(note())

    retype('archive/weekly-review.md')
    pathInput().dispatchEvent(new Event('blur'))
    await vi.waitFor(() => expect(calls).toHaveLength(1))

    expect(calls[0].url).toBe('/api/v1/notes/NOTE-6')
    expect(calls[0].body).toEqual({ path: 'archive/weekly-review.md' })
  })

  it('sends nothing when the path did not change', async () => {
    const calls = stubPathPatch(200, note())
    await open(note())

    pathInput().dispatchEvent(new Event('blur'))
    flushSync()

    expect(calls).toHaveLength(0)
  })

  it('never PATCHes on typing alone — only on blur', async () => {
    const calls = stubPathPatch(200, note({ path: 'archive/weekly-review.md' }))
    await open(note())

    retype('archive/weekly-review.md')

    expect(calls).toHaveLength(0)
  })

  it("fires onupdated with the fresh note, so App.svelte's separate sidebar list can update", async () => {
    stubPathPatch(200, note({ path: 'archive/weekly-review.md', updated_at: SAVED_AT }))
    const onupdated = vi.fn()
    mounted.push(mount(EditorPane, { target: host, props: { note: note(), error: null, onupdated } }))
    flushSync()
    await editorArrived(host)

    retype('archive/weekly-review.md')
    pathInput().dispatchEvent(new Event('blur'))
    await vi.waitFor(() => expect(onupdated).toHaveBeenCalledTimes(1))

    expect(onupdated).toHaveBeenCalledWith(
      expect.objectContaining({ ref: 'NOTE-6', path: 'archive/weekly-review.md' }),
    )
  })

  it('refreshes the body-save precondition from the response, so the next Save is not a spurious 409', async () => {
    stubPathPatch(200, note({ path: 'archive/weekly-review.md', updated_at: SAVED_AT }))
    await open(note())

    retype('archive/weekly-review.md')
    pathInput().dispatchEvent(new Event('blur'))
    await vi.waitFor(() => expect(host.querySelector('.stamp')!.textContent).toContain(SAVED_AT))
  })

  it('shows a refusal and leaves what was typed rather than reverting it', async () => {
    stubPathPatch(422, { error: { code: 'validation_error', message: 'Path is invalid.' } })
    await open(note())

    retype('bad//path')
    pathInput().dispatchEvent(new Event('blur'))

    await vi.waitFor(() => expect(host.querySelector('[data-testid="path-error"]')).not.toBeNull())
    expect(host.querySelector('[data-testid="path-error"]')!.textContent).toContain('invalid')
    expect(pathInput().value).toBe('bad//path')
  })

  it('resets to the new note when a different note opens, discarding an unsaved draft', async () => {
    stubPathPatch(200, note())
    const { opened } = await open(note())

    retype('not/sent/anywhere.md')
    opened.value = note({ ref: 'NOTE-7', title: 'Architecture notes', path: 'architecture.md' })
    flushSync()
    await editorArrived(host)

    expect(pathInput().value).toBe('architecture.md')
  })
})

describe("the team badge (ADR 0011, R16.7)", () => {
  function teamBadge(): HTMLElement | null {
    return host.querySelector('[data-testid="team-badge"]')
  }

  it('is absent for a personal note', async () => {
    await open(note())
    expect(teamBadge()).toBeNull()
  })

  it('shows the team id for a team-shared note', async () => {
    await open(note({ team_id: 501 }))
    expect(teamBadge()!.textContent).toContain('501')
  })

  it('updates when a different note opens', async () => {
    const { opened } = await open(note({ team_id: 501 }))

    opened.value = note({ ref: 'NOTE-7', title: 'Architecture notes', team_id: null })
    flushSync()
    await editorArrived(host)

    expect(teamBadge()).toBeNull()
  })
})
