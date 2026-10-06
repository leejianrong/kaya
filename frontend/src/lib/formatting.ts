/**
 * KAN-1826: what each button of the mobile formatting toolbar does to a document, as pure functions.
 *
 * Same stance as `lib/editor.ts`: no CodeMirror at runtime, so every rule here is testable in
 * node. `applyFormat` takes the document and a selection and answers with one replacement and the
 * selection to leave behind; `lib/codemirror.ts` dispatches that as a single transaction, which is
 * what makes one tap one undo step. The answer is `null` where an action has nothing to do.
 *
 * Every action is a toggle where a toggle means something: pressing Bold on bold text removes it.
 *
 * Wikilinks interplay with `[[` completion (`lib/codemirror.ts`'s `completeWikilink`) in one way. At
 * a bare caret the button types exactly what a person would, `[[`, and asks the adapter to open the
 * completion list; choosing a title inserts `Title]]`, so adding a `]]` here as well would leave
 * four brackets. With a selection there is nothing to complete, so the selection is wrapped whole.
 */

/** The text-changing actions. Undo is the toolbar's eighth button and is not a text rule. */
export type FormatAction = 'bold' | 'italic' | 'code' | 'list' | 'checkbox' | 'link' | 'wikilink'

export interface TextSelection {
  anchor: number
  head: number
}

/** One replacement of `[from, to)` by `insert`, and where the selection goes afterwards. */
export interface FormatEdit {
  from: number
  to: number
  insert: string
  /** Selection in the document *after* the change. */
  anchor: number
  head: number
  /** The adapter should open `[[` title completion once this change has landed. */
  opensWikilinkCompletion: boolean
}

export function isUrl(text: string): boolean {
  return /^https?:\/\/\S+$/i.test(text)
}

function edit(
  from: number,
  to: number,
  insert: string,
  anchor: number,
  head: number,
  opensWikilinkCompletion = false,
): FormatEdit {
  return { from, to, insert, anchor, head, opensWikilinkCompletion }
}

/** Keep the direction the person dragged the selection in. */
function directed(backwards: boolean, start: number, end: number): [number, number] {
  return backwards ? [end, start] : [start, end]
}

// --- inline marks ---------------------------------------------------------------------------

const WORD = /[\p{L}\p{N}_]/u

function wordAround(doc: string, pos: number): [number, number] {
  let start = pos
  let end = pos
  while (start > 0 && WORD.test(doc[start - 1])) {
    start -= 1
  }
  while (end < doc.length && WORD.test(doc[end])) {
    end += 1
  }
  return [start, end]
}

function runBefore(doc: string, pos: number, char: string): number {
  let n = 0
  while (pos - n > 0 && doc[pos - n - 1] === char) {
    n += 1
  }
  return n
}

function runAfter(doc: string, pos: number, char: string): number {
  let n = 0
  while (pos + n < doc.length && doc[pos + n] === char) {
    n += 1
  }
  return n
}

/**
 * Whether a mark is applied, given the run of its character on each side. `*` is shared by italic
 * (one) and bold (two), so `***x***` is both and `**x**` is not italic: a run of three is bold
 * italic, and the odd count is what says italic is in it.
 */
function layerPresent(mark: string, run: number): boolean {
  if (mark === '**') {
    return run >= 2
  }
  if (mark === '*') {
    return run % 2 === 1
  }
  return run >= 1
}

function toggleMark(doc: string, sel: TextSelection, mark: string): FormatEdit {
  const char = mark[0]
  const len = mark.length
  const backwards = sel.anchor > sel.head
  let from = Math.min(sel.anchor, sel.head)
  let to = Math.max(sel.anchor, sel.head)
  const collapsed = from === to
  const caret = from
  if (collapsed) {
    ;[from, to] = wordAround(doc, caret)
  }

  // The selection includes its own marks: `{**word**}`.
  const text = doc.slice(from, to)
  if (text.length >= 2 * len) {
    const lead = runAfter(text, 0, char)
    const trail = runBefore(text, text.length, char)
    if (lead < text.length && layerPresent(mark, Math.min(lead, trail))) {
      const inner = text.slice(len, text.length - len)
      const [a, h] = directed(backwards, from, from + inner.length)
      return edit(from, to, inner, a, h)
    }
  }

  // The marks sit just outside the selection, or around the caret: `**{word}**`, `**|**`.
  const left = runBefore(doc, from, char)
  const right = runAfter(doc, to, char)
  if (layerPresent(mark, Math.min(left, right))) {
    const outerFrom = from - len
    const outerTo = to + len
    if (collapsed) {
      const at = Math.max(outerFrom, caret - len)
      return edit(outerFrom, outerTo, doc.slice(from, to), at, at)
    }
    const [a, h] = directed(backwards, outerFrom, outerFrom + (to - from))
    return edit(outerFrom, outerTo, doc.slice(from, to), a, h)
  }

  // Fenced block for a code selection that spans lines; inline backticks cannot.
  if (mark === '`' && !collapsed && text.includes('\n')) {
    const [a, h] = directed(backwards, from + 4, from + 4 + text.length)
    return edit(from, to, `\`\`\`\n${text}\n\`\`\``, a, h)
  }

  // Apply the mark.
  if (from === to) {
    return edit(from, to, mark + mark, from + len, from + len)
  }
  if (collapsed) {
    return edit(from, to, mark + text + mark, caret + len, caret + len)
  }
  const [a, h] = directed(backwards, from + len, to + len)
  return edit(from, to, mark + text + mark, a, h)
}

