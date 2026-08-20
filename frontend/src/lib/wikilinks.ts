/**
 * KAN-567's pure half: finding `[[...]]` spans in a note's raw markdown text and deciding what each
 * one's pill should say, with no CodeMirror value anywhere in this file.
 *
 * Same split `lib/editor.ts` and `lib/backlinks.ts` already make — the decision lives here as a
 * plain function over plain data, so it is tested in vitest's default `node` environment, and
 * `lib/codemirror.ts` is left holding only the parts that genuinely need a CodeMirror value in
 * scope (`Decoration`, `ViewPlugin`, `syntaxTree`).
 *
 * ## The grammar, mirrored from the backend rather than re-invented
 *
 * `PANDAN_REF` and `NOTE_TITLE` are `backend/app/wikilinks.py`'s `WIKILINK_PATTERN` and
 * `NOTE_TITLE_PATTERN`, field for field: `[[`, optional horizontal whitespace, either a literal
 * `KAN`/`EPIC` prefix plus digits or (via a negative lookahead refusing exactly that shape) any
 * run of non-bracket, non-newline text, optional whitespace, `]]`. No wildcard spans a bracket in
 * either pattern, which is what makes nesting resolve to the innermost well-formed pair here too,
 * for the identical structural reason the backend's docstring gives. `[ \t]*` rather than `\s*`
 * throughout, for the backend's own reason: a wikilink is written on one line, and letting one span
 * a hand-typed newline is a shape no editor produces by hand.
 *
 * JS's `\d` needs no `re.ASCII` companion the way the backend's does: without the `u`/`v` flag this
 * engine's `\d` is always `[0-9]`, never a Unicode decimal digit, so there is no separate gate to
 * carry over.
 *
 * ## What is deliberately not here
 *
 * **Fence exclusion.** `backend/app/wikilinks.py` hand-rolls a line-based fence scanner because
 * Python has no markdown parser in scope there; this app already has CM6's own syntax tree
 * (`markdownLanguage` is loaded), so `lib/codemirror.ts` derives fenced ranges from
 * `syntaxTree(state)` and calls {@link excludeFenced} rather than this module re-parsing fences by
 * regex a second time — CM6 already did that work once. Keeping the exclusion out of this file is
 * what keeps it free of a CodeMirror import.
 *
 * **A body's actual resolution.** Whether a span names something that exists is `/links`' question,
 * answered by kaya's own database and, for a pandan-shaped ref, by pandan. This module never asks —
 * {@link matchingLink} only reads the answer `/links` already gave, and a span it cannot find a row
 * for is reported as unresolved rather than guessed at.
 */

import type { Link } from './types'

/** One `[[KAN-n]]` / `[[EPIC-n]]` span. */
export interface KanEpicSpan {
  kind: 'KAN' | 'EPIC'
  /** Canonical `KAN-501` spelling — case-normalised, brackets and padding gone — matching
   *  `LinkRead.target_ref` for a pandan-kind edge (`WikilinkRef.canonical` server-side). */
  ref: string
  start: number
  end: number
}

/** One `[[Some Note Title]]` span. */
export interface NoteTitleSpan {
  kind: 'NOTE'
  /** The title exactly as typed inside the brackets, only the immediately-surrounding whitespace
   *  trimmed — never case-folded, matching `LinkRead.target_ref` for a `NOTE` edge. */
  title: string
  start: number
  end: number
}

export type WikilinkSpan = KanEpicSpan | NoteTitleSpan

const PANDAN_REF = /\[\[[ \t]*(KAN|EPIC)-(\d+)[ \t]*\]\]/gi

// The lookahead's vocabulary is this pattern's own `KAN|EPIC` + digits, so a bracket pair
// `PANDAN_REF` would itself recognise is never reported twice here — the backend's "KAN-563's
// answer" paragraph, mirrored rather than re-derived.
const NOTE_TITLE = /\[\[(?![ \t]*(?:KAN|EPIC)-[0-9]+[ \t]*\]\])[ \t]*([^[\]\n]+?)[ \t]*\]\]/gi

/** Byte-for-byte `backend/app/wikilinks.py`'s `NOTE_TITLE_MAX`, duplicated rather than imported —
 *  this module is pure text-in-spans-out and reaches into no persistence layer for a constant, the
 *  same direction that file draws against its own database. */
export const NOTE_TITLE_MAX = 255

