// @vitest-environment jsdom
/**
 * KAN-556: ADR 0009's `409` as an affordance, through the pane that owns the write path.
 *
 * Mounted rather than unit-tested against `ConflictBanner` alone, and that is the point of the file.
 * The banner is markup and two callbacks; everything that can be *wrong* — which body is sent, which
 * stamp guards it, whether the document is replaced by a transaction or by a remount, whether the
 * banner leaked into CM6's subtree — lives in the seam between the two components. CLAUDE.md's rule:
 * a structural guard does not cover a behavioural claim, so the claims are asserted end to end and on
 * both sides of the boundary.
 *
 * `tests/conflict.test.ts` holds the pure half (`keepMinePatch`, `splitOnChange`, `compareMetadata`)
 * in `node`, where the resolution rule is one expression and jsdom cannot obscure it.
 */

import { undo } from '@codemirror/commands'
import { EditorView } from '@codemirror/view'
import { flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import EditorPane from '../src/components/EditorPane.svelte'
import * as auth from '../src/lib/auth'
import type { Note } from '../src/lib/types'
import { editorArrived } from './editor-arrival'
import { box } from './reactive.svelte'
import { FAKE_TOKEN } from './token'

/**
 * The three stamps, with six fractional digits each.
 *
 * ADR 0009 compares to the microsecond and `new Date(s).toISOString()` rounds to milliseconds, so
 * `.226957` is what makes "the precondition is an opaque string" refutable rather than aspirational.
 * These are the real values the PM observed on a live stack (`make up`, real PAT) for NOTE-11.
 */
const READ_AT = '2026-08-09T10:51:23.226957Z'
const THEIRS_AT = '2026-08-09T10:53:04.881903Z'
/** A third writer, arriving while the banner is open. */
const THIRD_AT = '2026-08-09T10:55:41.507218Z'
const WRITTEN_AT = '2026-08-09T10:56:12.664409Z'

/** Two bodies that share a head and a tail, so "the marked region" has something to be about. */
const MINE = '# Conflicts\n\n1. read updated_at\n2. my step\n\nend\n'
const THEIRS = '# Conflicts\n\n1. read updated_at\n2. their step\n\nend\n'

function note(overrides: Partial<Note> = {}): Note {
  return {
    ref: 'NOTE-11',
    id: 11,
    title: 'Conflicts',
    body: '# Conflicts\n\n1. read updated_at\n\nend\n',
    path: 'design/conflicts.md',
    created_at: '2026-08-09T09:00:00+00:00',
    updated_at: READ_AT,
    ...overrides,
  }
}

/** ADR 0009's body, as `concurrency.py` builds it: one error shape, two whole notes on it. */
function refusal(mine: string, theirs: string, storedAt: string, preconditionAt = READ_AT): unknown {
  return {
    error: {
      code: 'note_conflict',
      message:
        `NOTE-11 has changed since you read it: stored ${storedAt}, ` +
        `precondition ${preconditionAt}. Nothing was written.`,
      // `attempted` carries the caller's body and the **precondition** as its `updated_at`, and its
      // other fields come from the stored note. Both facts are `attempted_version`'s docstring.
      attempted: note({ body: mine, updated_at: preconditionAt }),
      stored: note({ body: theirs, updated_at: storedAt }),
    },
  }
}

interface Call {
  url: string
  method: string
  body: Record<string, unknown>
}

interface Reply {
  status: number
  payload: unknown
}

let host: HTMLDivElement
const mounted: unknown[] = []

/** Reply to each request in turn; the last reply repeats. Records what was asked. */
function stubFetch(...replies: Reply[]): Call[] {
  const calls: Call[] = []
  vi.stubGlobal('fetch', (url: string, init: RequestInit) => {
    const reply = replies[Math.min(calls.length, replies.length - 1)]
    calls.push({
      url,
      method: init.method ?? 'GET',
      body: JSON.parse(String(init.body)) as Record<string, unknown>,
    })
    return Promise.resolve(new Response(JSON.stringify(reply.payload), { status: reply.status }))
  })
  return calls
}

/**
 * `async` since KAN-767: CodeMirror is behind a dynamic `import()`, so the container is empty until the
 * chunk lands and every `editor(container)` below would find nothing. See `editor-arrival.ts`.
 */
async function open(initial: Note | null = note()): Promise<{
  opened: ReturnType<typeof box<Note | null>>
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

function editor(container: HTMLElement): EditorView {
  return EditorView.findFromDOM(container.querySelector('.cm-editor')!)!
}

/** Replace the whole document as a user would, so `dirty` is set and Save is enabled. */
function typeAll(view: EditorView, text: string): void {
  view.dispatch({
    changes: { from: 0, to: view.state.doc.length, insert: text },
    userEvent: 'input.type',
  })
  flushSync()
}

function pick(testid: string): HTMLElement | null {
  return host.querySelector(`[data-testid="${testid}"]`)
}

/**
 * An element's prose with runs of whitespace collapsed.
 *
 * For sentences only. The two bodies are asserted through `textContent` **unnormalised**, because
 * whitespace is exactly what a side-by-side of markdown must not touch.
 */
function prose(testid: string): string {
  return (pick(testid)?.textContent ?? '').replace(/\s+/g, ' ').trim()
}

function click(testid: string): void {
  ;(pick(testid) as HTMLButtonElement).click()
}

const banner = () => vi.waitFor(() => expect(pick('conflict')).not.toBeNull())

/** Save the current document and wait for the `409` the stub is primed with. */
async function saveIntoConflict(container: HTMLElement, body = MINE): Promise<void> {
  typeAll(editor(container), body)
  host.querySelector('button')!.click()
  await banner()
}

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

describe('the banner shows both versions', () => {
  it('renders both bodies whole, byte for byte', async () => {
    // Why both arrive whole at all: `concurrency.py` — a client cannot reconstruct one from a patch it
    // no longer holds. And byte for byte because this screen is where a person decides which bytes to
    // keep; a rendering that dropped the trailing newline would be describing a note that does not
    // exist.
    stubFetch({ status: 409, payload: refusal(MINE, THEIRS, THEIRS_AT) })
    const { container } = await open()
    await saveIntoConflict(container)

    expect(pick('conflict-mine-body')!.textContent).toBe(MINE)
    expect(pick('conflict-theirs-body')!.textContent).toBe(THEIRS)
  })

  it('keeps a code fence, a run of spaces and an emoji intact', async () => {
    // `white-space: pre-wrap` and *not* `pre-line`, three slices and not a re-join: this is the
    // assertion behind both choices. A collapsed run of spaces inside a fence is a rendering of a
    // markdown note that the note does not contain.
    const fussy = '```\n  two  spaces\n```\ntail 🌱 é'
    stubFetch({ status: 409, payload: refusal(fussy, `${fussy}!`, THEIRS_AT) })
    const { container } = await open()
    await saveIntoConflict(container, fussy)

    expect(pick('conflict-mine-body')!.textContent).toBe(fussy)
    expect(pick('conflict-theirs-body')!.textContent).toBe(`${fussy}!`)
  })

  it('marks the region that differs and leaves the shared lines unmarked', async () => {
    stubFetch({ status: 409, payload: refusal(MINE, THEIRS, THEIRS_AT) })
    const { container } = await open()
    await saveIntoConflict(container)

    expect(pick('conflict-mine-body')!.querySelector('mark')!.textContent).toBe('2. my step\n')
    expect(pick('conflict-theirs-body')!.querySelector('mark')!.textContent).toBe('2. their step\n')
  })

  it('names both stamps outside the comparison, so hiding it does not hide them', async () => {
    stubFetch({ status: 409, payload: refusal(MINE, THEIRS, THEIRS_AT) })
    const { container } = await open()
    await saveIntoConflict(container)

    click('conflict-toggle')
    flushSync()

    expect(pick('conflict-side-by-side')).toBeNull()
    expect(pick('conflict-attempted')!.textContent).toBe(READ_AT)
    expect(pick('conflict-stored')!.textContent).toBe(THEIRS_AT)
    // And the two ways out are still there with the comparison collapsed.
    expect(pick('conflict-keep-mine')).not.toBeNull()
    expect(pick('conflict-keep-theirs')).not.toBeNull()
  })

  it('lists the fields both versions agree on once, rather than as an empty diff', async () => {
    // `concurrency.py`'s second "looks like a bug and is not": a body-only write's `409` carries the
    // stored `title` and `path` on **both** sides, because kaya never saw the caller's base version.
    stubFetch({ status: 409, payload: refusal(MINE, THEIRS, THEIRS_AT) })
    const { container } = await open()
    await saveIntoConflict(container)

    const agreed = prose('conflict-agreed')
    expect(agreed).toContain('title Conflicts')
    expect(agreed).toContain('path design/conflicts.md')
    expect(agreed).toContain('correct rather than a bug')
    expect(pick('conflict-differing')).toBeNull()
  })

  it('says so when the two bodies are identical instead of showing two silent columns', async () => {
    stubFetch({ status: 409, payload: refusal(MINE, MINE, THEIRS_AT) })
    const { container } = await open()
    await saveIntoConflict(container)

    expect(prose('conflict-identical')).toContain('The two bodies are identical')
    expect(pick('conflict-mine-body')!.textContent).toBe(MINE)
  })
})

describe('keep mine', () => {
  it('re-PATCHes the attempted body guarded on the stored stamp, verbatim', async () => {
    // The card, and the one assertion `concurrency.py` wrote for this file: `body` from `attempted`,
    // `if_updated_at` from **`stored`**. `toBe` on the stamp, because equality after parsing is what
    // loses `.881903` and refuses every correct write.
    const calls = stubFetch(
      { status: 409, payload: refusal(MINE, THEIRS, THEIRS_AT) },
      { status: 200, payload: note({ body: MINE, updated_at: WRITTEN_AT }) },
    )
    const { container } = await open()
    await saveIntoConflict(container)

    click('conflict-keep-mine')
    await vi.waitFor(() => expect(calls).toHaveLength(2))

    expect(calls[1].url).toBe('/api/v1/notes/NOTE-11')
    expect(calls[1].method).toBe('PATCH')
    expect(calls[1].body).toEqual({ body: MINE, if_updated_at: THEIRS_AT })
    expect(calls[1].body.if_updated_at).toBe(THEIRS_AT)
    expect(calls[1].body.if_updated_at).not.toBe(new Date(THEIRS_AT).toISOString())
  })

  it('is one request, and never a read to refresh the precondition first', async () => {
    // The rule `kaya note edit` follows: the client never fetches the precondition. Here it *has* the
    // right one — the `409` handed it over — so a read would be both wasteful and a way to widen the
    // race the guard exists to close.
    const calls = stubFetch(
      { status: 409, payload: refusal(MINE, THEIRS, THEIRS_AT) },
      { status: 200, payload: note({ body: MINE, updated_at: WRITTEN_AT }) },
    )
    const { container } = await open()
    await saveIntoConflict(container)

    click('conflict-keep-mine')
    await vi.waitFor(() => expect(pick('conflict')).toBeNull())

    expect(calls).toHaveLength(2)
    expect(calls.every((call) => call.method === 'PATCH')).toBe(true)
    expect(pick('save-state')!.textContent).toContain(WRITTEN_AT)
  })

  it('leaves the document alone and does not rebuild the editor', async () => {
    const destroy = vi.spyOn(EditorView.prototype, 'destroy')
    stubFetch(
      { status: 409, payload: refusal(MINE, THEIRS, THEIRS_AT) },
      { status: 200, payload: note({ body: MINE, updated_at: WRITTEN_AT }) },
    )
    const { container } = await open()
    await saveIntoConflict(container)
    const view = editor(container)
    const node = container.firstElementChild

    click('conflict-keep-mine')
    await vi.waitFor(() => expect(pick('conflict')).toBeNull())

    expect(editor(container)).toBe(view)
    expect(container.firstElementChild).toBe(node)
    expect(destroy).not.toHaveBeenCalled()
    expect(view.state.doc.toString()).toBe(MINE)
  })

  it('still reads as unsaved when the document moved past what the banner offered', async () => {
    // `keepMinePatch` writes `attempted.body`, which is what the banner *shows* under "mine" — a
    // button that wrote something not on the screen would be a different button. So typing on while
    // the banner is open leaves work unsaved after it, and the pane has to say so.
    stubFetch(
      { status: 409, payload: refusal(MINE, THEIRS, THEIRS_AT) },
      { status: 200, payload: note({ body: MINE, updated_at: WRITTEN_AT }) },
    )
    const { container } = await open()
    await saveIntoConflict(container)
    typeAll(editor(container), `${MINE}typed while deciding\n`)

    click('conflict-keep-mine')
    await vi.waitFor(() => expect(pick('conflict')).toBeNull())

    expect(pick('save-state')!.textContent).toContain('unsaved')
  })

  it('disables both buttons while the resolution is in flight', async () => {
    stubFetch(
      { status: 409, payload: refusal(MINE, THEIRS, THEIRS_AT) },
      { status: 200, payload: note({ body: MINE, updated_at: WRITTEN_AT }) },
    )
    const { container } = await open()
    await saveIntoConflict(container)

    click('conflict-keep-mine')
    flushSync()

    // The banner stays up through its own round trip — the buttons must not vanish under the cursor —
    // and neither choice is clickable while the other one is deciding.
    expect(pick('conflict')).not.toBeNull()
    expect((pick('conflict-keep-mine') as HTMLButtonElement).disabled).toBe(true)
    expect((pick('conflict-keep-theirs') as HTMLButtonElement).disabled).toBe(true)
  })
})

describe('keep theirs', () => {
  it('makes no request at all', async () => {
    // Nothing to write: the stored version already *is* what the server holds. A `PATCH` here would
    // be a write whose only effect is a new `updated_at`, and it could fail.
    const calls = stubFetch({ status: 409, payload: refusal(MINE, THEIRS, THEIRS_AT) })
    const { container } = await open()
    await saveIntoConflict(container)
    expect(calls).toHaveLength(1)

    click('conflict-keep-theirs')
    flushSync()

    expect(calls).toHaveLength(1)
    expect(pick('conflict')).toBeNull()
  })

  it('puts the stored body in the document as a transaction, never as a remount', async () => {
    // PLAN §S9: the document is swapped by `dispatch`, so the view — and the undo history the next
    // test needs — survives. Node identity is the instrument, as in `editor-pane.test.ts`.
    const destroy = vi.spyOn(EditorView.prototype, 'destroy')
    stubFetch({ status: 409, payload: refusal(MINE, THEIRS, THEIRS_AT) })
    const { container } = await open()
    await saveIntoConflict(container)
    const view = editor(container)
    const node = container.firstElementChild

    click('conflict-keep-theirs')
    flushSync()

    expect(view.state.doc.toString()).toBe(THEIRS)
    expect(editor(container)).toBe(view)
    expect(container.firstElementChild).toBe(node)
    expect(container.querySelectorAll('.cm-editor')).toHaveLength(1)
    expect(destroy).not.toHaveBeenCalled()
  })

  it('leaves the discarded text one undo away, and marks it unsaved again', async () => {
    // The reason the banner may promise this: the discard is a transaction in a view with `history()`,
    // so ⌘/Ctrl-Z is a real undo. It matters because ADR 0009 §Consequences is explicit that there is
    // **no revision history** — this is the only copy of the text that exists after the click.
    stubFetch({ status: 409, payload: refusal(MINE, THEIRS, THEIRS_AT) })
    const { container } = await open()
    await saveIntoConflict(container)
    const view = editor(container)

    click('conflict-keep-theirs')
    flushSync()
    expect(pick('save-state')!.textContent).toContain('kept theirs')

    expect(undo(view)).toBe(true)
    flushSync()

    expect(view.state.doc.toString()).toBe(MINE)
    expect(pick('save-state')!.textContent).toContain('unsaved')
  })

  it('never claims a save, because nothing was written', async () => {
    stubFetch({ status: 409, payload: refusal(MINE, THEIRS, THEIRS_AT) })
    const { container } = await open()
    await saveIntoConflict(container)

    click('conflict-keep-theirs')
    flushSync()

    const state = pick('save-state')!.textContent!
    expect(state).toContain('kept theirs')
    expect(state).not.toContain('saved ·')
    expect(state).not.toContain('now at')
  })

  it('rebases the next save on the stored stamp, so it is not refused forever', async () => {
    // The half that would be silently missing: without `basedOn` moving, the next Save would re-send
    // the precondition the server just rejected, and the user would be stuck in a banner loop with a
    // document that came *from* the server.
    const calls = stubFetch(
      { status: 409, payload: refusal(MINE, THEIRS, THEIRS_AT) },
      { status: 200, payload: note({ body: `${THEIRS}mine again\n`, updated_at: WRITTEN_AT }) },
    )
    const { container } = await open()
    await saveIntoConflict(container)

    click('conflict-keep-theirs')
    flushSync()
    typeAll(editor(container), `${THEIRS}mine again\n`)
    host.querySelector('button')!.click()
    await vi.waitFor(() => expect(calls).toHaveLength(2))

    expect(calls[1].body.if_updated_at).toBe(THEIRS_AT)
    expect(calls[1].body.body).toBe(`${THEIRS}mine again\n`)
  })
})

describe('a conflict on the retry, because the note can move again while you read', () => {
  it('replaces the banner with the newer pair and says it changed again', async () => {
    // The write "keep mine" makes is itself guarded, so a third writer landing between the refusal and
    // the click is refused in exactly the same way. That is the feature working twice, not a bug — so
    // the banner refreshes in place rather than clearing, and the comparison is now against the new
    // stored body.
    const calls = stubFetch(
      { status: 409, payload: refusal(MINE, THEIRS, THEIRS_AT) },
      { status: 409, payload: refusal(MINE, `${THEIRS}third writer\n`, THIRD_AT, THEIRS_AT) },
    )
    const { container } = await open()
    await saveIntoConflict(container)

    click('conflict-keep-mine')
    await vi.waitFor(() => expect(pick('conflict-stored')!.textContent).toBe(THIRD_AT))

    expect(calls).toHaveLength(2)
    expect(prose('conflict-moved-again')).toContain('changed again while you were deciding')
    expect(pick('conflict-theirs-body')!.textContent).toBe(`${THEIRS}third writer\n`)
    // Still the caller's text on the left, and still in the editor. Two refusals have written nothing.
    expect(pick('conflict-mine-body')!.textContent).toBe(MINE)
    expect(editor(container).state.doc.toString()).toBe(MINE)
  })

  it('offers a keep mine guarded on the newest stored stamp', async () => {
    // The resolution has to *converge*: each attempt is guarded on the version that refused the last
    // one. A banner that kept offering the first stamp would never write, however many times it was
    // clicked.
    const calls = stubFetch(
      { status: 409, payload: refusal(MINE, THEIRS, THEIRS_AT) },
      { status: 409, payload: refusal(MINE, `${THEIRS}third writer\n`, THIRD_AT, THEIRS_AT) },
      { status: 200, payload: note({ body: MINE, updated_at: WRITTEN_AT }) },
    )
    const { container } = await open()
    await saveIntoConflict(container)

    click('conflict-keep-mine')
    await vi.waitFor(() => expect(pick('conflict-stored')!.textContent).toBe(THIRD_AT))
    click('conflict-keep-mine')
    await vi.waitFor(() => expect(pick('conflict')).toBeNull())

    expect(calls[1].body.if_updated_at).toBe(THEIRS_AT)
    expect(calls[2].body.if_updated_at).toBe(THIRD_AT)
    expect(calls[2].body.body).toBe(MINE)
  })

  it('does not claim it changed again when the same conflict is refused a second time', async () => {
    // A plain Save after a refusal re-sends the same stale precondition and is refused identically.
    // Correct, and not news: claiming "it changed again" on an unchanged stored stamp would teach the
    // user to distrust the one sentence that means someone is writing right now.
    stubFetch({ status: 409, payload: refusal(MINE, THEIRS, THEIRS_AT) })
    const { container } = await open()
    await saveIntoConflict(container)
    expect(pick('conflict-moved-again')).toBeNull()

    typeAll(editor(container), `${MINE}more\n`)
    host.querySelector('button')!.click()
    await vi.waitFor(() => expect(pick('save-state')!.textContent).toContain('unsaved'))

    expect(pick('conflict-stored')!.textContent).toBe(THEIRS_AT)
    expect(pick('conflict-moved-again')).toBeNull()
  })
})

describe("PLAN §S9, with the banner up", () => {
  /** Everything in the container the `$effect` did not put there — `shell.test.ts`'s instrument. */
  function foreignNodes(container: Element): string[] {
    const own = new Set<Node>(container.querySelectorAll(':scope > .cm-editor'))
    return Array.from(container.childNodes)
      .filter((node) => !own.has(node))
      .map((node) => `${node.nodeName.toLowerCase()} ${JSON.stringify(node.textContent)}`)
  }

  it('renders the banner outside the editor container, and puts nothing inside it', async () => {
    // The rendered half of the claim. `tests/editor-container.test.ts` covers the source half — the
    // container has zero template children, so a `<ConflictBanner />` moved inside it would be named
    // there — and this one covers the state that source check cannot reach: a conflict actually up.
    stubFetch({ status: 409, payload: refusal(MINE, THEIRS, THEIRS_AT) })
    const { container } = await open()
    await saveIntoConflict(container)

    const rendered = pick('conflict')!
    expect(container.contains(rendered)).toBe(false)
    expect(rendered.contains(container)).toBe(false)
    expect(foreignNodes(container)).toEqual([])
    expect(container.querySelectorAll(':scope > .cm-editor')).toHaveLength(1)
  })

  it('does not remount the editor when the banner appears or is resolved', async () => {
    const destroy = vi.spyOn(EditorView.prototype, 'destroy')
    stubFetch({ status: 409, payload: refusal(MINE, THEIRS, THEIRS_AT) })
    const { container } = await open()
    const node = container.firstElementChild

    await saveIntoConflict(container)
    expect(container.firstElementChild).toBe(node)

    click('conflict-keep-theirs')
    flushSync()

    expect(container.firstElementChild).toBe(node)
    expect(destroy).not.toHaveBeenCalled()
  })

  it('never renders the credential, on any of the banner surfaces', async () => {
    // The four-character sweep `kaya config show` is held to. The banner is the widest new surface in
    // this card — two whole notes, an API message, and prose about both.
    stubFetch({ status: 409, payload: refusal(MINE, THEIRS, THEIRS_AT) })
    const { container } = await open()
    await saveIntoConflict(container)

    for (let start = 0; start + 4 <= FAKE_TOKEN.length; start += 1) {
      expect(document.body.innerHTML).not.toContain(FAKE_TOKEN.slice(start, start + 4))
    }
  })
})