// --- line prefixes --------------------------------------------------------------------------

type LineKind = 'plain' | 'bullet' | 'checkbox'

interface LineEdit {
  /** Absolute offset where the prefix sits (after indentation). */
  at: number
  removed: number
  inserted: string
}

const CHECKBOX_PREFIX = /^[-*+] \[[ xX]\] /
const BULLET_PREFIX = /^[-*+] /
const ORDERED_PREFIX = /^\d+[.)] /

function prefixOf(rest: string): { kind: LineKind; text: string } {
  const checkbox = CHECKBOX_PREFIX.exec(rest)
  if (checkbox !== null) {
    return { kind: 'checkbox', text: checkbox[0] }
  }
  const bullet = BULLET_PREFIX.exec(rest)
  if (bullet !== null) {
    return { kind: 'bullet', text: bullet[0] }
  }
  const ordered = ORDERED_PREFIX.exec(rest)
  return { kind: 'plain', text: ordered === null ? '' : ordered[0] }
}

function mapThrough(pos: number, lines: LineEdit[]): number {
  let shift = 0
  for (const line of lines) {
    if (pos < line.at) {
      break
    }
    if (pos <= line.at + line.removed) {
      return line.at + shift + line.inserted.length
    }
    shift += line.inserted.length - line.removed
  }
  return pos + shift
}

function togglePrefix(doc: string, sel: TextSelection, action: 'list' | 'checkbox'): FormatEdit | null {
  const backwards = sel.anchor > sel.head
  const from = Math.min(sel.anchor, sel.head)
  const to = Math.max(sel.anchor, sel.head)
  const blockStart = doc.lastIndexOf('\n', from - 1) + 1
  // A selection that ends at the very start of a line does not include that line.
  const lastPos = to > from && doc[to - 1] === '\n' ? to - 1 : to
  const newline = doc.indexOf('\n', lastPos)
  const blockEnd = newline === -1 ? doc.length : newline

  const rows: { start: number; indent: number; rest: string }[] = []
  let cursor = blockStart
  for (const text of doc.slice(blockStart, blockEnd).split('\n')) {
    const indent = /^[ \t]*/.exec(text)![0].length
    rows.push({ start: cursor, indent, rest: text.slice(indent) })
    cursor += text.length + 1
  }
  const filled = rows.filter((row) => row.rest.trim() !== '')
  const targets = filled.length > 0 ? filled : rows

  const kinds = targets.map((row) => prefixOf(row.rest).kind)
  const removing = kinds.every((kind) => (action === 'list' ? kind === 'bullet' : kind === 'checkbox'))

  const lines: LineEdit[] = []
  const rewritten = rows.map((row) => {
    if (!targets.includes(row)) {
      return doc.slice(row.start, row.start + row.indent + row.rest.length)
    }
    const { kind, text } = prefixOf(row.rest)
    let next: string
    if (removing) {
      next = ''
    } else if (action === 'list') {
      next = kind === 'bullet' ? text : '- '
    } else {
      next = kind === 'checkbox' ? text : '- [ ] '
    }
    if (next !== text) {
      lines.push({ at: row.start + row.indent, removed: text.length, inserted: next })
    }
    return doc.slice(row.start, row.start + row.indent) + next + row.rest.slice(text.length)
  })
  if (lines.length === 0) {
    return null
  }
  const insert = rewritten.join('\n')
  const start = mapThrough(from, lines)
  const end = mapThrough(to, lines)
  const [anchor, head] = directed(backwards, start, end)
  return edit(blockStart, blockEnd, insert, anchor, head)
}

// --- links ----------------------------------------------------------------------------------

function linkEdit(doc: string, sel: TextSelection): FormatEdit {
  const from = Math.min(sel.anchor, sel.head)
  const to = Math.max(sel.anchor, sel.head)
  const text = doc.slice(from, to)
  if (text === '') {
    return edit(from, to, '[]()', from + 1, from + 1)
  }
  if (isUrl(text.trim())) {
    return edit(from, to, `[](${text})`, from + 1, from + 1)
  }
  const caret = from + text.length + 3
  return edit(from, to, `[${text}]()`, caret, caret)
}

function wikilinkEdit(doc: string, sel: TextSelection): FormatEdit | null {
  const from = Math.min(sel.anchor, sel.head)
  const to = Math.max(sel.anchor, sel.head)
  const text = doc.slice(from, to)
  if (text === '') {
    return edit(from, to, '[[', from + 2, from + 2, true)
  }
  if (text.includes('\n')) {
    return null
  }
  if (text.length >= 4 && text.startsWith('[[') && text.endsWith(']]')) {
    const inner = text.slice(2, -2)
    return edit(from, to, inner, from, from + inner.length)
  }
  const caret = from + text.length + 4
  return edit(from, to, `[[${text}]]`, caret, caret)
}

/** What `action` does to `doc` at `sel`, or `null` for nothing. */
export function applyFormat(
  action: FormatAction,
  doc: string,
  sel: TextSelection,
): FormatEdit | null {
  switch (action) {
    case 'bold':
      return toggleMark(doc, sel, '**')
    case 'italic':
      return toggleMark(doc, sel, '*')
    case 'code':
      return toggleMark(doc, sel, '`')
    case 'list':
    case 'checkbox':
      return togglePrefix(doc, sel, action)
    case 'link':
      return linkEdit(doc, sel)
    case 'wikilink':
      return wikilinkEdit(doc, sel)
  }
}
