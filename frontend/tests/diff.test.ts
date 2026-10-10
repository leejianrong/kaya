import { describe, expect, it } from 'vitest'

import { diffLines, diffStats, MAX_CELLS, splitLines, withContext } from '../src/lib/diff'
import { actorLabel, previousIndex, versionNumber } from '../src/lib/history'
import type { NoteVersion } from '../src/lib/types'

describe('splitLines', () => {
  it('counts lines the way a reader does', () => {
    expect(splitLines('')).toEqual([])
    expect(splitLines('a')).toEqual(['a'])
    expect(splitLines('a\nb\n')).toEqual(['a', 'b'])
    expect(splitLines('a\n\nb')).toEqual(['a', '', 'b'])
  })
})

describe('diffLines', () => {
  it('is all same for equal bodies', () => {
    const lines = diffLines('a\nb', 'a\nb')
    expect(lines.every((line) => line.kind === 'same')).toBe(true)
    expect(diffStats(lines)).toEqual({ added: 0, removed: 0 })
  })

  it('reports an edited middle line as one removal and one addition, with line numbers', () => {
    const lines = diffLines('a\nb\nc', 'a\nB\nc')
    expect(lines).toEqual([
      { kind: 'same', text: 'a', oldNo: 1, newNo: 1 },
      { kind: 'del', text: 'b', oldNo: 2, newNo: null },
      { kind: 'add', text: 'B', oldNo: null, newNo: 2 },
      { kind: 'same', text: 'c', oldNo: 3, newNo: 3 },
    ])
  })

  it('handles insertions that shift later lines', () => {
    const lines = diffLines('a\nc', 'a\nb\nc')
    expect(diffStats(lines)).toEqual({ added: 1, removed: 0 })
    expect(lines.at(-1)).toEqual({ kind: 'same', text: 'c', oldNo: 2, newNo: 3 })
  })

  it('treats the first version as all additions against an empty body', () => {
    expect(diffStats(diffLines('', 'x\ny'))).toEqual({ added: 2, removed: 0 })
    expect(diffStats(diffLines('x\ny', ''))).toEqual({ added: 0, removed: 2 })
  })

  it('finds a minimal diff inside interleaved changes', () => {
    const lines = diffLines('1\n2\n3\n4\n5', '1\nx\n3\ny\n5')
    expect(diffStats(lines)).toEqual({ added: 2, removed: 2 })
  })

  it('degrades to remove-all then add-all past the cell budget, never hanging', () => {
    const side = Math.ceil(Math.sqrt(MAX_CELLS)) + 10
    const older = Array.from({ length: side }, (_, i) => `old ${i}`).join('\n')
    const newer = Array.from({ length: side }, (_, i) => `new ${i}`).join('\n')
    expect(diffStats(diffLines(older, newer))).toEqual({ added: side, removed: side })
  })
})

describe('withContext', () => {
  it('folds a long unchanged run and keeps context around a change', () => {
    const body = Array.from({ length: 20 }, (_, i) => `l${i}`)
    const edited = [...body]
    edited[10] = 'CHANGED'
    const rows = withContext(diffLines(body.join('\n'), edited.join('\n')), 2)
    expect(rows[0]).toEqual({ kind: 'skip', count: 8 })
    expect(rows.at(-1)).toEqual({ kind: 'skip', count: 7 })
    expect(rows.filter((row) => row.kind !== 'skip')).toHaveLength(6)
  })

  it('is empty when nothing changed', () => {
    expect(withContext(diffLines('a', 'a'))).toEqual([])
  })
})

function version(id: number, overrides: Partial<NoteVersion> = {}): NoteVersion {
  return { id, body: '', created_at: '2026-10-01T00:00:00+00:00', ...overrides }
}

describe('actorLabel', () => {
  it('says before tracking for a version with no actor, and never guesses', () => {
    expect(actorLabel(null)).toEqual({ who: 'before tracking', how: null })
    expect(actorLabel(undefined)).toEqual({ who: 'before tracking', how: null })
  })

  it('says You on the web for the viewer own cookie session', () => {
    expect(
      actorLabel({ user_id: 'u', email: 'a@x.io', channel: 'session', token: null, is_you: true }),
    ).toEqual({ who: 'You', how: 'web' })
  })

  it('names a token by name and its display prefix only', () => {
    expect(
      actorLabel({
        user_id: 'u',
        email: 'a@x.io',
        channel: 'token',
        token: { id: 1, prefix: 'kaya_pat_ab12', name: 'ci-bot', kind: null },
        is_you: false,
      }),
    ).toEqual({ who: 'a@x.io', how: 'Token ci-bot (kaya_pat_ab12…)' })
  })

  it('appends a token kind when one exists', () => {
    const label = actorLabel({
      user_id: 'u',
      email: 'a@x.io',
      channel: 'token',
      token: { id: 1, prefix: 'kaya_pat_ab12', name: 'ci-bot', kind: 'read-only' },
      is_you: true,
    })
    expect(label.how).toBe('Token ci-bot (kaya_pat_ab12…) · read-only')
  })
})

describe('version ordinals', () => {
  const versions = [version(9), version(8), version(7)]
  it('numbers oldest first, matching the CLI', () => {
    expect([0, 1, 2].map((i) => versionNumber(versions, i))).toEqual([3, 2, 1])
  })
  it('compares against the next row down, and nothing for the first version', () => {
    expect(previousIndex(versions, 0)).toBe(1)
    expect(previousIndex(versions, 2)).toBeNull()
  })
})
