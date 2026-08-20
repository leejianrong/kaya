/**
 * `lib/wikilinks.ts`'s pure half — span-finding, fence exclusion, link matching and the `[[`
 * trigger — in vitest's default `node` environment, the same shape `tests/editor-guards.test.ts`
 * and `tests/backlinks-subject.test.ts` already use for the decisions beside a CodeMirror value.
 *
 * The span-finding cases mirror `backend/app/wikilinks.py`'s own unit suite on purpose: nesting, an
 * unclosed `[[`, surrounding punctuation and the `KAN-1`-is-not-a-title exclusion are all properties
 * this module claims to inherit from the backend's grammar, so the same fixtures are the check that
 * it actually did.
 */

import { describe, expect, it } from 'vitest'

import type { Link } from '../src/lib/types'
import {
  excludeFenced,
  findWikilinkSpans,
  isResolved,
  matchingLink,
  wikilinkTooltip,
  wikilinkTrigger,
} from '../src/lib/wikilinks'

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

describe('findWikilinkSpans', () => {
  it('finds a pandan reference, case-insensitively, canonicalised', () => {
    const spans = findWikilinkSpans('See [[ kan-501 ]] for details.')
    expect(spans).toEqual([{ kind: 'KAN', ref: 'KAN-501', start: 4, end: 17 }])
  })

  it('finds an epic reference the same way', () => {
    const spans = findWikilinkSpans('[[EPIC-3]]')
    expect(spans).toEqual([{ kind: 'EPIC', ref: 'EPIC-3', start: 0, end: 10 }])
  })

  it('finds a note-title link, trimmed but not case-folded', () => {
    const spans = findWikilinkSpans('[[  Weekly Review  ]]')
    expect(spans).toEqual([{ kind: 'NOTE', title: 'Weekly Review', start: 0, end: 21 }])
  })

  it('does not double-report a pandan reference as a literal title', () => {
    // The exclusion is `NOTE_TITLE`'s own negative lookahead, mirroring the backend's "KAN-563's
    // answer": without it, `[[KAN-1]]` would be a pandan ref *and* a note titled "KAN-1".
    expect(findWikilinkSpans('[[KAN-1]]')).toEqual([{ kind: 'KAN', ref: 'KAN-1', start: 0, end: 9 }])
  })

  it('leaves an unclosed `[[` as prose', () => {
    expect(findWikilinkSpans('a dangling [[KAN-123 with no close')).toEqual([])
  })

  it('resolves nesting to the innermost well-formed pair', () => {
    // `backend/app/wikilinks.py`'s own example: the outer pair is malformed (it contains a stray
    // `[[`), so only `KAN-2` is found.
    const spans = findWikilinkSpans('[[KAN-1 [[KAN-2]] ]]')
    expect(spans).toEqual([{ kind: 'KAN', ref: 'KAN-2', start: 8, end: 17 }])
  })

  it('never swallows surrounding punctuation', () => {
    expect(findWikilinkSpans('([[KAN-123]].)')).toEqual([
      { kind: 'KAN', ref: 'KAN-123', start: 1, end: 12 },
    ])
  })

  it('does not span a hand-typed newline', () => {
    expect(findWikilinkSpans('[[KAN-\n123]]')).toEqual([])
  })

  it('reports no span for a whitespace-only title', () => {
    expect(findWikilinkSpans('[[   ]]')).toEqual([])
  })

  it('reports no span for a title longer than 255 characters', () => {
    const long = 'x'.repeat(256)
    expect(findWikilinkSpans(`[[${long}]]`)).toEqual([])
  })

  it('finds every span left to right, sorted by position', () => {
    const spans = findWikilinkSpans('[[KAN-1]] and [[Some Note]] and [[EPIC-9]]')
    expect(spans.map((span) => span.start)).toEqual([0, 14, 32])
  })
})