/**
 * Every `[[KAN-n]]` / `[[EPIC-n]]` / `[[Some Note Title]]` span in `text`, left to right.
 *
 * Fences are **not** excluded here — see the module header. A caller with a syntax tree in scope
 * filters this list with {@link excludeFenced}; a caller without one (a unit test) sees the same
 * spans a fence-blind reading of the text produces, which is the honest thing to test at this
 * layer.
 *
 * A whitespace-only title and a title longer than {@link NOTE_TITLE_MAX} are both reported as *no*
 * span, the same "not a link" treatment the backend gives `[[KAN-]]`'s missing digits.
 */
export function findWikilinkSpans(text: string): WikilinkSpan[] {
  const spans: WikilinkSpan[] = []
  for (const match of text.matchAll(PANDAN_REF)) {
    const kind = match[1].toUpperCase() as 'KAN' | 'EPIC'
    const start = match.index ?? 0
    spans.push({ kind, ref: `${kind}-${match[2]}`, start, end: start + match[0].length })
  }
  for (const match of text.matchAll(NOTE_TITLE)) {
    const title = match[1].trim()
    if (title === '' || title.length > NOTE_TITLE_MAX) {
      continue
    }
    const start = match.index ?? 0
    spans.push({ kind: 'NOTE', title, start, end: start + match[0].length })
  }
  return spans.sort((a, b) => a.start - b.start)
}

/** Drop every span that starts inside one of `fenced`'s `[from, to)` ranges. */
export function excludeFenced(
  spans: readonly WikilinkSpan[],
  fenced: readonly { from: number; to: number }[],
): WikilinkSpan[] {
  if (fenced.length === 0) {
    return [...spans]
  }
  return spans.filter(
    (span) => !fenced.some((range) => span.start >= range.from && span.start < range.to),
  )
}

/**
 * The `/links` row this span names, or `undefined` if `/links` never mentioned it.
 *
 * **`undefined` covers two situations the editor cannot tell apart, and that is a decision rather
 * than a gap**: a span the API genuinely could not resolve, and a span typed since the last save
 * that `note_link` has never seen (KAN-562 reconciles on save, not on keystroke). Both render
 * identically — as an unresolved pill — because guessing a resolution kaya's own database does not
 * have would show a caller something it cannot back up. See `EditorPane.svelte`'s docstring for
 * where the re-fetch that narrows this window happens (on mount and after every save).
 */
export function matchingLink(span: WikilinkSpan, links: readonly Link[]): Link | undefined {
  return span.kind === 'NOTE'
    ? links.find((link) => link.target_kind === 'NOTE' && link.target_ref === span.title)
    : links.find((link) => link.target_kind === span.kind && link.target_ref === span.ref)
}

/** Whether {@link matchingLink} found a resolved answer — the one thing the pill's CSS class needs. */
export function isResolved(link: Link | undefined): boolean {
  return link !== undefined && link.resolved_ref !== null
}

/**
 * The pill's hover text — the demo's `KAN-501 · in_progress · "title"` shape when resolved, or an
 * honest explanation of why there is nothing to show yet.
 *
 * `title` rather than replaced visible text, matching `lib/markdown.ts`'s `unlinked()` convention:
 * the raw `[[...]]` a person typed stays exactly what the caret can edit, and the extra context is a
 * native tooltip rather than a rewrite of what is on screen.
 */
export function wikilinkTooltip(span: WikilinkSpan, link: Link | undefined): string {
  if (link === undefined || link.resolved_ref === null) {
    return span.kind === 'NOTE'
      ? `not linked: no note titled "${span.title}" (yet — save to check again)`
      : `not linked: pandan has no ${span.ref}, or it hasn't resolved yet (save to check again)`
  }
  const parts = [link.resolved_ref]
  if (link.column !== null) {
    parts.push(link.column)
  }
  if (link.title !== null) {
    parts.push(`"${link.title}"`)
  }
  return parts.join(' · ')
}

/** What `[[` completion should search for, and where the insertion starts. */
export interface WikilinkTrigger {
  /** Offset within `lineText`, right after the opening `[[`. */
  from: number
  /** Everything typed since, on this line. */
  query: string
}

const TRIGGER = /\[\[([^[\]\n]*)$/

/**
 * Whether the caret sits inside an unclosed `[[…` on one line, and what has been typed since.
 *
 * `null` the moment a `]` or a newline has appeared since the last `[[`, or when there is no
 * unclosed `[[` on this line at all — the trigger closes the moment a link closes, which is what
 * keeps completion from reopening over a `[[KAN-501]]` a person is done typing.
 */
export function wikilinkTrigger(lineText: string, caretInLine: number): WikilinkTrigger | null {
  const before = lineText.slice(0, caretInLine)
  const match = TRIGGER.exec(before)
  return match === null ? null : { from: (match.index ?? 0) + 2, query: match[1] }
}
