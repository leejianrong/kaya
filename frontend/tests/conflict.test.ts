/**
 * `lib/conflict.ts`: the resolution rule and the comparison, in `node`, with no DOM anywhere near.
 *
 * The highest-value assertion in this file is the microsecond one. `keepMinePatch` is the **second**
 * place in the SPA a precondition is built — the first is `EditorPane`'s save — and the two are
 * covered separately on purpose: a guard over one of them says nothing about the other, and this one
 * is the path a user reaches only after a conflict, which is exactly when a lost microsecond would be
 * hardest to explain.
 */

import { describe, expect, it } from 'vitest'

import { compareMetadata, type ConflictVersions, keepMinePatch, splitOnChange } from '../src/lib/conflict'
import type { Note } from '../src/lib/types'

/** Six fractional digits, because five of them are what `new Date(s).toISOString()` would keep. */
const MINE_AT = '2026-08-09T10:51:23.226957Z'
const THEIRS_AT = '2026-08-09T10:53:04.881903Z'

function note(overrides: Partial<Note> = {}): Note {
  return {
    ref: 'NOTE-11',
    id: 11,
    title: 'Conflicts',
    body: '',
    path: 'design/conflicts.md',
    created_at: '2026-08-09T09:00:00+00:00',
    updated_at: MINE_AT,
    ...overrides,
  }
}

function conflict(mine: Partial<Note>, theirs: Partial<Note>): ConflictVersions {
  return { attempted: note(mine), stored: note({ updated_at: THEIRS_AT, ...theirs }) }
}

describe('keepMinePatch — the whole resolution mechanism', () => {
  it('takes the body from attempted and the precondition from stored', () => {
    // The crossing, which is the card. `backend/app/api/concurrency.py` specifies exactly this, and
    // it is why both objects on the `409` carry their own `updated_at`.
    const patch = keepMinePatch(conflict({ body: 'mine\n' }, { body: 'theirs\n' }))

    expect(patch).toEqual({ body: 'mine\n', if_updated_at: THEIRS_AT })
  })

  it('carries the stored stamp verbatim, to the microsecond', () => {
    // Not "equal after parsing" — identical. `new Date(THEIRS_AT).toISOString()` is
    // `2026-08-09T10:53:04.881Z`, which is a precondition the backend refuses for *every* correct
    // write, and the failure looks like a conflict rather than like a bug in this line.
    const patch = keepMinePatch(conflict({}, {}))

    expect(patch.if_updated_at).toBe(THEIRS_AT)
    expect(patch.if_updated_at).not.toBe(new Date(THEIRS_AT).toISOString())
  })

  it('never sends the attempted stamp, which is the version that was already refused', () => {
    const patch = keepMinePatch(conflict({}, {}))

    // Sending this back would be refused identically, forever: it is the stale token, by definition.
    expect(patch.if_updated_at).not.toBe(MINE_AT)
  })

  it('sends the body only, so resolving a conflict cannot overwrite a rename', () => {
    // A `PATCH` sends what it changes (ADR 0009's table: a metadata-only write is plain LWW). If this
    // grew a `title`, "keep mine" would quietly reverse someone else's rename as a side effect of
    // keeping a body.
    const patch = keepMinePatch(conflict({ title: 'Mine' }, { title: 'Theirs' }))

    expect(Object.keys(patch).sort()).toEqual(['body', 'if_updated_at'])
  })
})

describe('splitOnChange — faithful first, clever never', () => {
  const CASES: [string, string][] = [
    ['# R\n\n1. drain\n2. mine\n\nend\n', '# R\n\n1. drain\n2. theirs\n\nend\n'],
    ['same\n', 'same\n'],
    ['', 'anything\n'],
    ['no trailing newline', 'no trailing newline!'],
    ['a\nb\nc\n', 'a\nc\n'],
    ['```\n  two  spaces\n```\ntail 🌱 é', '```\n  two  spaces\n```\ntail 🌿 é'],
    ['x\n', ''],
  ]

  it.each(CASES)('reassembles both bodies byte for byte (%j / %j)', (mine, theirs) => {
    // The property the side-by-side rests on: the three segments are *slices*, so a `<pre>` of them
    // is the note and not a reconstruction of it. A `split('\n')` implementation loses the trailing
    // newline and fails here, which is the point.
    const split = splitOnChange(mine, theirs)

    expect(split.mine.before + split.mine.changed + split.mine.after).toBe(mine)
    expect(split.theirs.before + split.theirs.changed + split.theirs.after).toBe(theirs)
  })

  it.each(CASES)('leaves nothing different outside the marked region (%j / %j)', (mine, theirs) => {
    // The bound, asserted as the property rather than as a symptom: the unmarked parts of the two
    // bodies are *the same strings*. So no difference can hide in them, whatever the middle looks
    // like.
    const split = splitOnChange(mine, theirs)

    expect(split.mine.before).toBe(split.theirs.before)
    expect(split.mine.after).toBe(split.theirs.after)
  })

  it('marks only the line that actually changed', () => {
    const split = splitOnChange('# R\n\n1. drain\n2. mine\n\nend\n', '# R\n\n1. drain\n2. theirs\n\nend\n')

    expect(split.mine.before).toBe('# R\n\n1. drain\n')
    expect(split.mine.changed).toBe('2. mine\n')
    expect(split.mine.after).toBe('\nend\n')
    expect(split.theirs.changed).toBe('2. theirs\n')
  })

  it('marks nothing when the two bodies are identical', () => {
    // Reachable, and the banner says so in words: a write that only *touched* the body still carries
    // it, and ADR 0009 guards on the field being present.
    const split = splitOnChange('same\n', 'same\n')

    expect(split.mine.changed).toBe('')
    expect(split.theirs.changed).toBe('')
    expect(split.mine.before).toBe('same\n')
  })

  it('marks a whole insertion when one side has nothing', () => {
    const split = splitOnChange('added\n', '')

    expect(split.mine.changed).toBe('added\n')
    expect(split.theirs.changed).toBe('')
  })
})

describe('compareMetadata — identical on both sides is correct, and must not read as a diff', () => {
  it('reports title and path as agreed for a body-only write, which is every SPA write', () => {
    // `attempted_version` fills the fields the caller did not send from the **stored** note, because
    // kaya never saw the caller's base version. So these match by construction.
    const comparison = compareMetadata(conflict({ body: 'mine' }, { body: 'theirs' }))

    expect(comparison.differing).toEqual([])
    expect(comparison.agreed).toEqual([
      { name: 'title', value: 'Conflicts' },
      { name: 'path', value: 'design/conflicts.md' },
    ])
  })

  it('still notices a genuine difference rather than assuming they agree', () => {
    const comparison = compareMetadata(conflict({ title: 'Mine' }, { title: 'Theirs' }))

    expect(comparison.differing).toEqual([{ name: 'title', mine: 'Mine', theirs: 'Theirs' }])
    expect(comparison.agreed.map((field) => field.name)).toEqual(['path'])
  })

  it('does not offer updated_at as a field to choose between', () => {
    // It is the one field that *must* differ (`concurrency.py`'s first "looks like a bug and is
    // not"), and the banner names both stamps in its own line. Listing it as differing metadata would
    // invite a choice that does not exist.
    const names = compareMetadata(conflict({}, {})).differing.map((field) => field.name)

    expect(names).not.toContain('updated_at')
    expect(names).not.toContain('ref')
  })
})
