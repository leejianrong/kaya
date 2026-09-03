/**
 * The two guards ADR 0001 §2 requires, as pure predicates, in the **`node`** environment.
 *
 * No `// @vitest-environment jsdom` here on purpose. `tests/editor-view.test.ts` drives the same
 * functions against a real `EditorView` and needs a DOM; these tests must not, because the guards are
 * the part of this card most worth being certain about and jsdom's missing measurement APIs are the
 * least interesting reason for a test about a string comparison to fail. dev-playbook §2: pull the
 * decision out of the widget and test the decision.
 *
 * `src/lib/editor.ts` imports `EditorView` as a **type only**, which `verbatimModuleSyntax` erases —
 * so this file loading it in `node` also proves that erasure holds. Add a value import there and this
 * file goes red on `@codemirror/view`'s module-level browser sniffing, which is the correct alarm.
 */

import { describe, expect, it, vi } from 'vitest'

import { conflictVersions, needsDispatch, needsRemount, syncDocument } from '../src/lib/editor'
import type { Note } from '../src/lib/types'

/** The smallest thing `syncDocument` can be handed: a document and a spy for the transaction. */
function stubView(text: string) {
  const dispatch = vi.fn()
  return {
    view: {
      state: { doc: { length: text.length, toString: () => text } },
      dispatch,
    } as never,
    dispatch,
  }
}

function note(overrides: Partial<Note> = {}): Note {
  return {
    ref: 'NOTE-11',
    id: 11,
    title: 'Conflicts',
    body: 'mine\n',
    path: 'design/conflicts.md',
    created_at: '2026-08-09T10:00:00+00:00',
    updated_at: '2026-08-09T10:00:00.123456+00:00',
    team_id: null,
    ...overrides,
  }
}

describe('the identity guard (needsRemount)', () => {
  it('does not remount for the same ref, whatever else changed', () => {
    // The whole card. A parent handing down a new `Note` object per keystroke re-runs the effect
    // whichever field it reads, so "depend on identity" has to mean *compare the ref*, not
    // *read a narrower field* — reading `note.ref` instead of `note.body` registers the same signal.
    expect(needsRemount(true, 'NOTE-6', 'NOTE-6')).toBe(false)
  })

  it('remounts when the ref changes, because that is a different note (ADR 0008)', () => {
    expect(needsRemount(true, 'NOTE-6', 'NOTE-7')).toBe(true)
  })

  it('remounts when there is no view yet, whatever the refs say', () => {
    // `hasView` is a separate parameter for this case alone: "no view" and "a view showing no note"
    // are different states, and spelling them both `null` would make the first one unmountable.
    expect(needsRemount(false, null, null)).toBe(true)
    expect(needsRemount(false, 'NOTE-6', 'NOTE-6')).toBe(true)
  })

  it('treats the no-note state as a note, so it does not thrash', () => {
    expect(needsRemount(true, null, null)).toBe(false)
    expect(needsRemount(true, null, 'NOTE-6')).toBe(true)
    expect(needsRemount(true, 'NOTE-6', null)).toBe(true)
  })

  it('has no parameter for the body, so no content change can reach the decision', () => {
    // Structural, in the shape `kaya-client/tests/test_aggregates.py` uses on `attach_summary`: the
    // strongest form of "content cannot cause a remount" is that content cannot be passed in.
    expect(needsRemount).toHaveLength(3)
  })
})

describe('the echo guard (needsDispatch / syncDocument)', () => {
  it('dispatches nothing when the incoming value already is the document', () => {
    // The cycle this breaks: `updateListener → set rune → effect → dispatch → updateListener`. At the
    // moment the effect re-runs, the rune holds exactly what the editor holds, and that equality is
    // the one place the cycle can be cut without guessing.
    const { view, dispatch } = stubView('# Heading\n')

    expect(needsDispatch('# Heading\n', '# Heading\n')).toBe(false)
    expect(syncDocument(view, '# Heading\n')).toBe(false)
    expect(dispatch).not.toHaveBeenCalled()
  })

  it('dispatches one transaction spanning the whole document when it differs', () => {
    const { view, dispatch } = stubView('old')

    expect(syncDocument(view, 'new')).toBe(true)
    expect(dispatch).toHaveBeenCalledTimes(1)
    expect(dispatch).toHaveBeenCalledWith({ changes: { from: 0, to: 3, insert: 'new' } })
  })

  it('compares exactly, with no normalisation', () => {
    // A normalising comparison would make the two sides disagree about equality and the cycle would
    // resume on whatever the normaliser changed — trailing newline, CRLF, NFC vs NFD.
    expect(needsDispatch('a\n', 'a')).toBe(true)
    expect(needsDispatch('a\r\n', 'a\n')).toBe(true)
    expect(needsDispatch('é', 'é')).toBe(true)
    expect(needsDispatch('', '')).toBe(false)
  })

  it('dispatches when the editor is empty and the incoming value is not, and vice versa', () => {
    const empty = stubView('')
    expect(syncDocument(empty.view, 'x')).toBe(true)
    expect(empty.dispatch).toHaveBeenCalledWith({ changes: { from: 0, to: 0, insert: 'x' } })

    const full = stubView('x')
    expect(syncDocument(full.view, '')).toBe(true)
    expect(full.dispatch).toHaveBeenCalledWith({ changes: { from: 0, to: 1, insert: '' } })
  })
})

describe("ADR 0009's two versions (conflictVersions)", () => {
  it('reads both whole notes out of the 409 extras', () => {
    const attempted = note({ body: 'mine\n', updated_at: '2026-08-09T10:00:00.123456+00:00' })
    const stored = note({ body: 'theirs\n', updated_at: '2026-08-09T10:05:00.654321+00:00' })

    const found = conflictVersions({ attempted, stored })

    // Whole, not summarised. KAN-556's side-by-side needs both prose bodies — a client cannot
    // reconstruct one from a patch it no longer has.
    expect(found).not.toBeNull()
    expect(found!.attempted.body).toBe('mine\n')
    expect(found!.stored.body).toBe('theirs\n')
    // To the microsecond, both of them. Six digits reach the UI or the precondition was never opaque.
    expect(found!.attempted.updated_at).toBe('2026-08-09T10:00:00.123456+00:00')
    expect(found!.stored.updated_at).toBe('2026-08-09T10:05:00.654321+00:00')
  })

  it('returns null rather than half a conflict when a version is missing or malformed', () => {
    expect(conflictVersions({})).toBeNull()
    expect(conflictVersions({ attempted: note() })).toBeNull()
    expect(conflictVersions({ attempted: note(), stored: null })).toBeNull()
    expect(conflictVersions({ attempted: note(), stored: { ref: 'NOTE-11' } })).toBeNull()
  })

  it('tolerates an extra key the API grows without this file knowing', () => {
    // The backend's error vocabulary grows without the client's knowledge — `kaya-cli` keys its exit
    // table on the status for the same reason. A stricter shape check here would turn one added field
    // into a swallowed conflict.
    const found = conflictVersions({
      attempted: { ...note(), lock_holder: 'someone' },
      stored: note(),
    })
    expect(found).not.toBeNull()
  })
})
