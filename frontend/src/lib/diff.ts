/**
 * A line-level diff, as a pure function (KAY-138) — no dependency, no DOM.
 *
 * A note body is small prose and a version is a whole body, so the History tab diffs two bodies it
 * already holds rather than asking the server (and `kaya note diff` does the same over the same
 * list). Measured against the alternatives: a diff library is tens of kB gzipped for a feature
 * that needs line granularity only, and this file is ~1 kB.
 *
 * Shape: trim the common prefix and suffix, then a longest-common-subsequence table over the
 * differing middle. The table is quadratic, so a middle past {@link MAX_CELLS} cells (two
 * ~2000-line rewrites) degrades to "all removed, then all added": still a correct diff, just not a
 * minimal one, and never a frozen tab.
 */

export type DiffKind = 'same' | 'add' | 'del'

export interface DiffLine {
  kind: DiffKind
  text: string
  /** 1-based line number in the older body, `null` for an added line. */
  oldNo: number | null
  /** 1-based line number in the newer body, `null` for a removed line. */
  newNo: number | null
}

/** A run of unchanged lines folded away, with how many it hides. */
export interface DiffSkip {
  kind: 'skip'
  count: number
}

export type DiffRow = DiffLine | DiffSkip

export const MAX_CELLS = 4_000_000

/** Split a body into lines the way a reader counts them: `''` is no lines, a trailing newline does
 *  not add an empty last line. */
export function splitLines(body: string): string[] {
  if (body === '') {
    return []
  }
  const lines = body.split('\n')
  if (lines[lines.length - 1] === '') {
    lines.pop()
  }
  return lines
}

/** Every line of `older` → `newer`, unchanged ones included, in reading order. */
export function diffLines(older: string, newer: string): DiffLine[] {
  const a = splitLines(older)
  const b = splitLines(newer)

  let start = 0
  while (start < a.length && start < b.length && a[start] === b[start]) {
    start++
  }
  let endA = a.length
  let endB = b.length
  while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) {
    endA--
    endB--
  }

  const out: DiffLine[] = []
  for (let i = 0; i < start; i++) {
    out.push({ kind: 'same', text: a[i], oldNo: i + 1, newNo: i + 1 })
  }

  const midA = a.slice(start, endA)
  const midB = b.slice(start, endB)
  for (const step of diffMiddle(midA, midB)) {
    if (step.kind === 'same') {
      out.push({ kind: 'same', text: step.text, oldNo: start + step.i + 1, newNo: start + step.j + 1 })
    } else if (step.kind === 'del') {
      out.push({ kind: 'del', text: step.text, oldNo: start + step.i + 1, newNo: null })
    } else {
      out.push({ kind: 'add', text: step.text, oldNo: null, newNo: start + step.j + 1 })
    }
  }

  for (let k = 0; endA + k < a.length; k++) {
    out.push({ kind: 'same', text: a[endA + k], oldNo: endA + k + 1, newNo: endB + k + 1 })
  }
  return out
}

interface Step {
  kind: DiffKind
  text: string
  /** Index into the middle of the older side (meaningful for `same` and `del`). */
  i: number
  /** Index into the middle of the newer side (meaningful for `same` and `add`). */
  j: number
}

function diffMiddle(a: string[], b: string[]): Step[] {
  const steps: Step[] = []
  if (a.length === 0 || b.length === 0 || (a.length + 1) * (b.length + 1) > MAX_CELLS) {
    a.forEach((text, i) => steps.push({ kind: 'del', text, i, j: 0 }))
    b.forEach((text, j) => steps.push({ kind: 'add', text, i: 0, j }))
    return steps
  }

  const width = b.length + 1
  // lcs[i * width + j] = LCS length of a[i..] and b[j..].
  const lcs = new Uint32Array((a.length + 1) * width)
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      lcs[i * width + j] =
        a[i] === b[j]
          ? lcs[(i + 1) * width + j + 1] + 1
          : Math.max(lcs[(i + 1) * width + j], lcs[i * width + j + 1])
    }
  }

  let i = 0
  let j = 0
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      steps.push({ kind: 'same', text: a[i], i, j })
      i++
      j++
    } else if (lcs[(i + 1) * width + j] >= lcs[i * width + j + 1]) {
      steps.push({ kind: 'del', text: a[i], i, j })
      i++
    } else {
      steps.push({ kind: 'add', text: b[j], i, j })
      j++
    }
  }
  for (; i < a.length; i++) {
    steps.push({ kind: 'del', text: a[i], i, j })
  }
  for (; j < b.length; j++) {
    steps.push({ kind: 'add', text: b[j], i, j })
  }
  return steps
}

/** How many lines a diff adds and removes. */
export function diffStats(lines: DiffLine[]): { added: number; removed: number } {
  let added = 0
  let removed = 0
  for (const line of lines) {
    if (line.kind === 'add') {
      added++
    } else if (line.kind === 'del') {
      removed++
    }
  }
  return { added, removed }
}

/**
 * Fold unchanged runs longer than `2 * context` down to `context` lines either side of a change
 * and a {@link DiffSkip} saying how many were hidden. A diff with no changes folds to nothing at
 * all: the caller says "no changes" rather than showing the whole note twice.
 */
export function withContext(lines: DiffLine[], context = 3): DiffRow[] {
  if (!lines.some((line) => line.kind !== 'same')) {
    return []
  }
  const keep = new Array<boolean>(lines.length).fill(false)
  lines.forEach((line, index) => {
    if (line.kind === 'same') {
      return
    }
    for (let k = Math.max(0, index - context); k <= Math.min(lines.length - 1, index + context); k++) {
      keep[k] = true
    }
  })

  const rows: DiffRow[] = []
  let hidden = 0
  lines.forEach((line, index) => {
    if (keep[index]) {
      if (hidden > 0) {
        rows.push({ kind: 'skip', count: hidden })
        hidden = 0
      }
      rows.push(line)
    } else {
      hidden++
    }
  })
  if (hidden > 0) {
    rows.push({ kind: 'skip', count: hidden })
  }
  return rows
}
