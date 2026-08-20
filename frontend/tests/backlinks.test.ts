/**
 * `lib/backlinks.ts` — the rail's two decisions, in vitest's default `node` environment.
 *
 * No DOM here on purpose, exactly as `tests/editor-guards.test.ts` keeps `needsRemount` reachable
 * without one: the precedence between five states and the identity guard are the parts most worth
 * testing and the parts a component render could most easily obscure, because a render only ever
 * shows the props that test happened to pass.
 *
 * `tests/backlinks-panel.test.ts` is the behavioural twin and it is not optional — CLAUDE.md's rule
 * that a structural guard does not cover a behavioural claim cuts exactly here. Every assertion
 * below stays green while the component renders `failed` and `empty` with the same sentence, because
 * these prove the two *values* differ and say nothing about the markup that reads them.
 */

import { describe, expect, it } from 'vitest'

import { backlinkLabel, needsFetch, panelState } from '../src/lib/backlinks'
import type { Note } from '../src/lib/types'

function note(ref: string, overrides: Partial<Note> = {}): Note {
  return {
    ref,
    id: Number.parseInt(ref.replace(/\D/g, ''), 10),
    title: `Title ${ref}`,
    body: '',
    path: 'design/adr.md',
    created_at: '2026-08-09T10:00:00+00:00',
    updated_at: '2026-08-09T10:00:00.123456+00:00',
    ...overrides,
  }
}

const IDLE = { ref: 'NOTE-1', loading: false, failure: null, notes: [] as Note[] }

describe('panelState names all five states, and they are five', () => {
  it('is closed when there is no note, whatever else is true', () => {
    // Not the same value as `empty`, and the difference is the whole point: "there is no note open"
    // is not an answer *about* a note, so it must not be able to render as one. The in-flight window
    // between a note route and `getNote` answering is exactly when a panel saying "nothing links to
    // this note" would be lying.
    expect(panelState({ ...IDLE, ref: null })).toEqual({ kind: 'closed' })
    expect(panelState({ ...IDLE, ref: null, notes: [note('NOTE-2')] })).toEqual({ kind: 'closed' })
    expect(panelState({ ...IDLE, ref: null, failure: 'boom' })).toEqual({ kind: 'closed' })
  })

  it('is empty when the request succeeded and returned nothing', () => {
    expect(panelState(IDLE)).toEqual({ kind: 'empty', ref: 'NOTE-1' })
  })

  it('names the note in the zero state, so it cannot be the previous note’s', () => {
    // The fetch is asynchronous and the ref moves first, so a zero state that does not name its
    // subject is indistinguishable from one left over from the note before. Same care as
    // `Sidebar.svelte`'s `No notes match "…"` against its plain `No notes yet.`
    const state = panelState({ ...IDLE, ref: 'NOTE-9' })
    expect(state).toEqual({ kind: 'empty', ref: 'NOTE-9' })
  })

  it('is listed, carrying the rows in the order they arrived', () => {
    // `updated_at DESC, id DESC` is the server's (`notes_linking_to`), and nothing here re-sorts it.
    const notes = [note('NOTE-7'), note('NOTE-2'), note('NOTE-5')]
    expect(panelState({ ...IDLE, notes })).toEqual({ kind: 'listed', ref: 'NOTE-1', notes })
  })

  it('is failed, carrying the API’s own message', () => {
    expect(panelState({ ...IDLE, failure: 'Note not found.' })).toEqual({
      kind: 'failed',
      ref: 'NOTE-1',
      message: 'Note not found.',
    })
  })
})

describe('the precedence, which is the part that can be wrong', () => {
  it('shows loading rather than the error it is retrying past', () => {
    // A Retry that still showed the failure would look like it had already failed again.
    expect(panelState({ ...IDLE, loading: true, failure: 'boom' })).toEqual({ kind: 'loading' })
  })

  it('shows loading rather than rows a new request may replace', () => {
    // The stated trade: a refresh blanks the list for one round trip rather than dimming it in
    // place. Rows held over while a request is in flight are rows a reader takes as current, and
    // this panel exists to say what currently points here.
    expect(panelState({ ...IDLE, loading: true, notes: [note('NOTE-2')] })).toEqual({
      kind: 'loading',
    })
  })

  it('shows the failure rather than the previous answer’s rows', () => {
    // A list under a "could not load" line is a list somebody will read, and it is the *old* answer.
    expect(
      panelState({ ...IDLE, failure: 'The API answered 503', notes: [note('NOTE-2')] }),
    ).toMatchObject({ kind: 'failed' })
  })

  it('puts closed above loading, so a vanished note cannot be “loading” forever', () => {
    expect(panelState({ ...IDLE, ref: null, loading: true })).toEqual({ kind: 'closed' })
  })
})

describe('needsFetch, the identity guard', () => {
  it('refetches when the ref moves', () => {
    expect(needsFetch('NOTE-1', 'NOTE-2')).toBe(true)
  })

  it('does not refetch for the same ref, which is the whole guard', () => {
    // Reading the `note` prop in an effect registers the *whole* prop, so a parent handing down a
    // new object re-runs that effect whichever field is read — `note.ref` and `note.body` are one
    // signal. Without this comparison the rail issues a request per keystroke.
    expect(needsFetch('NOTE-1', 'NOTE-1')).toBe(false)
  })

  it('treats no-note as a value on both sides rather than as a hole', () => {
    expect(needsFetch(null, 'NOTE-1')).toBe(true)
    expect(needsFetch('NOTE-1', null)).toBe(true)
    // `null !== null` is false, so the closed state does not thrash.
    expect(needsFetch(null, null)).toBe(false)
  })

  it('cannot see a body, so no amount of typing can reach the decision', () => {
    // A property of the signature, not of the comparison — the same argument `needsRemount` makes
    // about its own missing parameter. If a body ever becomes an argument here, that is the card
    // that made the rail refetch per keystroke.
    expect(needsFetch.length).toBe(2)
  })
})

describe('backlinkLabel', () => {
  it('shows the title', () => {
    expect(backlinkLabel(note('NOTE-3'))).toBe('Title NOTE-3')
  })

  it('falls back to the ref for an empty title, which is legal server-side', () => {
    // `title` is `String(255)` with no minimum, so a row keyed on the title alone is a blank line
    // that reads as a rendering bug. `Sidebar.svelte`'s `label()` makes the same call.
    expect(backlinkLabel(note('NOTE-3', { title: '' }))).toBe('NOTE-3')
  })
})