describe('excludeFenced', () => {
  it('drops a span whose start falls inside a fenced range', () => {
    const spans = findWikilinkSpans('before [[KAN-1]] ```\n[[KAN-2]]\n``` after [[KAN-3]]')
    const fenceStart = spans.find((s) => s.kind === 'KAN' && s.ref === 'KAN-2')!.start
    const visible = excludeFenced(spans, [{ from: fenceStart - 4, to: fenceStart + 20 }])
    expect(visible.map((s) => (s.kind === 'NOTE' ? s.title : s.ref))).toEqual(['KAN-1', 'KAN-3'])
  })

  it('is a no-op with no fenced ranges', () => {
    const spans = findWikilinkSpans('[[KAN-1]]')
    expect(excludeFenced(spans, [])).toEqual(spans)
  })
})

describe('matchingLink', () => {
  it('matches a KAN/EPIC span on kind and canonical ref', () => {
    const links = [link()]
    const span = findWikilinkSpans('[[kan-501]]')[0]
    expect(matchingLink(span, links)).toBe(links[0])
  })

  it('matches a NOTE span on the title exactly, case included', () => {
    const target = link({ target_kind: 'NOTE', target_ref: 'Weekly Review', resolved_ref: 'NOTE-9' })
    const span = findWikilinkSpans('[[Weekly Review]]')[0]
    expect(matchingLink(span, [target])).toBe(target)

    // Case matters for a NOTE match — `backend/app/wikilinks.py`'s `NoteTitleLink.title` is never
    // case-folded, and `Note.title` matching mirrors that.
    const differentCase = findWikilinkSpans('[[weekly review]]')[0]
    expect(matchingLink(differentCase, [target])).toBeUndefined()
  })

  it('returns undefined for a span `/links` never mentioned', () => {
    const span = findWikilinkSpans('[[KAN-999]]')[0]
    expect(matchingLink(span, [link()])).toBeUndefined()
  })
})

describe('isResolved', () => {
  it('is true only for a link whose resolved_ref is not null', () => {
    expect(isResolved(link())).toBe(true)
    expect(isResolved(link({ resolved_ref: null, title: null, column: null }))).toBe(false)
    expect(isResolved(undefined)).toBe(false)
  })
})

describe('wikilinkTooltip', () => {
  it('renders the demo string for a resolved card: ref · column · "title"', () => {
    const span = findWikilinkSpans('[[KAN-501]]')[0]
    expect(wikilinkTooltip(span, link())).toBe(
      'KAN-501 · in_progress · "MCP read tools: add a fields argument"',
    )
  })

  it('omits the column for a resolved epic or note', () => {
    const span = findWikilinkSpans('[[EPIC-3]]')[0]
    const epic = link({ target_kind: 'EPIC', target_ref: 'EPIC-3', resolved_ref: 'EPIC-3', column: null })
    expect(wikilinkTooltip(span, epic)).toBe('EPIC-3 · "MCP read tools: add a fields argument"')
  })

  it('explains an unresolved pandan reference without inventing one', () => {
    const span = findWikilinkSpans('[[KAN-999]]')[0]
    expect(wikilinkTooltip(span, undefined)).toContain('KAN-999')
    expect(wikilinkTooltip(span, undefined)).toContain('not linked')
  })

  it('explains an unresolved note title by name', () => {
    const span = findWikilinkSpans('[[Some Title]]')[0]
    expect(wikilinkTooltip(span, undefined)).toContain('Some Title')
  })
})

describe('wikilinkTrigger', () => {
  it('finds the trigger right after typing `[[`', () => {
    expect(wikilinkTrigger('See [[', 6)).toEqual({ from: 6, query: '' })
  })

  it('carries the text typed since as the query', () => {
    expect(wikilinkTrigger('See [[week', 10)).toEqual({ from: 6, query: 'week' })
  })

  it('closes the moment a `]` appears since the last `[[`, right after that close', () => {
    const line = 'See [[KAN-501]]'
    expect(wikilinkTrigger(line, line.length)).toBeNull()
  })

  it('is null with no unclosed `[[` on the line at all', () => {
    expect(wikilinkTrigger('just some prose', 10)).toBeNull()
  })

  it('finds the second `[[`, unconfused by the first, already-closed one', () => {
    const line = '[[KAN-1]] then [[wee'
    expect(wikilinkTrigger(line, line.length)).toEqual({ from: 17, query: 'wee' })
  })
})
