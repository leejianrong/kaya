/**
 * ADR 0009's `409`, turned into the two things a person can do about it — as pure functions.
 *
 * `lib/editor.ts`'s {@link conflictVersions} reads the two whole notes out of `ApiError.details`;
 * this module is what the banner then does with them. Everything here is a total function over two
 * `Note`s, so the resolution rule and the comparison are testable in `node` without a DOM, and
 * `ConflictBanner.svelte` is left holding markup only.
 *
 * ## The one rule that matters
 *
 * {@link keepMinePatch} is the whole resolution mechanism, and it **crosses the two versions**: the
 * body comes from `attempted` and the precondition from `stored`. `backend/app/api/concurrency.py`
 * says so in the docstring that specified this card, and it is the reason both objects carry their
 * own `updated_at` — "keep mine" is the same guarded `PATCH` again, aimed at the version that
 * refused it. Sending the *attempted* stamp back would refuse it a second time, forever.
 *
 * The words are "mine" and "theirs" only here, in the browser. The API says `attempted` and
 * `stored`, because the same `409` body reaches `kaya note edit` and a future MCP tool, where "mine"
 * names nobody.
 */

import type { Note, NoteUpdate } from './types'

/** ADR 0009's two versions: what this caller tried to write, and what is on the server. */
export interface ConflictVersions {
  attempted: Note
  stored: Note
}

/**
 * "Keep mine", as the `PATCH` body it is.
 *
 * `body` from `attempted` and `if_updated_at` from **`stored`**, both **verbatim**. The stamp is an
 * opaque string here exactly as it is on the first write (`lib/types.ts`, `kaya-client`): ADR 0009's
 * comparison is exact to the microsecond and `new Date(s).toISOString()` rounds to milliseconds, so
 * a stamp parsed anywhere on this path refuses *every* correct write. This is the **second** place in
 * the SPA a precondition is built, so it carries its own assertion in `tests/conflict.test.ts` rather
 * than relying on the one covering the first.
 *
 * The body is `attempted`'s and not the editor's current document, because `attempted` is what the
 * banner *shows* under "mine" and a button that writes something not on the screen is a different
 * button. If the user typed on while reading the banner, the pane stays "unsaved changes" afterwards
 * — which is true, and is what {@link keepMinePatch} not seeing the document makes unavoidable.
 *
 * `title` and `path` are deliberately absent. A `PATCH` sends what it changes; this resolves a body
 * conflict, and resending metadata would let the resolution overwrite a rename that had nothing to do
 * with it.
 */
export function keepMinePatch(versions: ConflictVersions): NoteUpdate {
  return {
    body: versions.attempted.body,
    if_updated_at: versions.stored.updated_at,
  }
}

/** One body cut into the part before the change, the changed part, and the part after. */
export interface BodySplit {
  before: string
  changed: string
  after: string
}

/**
 * Both bodies, each cut into three so the side-by-side can mark the region that differs.
 *
 * **This is a bound, not a diff, and the distinction is the honest part.** It trims the lines the
 * two bodies share at the start and at the end, and marks everything left in the middle. What it
 * guarantees is exact:
 *
 * - `before + changed + after` is the original body, byte for byte — the segments are slices, so a
 *   rendered `<pre>` of the three is a faithful copy of the note and not a reconstruction of one.
 * - Every line *outside* the marked region is identical to the line at the same distance from the
 *   same end of the other body. So no difference hides in the unmarked part.
 *
 * What it does **not** do is align anything in the middle. A one-line insert near the top and an
 * unrelated edit near the bottom mark everything between them, and a change on line 1 of a
 * 3,000-word note marks the whole note. That is the deliberate trade: an LCS line diff would mark
 * less, and it would also be the first thing in this repository that can be *wrong* about what
 * changed while looking authoritative. ADR 0009 already refuses to auto-merge prose on that
 * reasoning ("sounds helpful and silently produces garbage"); showing both versions faithfully and
 * pointing at a region that provably contains every difference is the same argument one step down.
 *
 * Identical bodies come back with `changed === ''` on both sides, which is a reachable state: a write
 * that only *touched* the body (typed and deleted) still carries it, and ADR 0009 guards on the
 * presence of the field rather than on a value having changed.
 */
export function splitOnChange(mine: string, theirs: string): { mine: BodySplit; theirs: BodySplit } {
  const left = toLines(mine)
  const right = toLines(theirs)

  let head = 0
  while (head < left.length && head < right.length && left[head] === right[head]) {
    head += 1
  }

  let tail = 0
  while (
    tail < left.length - head &&
    tail < right.length - head &&
    left[left.length - 1 - tail] === right[right.length - 1 - tail]
  ) {
    tail += 1
  }

  return { mine: cut(left, head, tail), theirs: cut(right, head, tail) }
}

/**
 * Lines **with their terminators kept**, so joining them back is the identity function.
 *
 * A plain `split('\n')` loses the information about whether the text ended in a newline, and the
 * side-by-side would then render a body one byte different from the note — on a screen whose whole
 * purpose is deciding which bytes to keep.
 */
function toLines(text: string): string[] {
  return text.match(/[^\n]*\n|[^\n]+/g) ?? []
}

function cut(lines: string[], head: number, tail: number): BodySplit {
  return {
    before: lines.slice(0, head).join(''),
    changed: lines.slice(head, lines.length - tail).join(''),
    after: lines.slice(lines.length - tail).join(''),
  }
}

/** One metadata field, as the two versions spell it. */
export interface FieldPair {
  name: string
  mine: string
  theirs: string
}

/** The metadata fields the two versions agree on, and the ones they do not. */
export interface MetadataComparison {
  agreed: { name: string; value: string }[]
  differing: FieldPair[]
}

/**
 * `title` and `path` on both versions, sorted into agreed and differing.
 *
 * **This exists because "identical on both sides" is correct here and looks like a bug.**
 * `concurrency.py`'s `attempted_version` fills the fields the caller did not send from the **stored**
 * note — kaya never saw the caller's base version, only the token naming it — so a body-only write
 * (which is every write the SPA makes) produces a `409` whose `title` and `path` match on both
 * sides by construction. Rendering them as two competing values would invite the user to pick between
 * two identical strings; rendering them once, named as shared, says what is actually true.
 *
 * They are still compared rather than assumed equal, because the same banner would be reached by a
 * write that *did* send a title, and a rename silently displayed as shared would be the opposite
 * mistake.
 *
 * `ref` and `created_at` are not here (equal by construction, and neither is a thing to choose
 * between); `updated_at` is not either, because it is the one field that *must* differ and the banner
 * names both stamps in its own line.
 */
export function compareMetadata(versions: ConflictVersions): MetadataComparison {
  const comparison: MetadataComparison = { agreed: [], differing: [] }

  for (const name of ['title', 'path'] as const) {
    const mine = versions.attempted[name]
    const theirs = versions.stored[name]
    if (mine === theirs) {
      comparison.agreed.push({ name, value: mine })
    } else {
      comparison.differing.push({ name, mine, theirs })
    }
  }

  return comparison
}
