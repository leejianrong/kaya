/**
 * `lib/history.ts` — the History tab's decisions, in vitest's default `node` environment.
 *
 * `tests/backlinks.test.ts`'s twin, for its own twin module. `tests/history-panel.test.ts` is the
 * behavioural half — CLAUDE.md's rule that a structural guard does not cover a behavioural claim
 * cuts here exactly as it does there: these assertions stay green while the component renders
 * `failed` and `empty` with the same sentence, because they prove the two *values* differ and say
 * nothing about the markup that reads them.
 */

import { describe, expect, it } from 'vitest'

import { isSelected, needsFetch, panelState } from '../src/lib/history'
import type { NoteVersion } from '../src/lib/types'

function version(id: number, overrides: Partial<NoteVersion> = {}): NoteVersion {
  return {
    id,
    body: `body ${id}`,
    created_at: '2026-08-09T10:00:00+00:00',
    ...overrides,
  }
}

const IDLE = { ref: 'NOTE-1', loading: false, failure: null, versions: [] as NoteVersion[] }

describe('panelState names all five states, and they are five', () => {
  it('is closed when there is no note, whatever else is true', () => {
    expect(panelState({ ...IDLE, ref: null })).toEqual({ kind: 'closed' })
    expect(panelState({ ...IDLE, ref: null, versions: [version(1)] })).toEqual({ kind: 'closed' })
    expect(panelState({ ...IDLE, ref: null, failure: 'boom' })).toEqual({ kind: 'closed' })
  })

  it('is empty when the request succeeded and returned nothing', () => {
    // Not a state a real note can be in — `create_note` cuts a first version too — but the type
    // still names it, the same way `BacklinksPanel`'s zero state is named rather than assumed
    // unreachable.
    expect(panelState(IDLE)).toEqual({ kind: 'empty', ref: 'NOTE-1' })
  })

  it('names the note in the zero state, so it cannot be the previous note’s', () => {
    const state = panelState({ ...IDLE, ref: 'NOTE-9' })
    expect(state).toEqual({ kind: 'empty', ref: 'NOTE-9' })
  })

  it('is listed, carrying the rows in the order they arrived', () => {
    // `created_at DESC, id DESC` is the server's (`app/note_versions.py`), and nothing here re-sorts
    // it.
    const versions = [version(7), version(2), version(5)]
    expect(panelState({ ...IDLE, versions })).toEqual({ kind: 'listed', ref: 'NOTE-1', versions })
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
    expect(panelState({ ...IDLE, loading: true, failure: 'boom' })).toEqual({ kind: 'loading' })
  })

  it('shows loading rather than rows a new request may replace', () => {
    expect(panelState({ ...IDLE, loading: true, versions: [version(1)] })).toEqual({
      kind: 'loading',
    })
  })

  it('shows the failure rather than the previous answer’s rows', () => {
    expect(
      panelState({ ...IDLE, failure: 'The API answered 503', versions: [version(1)] }),
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
    expect(needsFetch('NOTE-1', 'NOTE-1')).toBe(false)
  })

  it('treats no-note as a value on both sides rather than as a hole', () => {
    expect(needsFetch(null, 'NOTE-1')).toBe(true)
    expect(needsFetch('NOTE-1', null)).toBe(true)
    expect(needsFetch(null, null)).toBe(false)
  })
})

describe('isSelected', () => {
  it('matches the chosen version by id', () => {
    expect(isSelected(2, version(2))).toBe(true)
    expect(isSelected(2, version(3))).toBe(false)
  })

  it('is false for every row when nothing is selected', () => {
    expect(isSelected(null, version(1))).toBe(false)
  })
})
