/**
 * Markdown → DOM, for KAN-554's live preview.
 *
 * ## Why this is presentation and not shaping
 *
 * `api.ts`'s header draws the line: shaping decides *which bytes a caller receives*, presentation
 * decides *what a person sees of the bytes they already have*. This module is the second, so it does
 * not need permission from ADR 0004 to exist — and it is also the reason ADR 0004's rules do not
 * loosen here. Nothing below narrows a record, cuts prose or counts anything.
 *
 * ## Why there is no markdown-to-HTML dependency
 *
 * `@lezer/markdown` is **already in the bundle**: `@codemirror/lang-markdown` imports
 * `{ parser, GFM, Subscript, Superscript, Emoji }` from it to build `markdownLanguage`, which
 * `EditorPane.svelte` mounts. So the parser below is the same module object the editor is already
 * highlighting with, and reusing it costs **zero new bytes**. Measured alternatives, esbuild,
 * minified, `gzip -9` (KAN-554's PR body has the table): `marked` alone 42,796 B / 12,982 B gzip;
 * `marked` + `DOMPurify` 72,171 / 24,069; `markdown-it` + `DOMPurify` 142,747 / 59,002. A sanitiser
 * is not optional for any of them, because they all produce an HTML *string* from note content.
 *
 * The configuration is `[GFM, Subscript, Superscript, Emoji]`, which is exactly what
 * `@codemirror/lang-markdown`'s `markdownLanguage` configures. That is deliberate: the preview then
 * parses precisely the grammar the editor highlights, so the two cannot disagree about what a
 * construct *is*. A preview on plain CommonMark beside a GFM-highlighting editor is a divergence
 * waiting to be reported as a bug.
 *
 * ## Why it returns a `DocumentFragment` and never a string
 *
 * This is the one place in kaya where an attacker's bytes are rendered as markup, and it is the
 * reason KAN-555 put the credential in `sessionStorage` rather than `localStorage`. So the escaping
 * is not a function that could have a bug — **there is no escaping at all**, because no string
 * containing markup is ever built:
 *
 * - Every element is `document.createElement(<a literal in this file>)`. A tag name never comes from
 *   the source.
 * - Every piece of source text becomes a `Text` node. The DOM cannot interpret a `Text` node as
 *   markup, so `<script>` in a note body is four visible characters and a tag name that never
 *   existed.
 * - Every attribute *name* is a literal in this file. The only source-derived attribute *value* is a
 *   URL, and it goes through {@link safeUrl} first.
 *
 * Raw HTML in the source (`HTMLBlock`, `HTMLTag`, `Comment`, …) is rendered **as visible text**, not
 * dropped and not interpreted. Dropping it would lose content silently; interpreting it is the whole
 * vulnerability. `tests/markdown.test.ts` asserts the *property* — over a battery of payloads, every
 * element in the output has an allow-listed tag name, every attribute an allow-listed name, and no
 * attribute value carries a dangerous scheme — rather than one symptom per payload.
 *
 * `tests/no-html-injection.test.ts` adds the structural half: no `{@html}` anywhere in `src/`, and no
 * `innerHTML`-family write in this file.
 *
 * ## Known limitations, on purpose
 *
 * No syntax highlighting inside fenced code (nothing asks for it, and it would drag
 * `@codemirror/lang-*` grammars in). No `title` attribute from a link's `LinkTitle` — one fewer
 * source-derived attribute for no real loss. No emoji shortcode table, so `:smile:` stays literal.
 * Wikilinks are KAN-567.
 */

import type { SyntaxNode, Tree } from '@lezer/common'
import { Emoji, GFM, parser as commonmark, Subscript, Superscript } from '@lezer/markdown'

/**
 * The grammar. Same extensions as `@codemirror/lang-markdown`'s `markdownLanguage`, so the preview
 * and the editor's highlighting are parsing the same language.
 */
const MARKDOWN = commonmark.configure([GFM, Subscript, Superscript, Emoji])

/**
 * Schemes a rendered `href`/`src` may carry.
 *
 * An allow-list rather than a `javascript:` deny-list, for the reason `truncation.py` gives about
 * allow-lists in `kaya-client`: a deny-list is a list of the attacks someone thought of, and
 * `vbscript:`, `data:text/html`, and whatever the next one is are not on it. `data:` is excluded even
 * though it is often harmless, because `data:text/html` is a same-origin-ish document and telling the
 * two apart means parsing a MIME type.
 */
const SAFE_SCHEMES = new Set(['http:', 'https:', 'mailto:'])

/** Heading node → tag. Setext headings are `h1`/`h2` by definition. */
const HEADINGS: Record<string, string> = {
  ATXHeading1: 'h1',
  ATXHeading2: 'h2',
  ATXHeading3: 'h3',
  ATXHeading4: 'h4',
  ATXHeading5: 'h5',
  ATXHeading6: 'h6',
  SetextHeading1: 'h1',
  SetextHeading2: 'h2',
}

/** Inline wrappers that are one element around their own inline content. */
const INLINE_WRAPPERS: Record<string, string> = {
  Emphasis: 'em',
  StrongEmphasis: 'strong',
  Strikethrough: 'del',
  Subscript: 'sub',
  Superscript: 'sup',
}

/**
 * Nodes that contribute **no output of their own**, because a parent already accounted for them.
 *
 * An explicit set rather than a `name.endsWith('Mark')` rule. The rule would be shorter and would
 * silently start hiding content the day an extension adds a node whose name happens to end that way;
 * the failure mode of the set is the opposite and safer — an unlisted node falls through to
 * {@link inlineInto}'s default and its text appears verbatim, which is visible rather than lost.
 */
const STRUCTURAL = new Set([
  'HeaderMark',
  'QuoteMark',
  'ListMark',
  'LinkMark',
  'EmphasisMark',
  'StrikethroughMark',
  'SubscriptMark',
  'SuperscriptMark',
  'CodeMark',
  'CodeInfo',
  'CodeText',
  'LinkTitle',
  'LinkLabel',
  'TableDelimiter',
  'TaskMarker',
  // A link's target is rendered by the link, not beside it.
  'URL',
])

/** Raw source that is shown as text rather than interpreted. See the header. */
const RAW_SOURCE = new Set([
  'HTMLBlock',
  'HTMLTag',
  'Comment',
  'CommentBlock',
  'ProcessingInstruction',
  'ProcessingInstructionBlock',
])

/**
 * The named character references worth decoding, plus numeric ones in {@link decodeEntity}.
 *
 * Decoding is safe *because* the result goes into a `Text` node: `&lt;script&gt;` decodes to a string
 * starting with `<`, and a `Text` node holding `<` is one visible character. There is no path from
 * here to markup, so the decoder cannot be an injection bug — only a wrong-glyph bug.
 */
const NAMED_ENTITIES: Record<string, string> = {
  amp: '&',
  apos: "'",
  copy: '©',
  gt: '>',
  hellip: '…',
  lt: '<',
  mdash: '—',
  ndash: '–',
  nbsp: ' ',
  quot: '"',
  reg: '®',
  trade: '™',
}

/**
 * A URL fit to put in an attribute, or `null` if it is not one.
 *
 * Parsed **absolutely**, with no base: a relative or fragment-only target has no meaning in a
 * preview until there is a resolver for it (wikilinks are KAN-567), so it comes back `null` and the
 * caller renders the source as text instead of inventing a destination.
 *
 * The control-character rejection happens *before* parsing and is the load-bearing part. `new URL()`
 * strips tab, newline and carriage return from its input per the URL spec, so `java&#9;script:x`
 * parses as `javascript:x` — a scheme the allow-list would then judge correctly, but only by
 * accident of ordering. Rejecting the bytes outright means the sanitiser never has to reason about
 * what a parser silently removed.
 *
 * Returns `parsed.href`, not the input. Whatever reaches the attribute is the exact string the
 * allow-list judged, so there is no gap between the decision and the value.
 */
export function safeUrl(raw: string): string | null {
  const trimmed = raw.trim()
  if (trimmed === '') {
    return null
  }
  // Every C0 control, space and DEL. A character scan rather than a character-class regex: the class
  // needs literal control characters in the source, which `no-control-regex` refuses and a reader
  // cannot see anyway.
  for (const character of trimmed) {
    const code = character.codePointAt(0) ?? 0
    if (code <= 0x20 || code === 0x7f) {
      return null
    }
  }
  let parsed: URL
  try {
    parsed = new URL(trimmed)
  } catch {
    return null
  }
  return SAFE_SCHEMES.has(parsed.protocol) ? parsed.href : null
}

/**
 * Render markdown as DOM nodes.
 *
 * A `DocumentFragment` rather than a string, and that is the security property rather than a style
 * choice — see the module header. Needs a `document`, so callers in a node test environment want
 * `// @vitest-environment jsdom`.
 */
export function renderMarkdown(source: string): DocumentFragment {
  const fragment = document.createDocumentFragment()
  const tree: Tree = MARKDOWN.parse(source)
  const links = definitions(tree, source)
  const context: Context = { source, links }

  for (const child of childrenOf(tree.topNode)) {
    blockInto(child, context, fragment)
  }
  return fragment
}

interface Context {
  readonly source: string
  /** Reference-link definitions, normalised label → raw target. */
  readonly links: Map<string, string>
}

/**
 * `[label]: url` definitions, collected before anything renders.
 *
 * CommonMark does not render a definition block, so it is dropped from the output — but a
 * `[text][label]` link elsewhere in the document needs it, and rendering that link as plain text when
 * its target is right there in the note is a fidelity loss with no argument behind it.
 */
function definitions(tree: Tree, source: string): Map<string, string> {
  const found = new Map<string, string>()
  for (const node of childrenOf(tree.topNode)) {
    if (node.name !== 'LinkReference') {
      continue
    }
    const label = node.getChild('LinkLabel')
    const url = node.getChild('URL')
    if (label === null || url === null) {
      continue
    }
    const key = normalizeLabel(source.slice(label.from, label.to))
    // First definition wins, which is CommonMark's rule for a duplicated label.
    if (!found.has(key)) {
      found.set(key, source.slice(url.from, url.to))
    }
  }
  return found
}

/** CommonMark label matching: brackets off, whitespace collapsed, case folded. */
function normalizeLabel(raw: string): string {
  return raw.replace(/^\[/, '').replace(/\]$/, '').trim().replace(/\s+/g, ' ').toLowerCase()
}

function childrenOf(node: SyntaxNode): SyntaxNode[] {
  const found: SyntaxNode[] = []
  for (let child = node.firstChild; child !== null; child = child.nextSibling) {
    found.push(child)
  }
  return found
}

/** `document.createElement` with the tag name coming from this file and nowhere else. */
function element(tag: string): HTMLElement {
  return document.createElement(tag)
}

/** Source text as a `Text` node. The only way source bytes reach the output. */
function textNode(value: string): Text {
  return document.createTextNode(value)
}

/** Drop insignificant whitespace at an element's two ends. Headings only — see the call site. */
function trimEdges(el: HTMLElement): void {
  const first = el.firstChild
  if (first !== null && first.nodeType === 3) {
    first.textContent = (first.textContent ?? '').replace(/^\s+/, '')
  }
  const last = el.lastChild
  if (last !== null && last.nodeType === 3) {
    last.textContent = (last.textContent ?? '').replace(/\s+$/, '')
  }
}

// --- Blocks -------------------------------------------------------------------------------------

function blockInto(node: SyntaxNode, context: Context, into: ParentNode): void {
  const { source } = context
  const name = node.name

  const heading = HEADINGS[name]
  if (heading !== undefined) {
    const el = element(heading)
    inlineInto(node, context, el)
    // A heading is the one block whose marks sit *inside* its own range on both sides — `## x` leaves
    // the space after the hashes, and a setext heading leaves the newline before its underline. HTML
    // would collapse both, but a heading is also the thing anything reading `textContent` looks at.
    trimEdges(el)
    into.append(el)
    return
  }

  if (RAW_SOURCE.has(name)) {
    into.append(rawSourceBlock(source.slice(node.from, node.to)))
    return
  }

  switch (name) {
    case 'Paragraph': {
      const el = element('p')
      inlineInto(node, context, el)
      into.append(el)
      return
    }
    case 'BulletList':
    case 'OrderedList': {
      into.append(listElement(node, context))
      return
    }
    case 'ListItem': {
      const el = element('li')
      for (const child of childrenOf(node)) {
        if (STRUCTURAL.has(child.name)) {
          continue
        }
        blockInto(child, context, el)
      }
      into.append(el)
      return
    }
    case 'Task': {
      // A GFM task item's content, with the checkbox as a real disabled input. `checked` is set from
      // the marker's own text, never from an attribute in the source.
      const el = element('p')
      el.className = 'task'
      const box = element('input') as HTMLInputElement
      box.type = 'checkbox'
      box.disabled = true
      const marker = node.getChild('TaskMarker')
      box.checked = marker !== null && /\[[xX]\]/.test(source.slice(marker.from, marker.to))
      el.append(box)
      inlineInto(node, context, el)
      into.append(el)
      return
    }
    case 'Blockquote': {
      const el = element('blockquote')
      for (const child of childrenOf(node)) {
        if (STRUCTURAL.has(child.name)) {
          continue
        }
        blockInto(child, context, el)
      }
      into.append(el)
      return
    }
    case 'FencedCode':
    case 'CodeBlock': {
      const pre = element('pre')
      const code = element('code')
      // Every `CodeText` run, concatenated. More than one appears when the block sits inside a
      // blockquote or a list item, where the parser splits it around the continuation marks.
      const parts = childrenOf(node)
        .filter((child) => child.name === 'CodeText')
        .map((child) => source.slice(child.from, child.to))
      code.append(textNode(parts.join('')))
      pre.append(code)
      into.append(pre)
      return
    }
    case 'HorizontalRule': {
      into.append(element('hr'))
      return
    }
    case 'Table': {
      into.append(tableElement(node, context))
      return
    }
    case 'LinkReference': {
      // Collected by `definitions()` and not rendered, as CommonMark specifies.
      return
    }
    default: {
      if (STRUCTURAL.has(name)) {
        return
      }
      // An unknown block still has to appear. A paragraph of its inline content is the safe default:
      // known descendants render, and anything else falls through to text.
      const el = element('p')
      inlineInto(node, context, el)
      into.append(el)
    }
  }
}

/**
 * Raw HTML from the source, as a visible block of text.
 *
 * `<pre>` because the bytes are shown verbatim, and a class so `PreviewPane.svelte` can label it. The
 * content goes in as a `Text` node, which is what makes `<script>alert(1)</script>` in a note body a
 * string of characters rather than a script element.
 */
function rawSourceBlock(raw: string): HTMLElement {
  const pre = element('pre')
  pre.className = 'raw-html'
  pre.append(textNode(raw))
  return pre
}

function listElement(node: SyntaxNode, context: Context): HTMLElement {
  const ordered = node.name === 'OrderedList'
  const el = element(ordered ? 'ol' : 'ul')
  if (ordered) {
    const first = node.firstChild?.getChild('ListMark') ?? null
    const number =
      first === null ? Number.NaN : Number.parseInt(context.source.slice(first.from, first.to), 10)
    // `1` is the default, so only a list that actually starts elsewhere gets an attribute.
    if (Number.isFinite(number) && number !== 1) {
      el.setAttribute('start', String(number))
    }
  }
  for (const child of childrenOf(node)) {
    if (child.name !== 'ListItem') {
      continue
    }
    blockInto(child, context, el)
  }
  return el
}

function tableElement(node: SyntaxNode, context: Context): HTMLElement {
  const table = element('table')
  for (const child of childrenOf(node)) {
    if (child.name === 'TableHeader') {
      const head = element('thead')
      head.append(tableRow(child, context, 'th'))
      table.append(head)
      continue
    }
    if (child.name === 'TableRow') {
      let body = table.querySelector(':scope > tbody')
      if (body === null) {
        body = element('tbody')
        table.append(body)
      }
      body.append(tableRow(child, context, 'td'))
    }
  }
  return table
}

function tableRow(node: SyntaxNode, context: Context, cellTag: 'th' | 'td'): HTMLElement {
  const row = element('tr')
  for (const child of childrenOf(node)) {
    if (child.name !== 'TableCell') {
      continue
    }
    const cell = element(cellTag)
    inlineInto(child, context, cell)
    row.append(cell)
  }
  return row
}

// --- Inline -------------------------------------------------------------------------------------

/**
 * Render `node`'s inline content into `into`, over the range `[from, to)`.
 *
 * The gap-filling loop is the heart of the renderer: every byte in the range either belongs to a
 * child — which handles it, or is `STRUCTURAL` and drops it — or is emitted as a `Text` node. So a
 * construct nobody wrote a case for still shows its source rather than disappearing, and no byte can
 * become markup on the way.
 *
 * `from`/`to` are parameters because a `Link`'s label is a *sub-range* of the link node: the target
 * and the brackets are inside `node` too and must not appear in the anchor's text.
 */
function inlineInto(
  node: SyntaxNode,
  context: Context,
  into: ParentNode,
  from: number = node.from,
  to: number = node.to,
): void {
  const { source } = context
  let cursor = from

  for (const child of childrenOf(node)) {
    if (child.to <= from || child.from >= to) {
      continue
    }
    if (child.from > cursor) {
      into.append(textNode(source.slice(cursor, child.from)))
    }
    inlineNodeInto(child, context, into)
    cursor = Math.max(cursor, child.to)
  }

  if (cursor < to) {
    into.append(textNode(source.slice(cursor, to)))
  }
}

function inlineNodeInto(node: SyntaxNode, context: Context, into: ParentNode): void {
  const { source } = context
  const name = node.name

  if (STRUCTURAL.has(name)) {
    return
  }

  if (RAW_SOURCE.has(name)) {
    // Inline raw HTML, as visible text. `<b>` shows as four characters; so does `<img onerror=…>`.
    into.append(textNode(source.slice(node.from, node.to)))
    return
  }

  const wrapper = INLINE_WRAPPERS[name]
  if (wrapper !== undefined) {
    const el = element(wrapper)
    inlineInto(node, context, el)
    into.append(el)
    return
  }

  switch (name) {
    case 'InlineCode': {
      // The `CodeMark` children are structural, so the gaps between them are exactly the code.
      const el = element('code')
      inlineInto(node, context, el)
      into.append(el)
      return
    }
    case 'Escape': {
      // `\*` is one escaped character, and the character is what the reader asked for.
      into.append(textNode(source.slice(node.from + 1, node.to)))
      return
    }
    case 'Entity': {
      into.append(textNode(decodeEntity(source.slice(node.from, node.to))))
      return
    }
    case 'HardBreak': {
      into.append(element('br'))
      return
    }
    case 'Link': {
      linkInto(node, context, into)
      return
    }
    case 'Autolink': {
      const url = node.getChild('URL')
      const raw = url === null ? '' : source.slice(url.from, url.to)
      const href = safeUrl(raw)
      if (href === null) {
        into.append(textNode(source.slice(node.from, node.to)))
        return
      }
      into.append(anchor(href, [textNode(raw)]))
      return
    }
    case 'Image': {
      imageInto(node, context, into)
      return
    }
    default: {
      // Unknown, and therefore shown: recurse so any known descendant still renders, and the rest
      // arrives as text. `Emoji` (`:smile:`) lands here on purpose — there is no shortcode table.
      inlineInto(node, context, into)
    }
  }
}

/**
 * A link, inline or reference, or its label as plain text when there is no destination this renderer
 * will emit.
 *
 * The label is the range between the first two `LinkMark`s, which is why {@link inlineInto} takes a
 * sub-range: `[**bold**](https://x)` must produce `<strong>` inside the anchor and must not leak the
 * URL into the anchor's text.
 */
function linkInto(node: SyntaxNode, context: Context, into: ParentNode): void {
  const marks = childrenOf(node).filter((child) => child.name === 'LinkMark')
  const labelFrom = marks[0]?.to ?? node.from
  const labelTo = marks[1]?.from ?? node.to

  const href = safeUrl(target(node, context))
  if (href === null) {
    // No destination, or one this renderer refuses. The words stay; the link does not.
    inlineInto(node, context, into, labelFrom, labelTo)
    return
  }

  const el = anchor(href, [])
  inlineInto(node, context, el, labelFrom, labelTo)
  // A link whose label was empty would otherwise be an invisible anchor.
  if (el.childNodes.length === 0) {
    el.append(textNode(href))
  }
  into.append(el)
}

/** A link's raw target: inline `(url)`, or the definition a `[text][label]` reference names. */
function target(node: SyntaxNode, context: Context): string {
  const { source, links } = context
  const url = node.getChild('URL')
  if (url !== null) {
    return source.slice(url.from, url.to)
  }
  const label = node.getChild('LinkLabel')
  const marks = childrenOf(node).filter((child) => child.name === 'LinkMark')
  // `[text][label]` names its definition; `[label]` is its own.
  const key =
    label === null
      ? source.slice(marks[0]?.to ?? node.from, marks[1]?.from ?? node.to)
      : source.slice(label.from, label.to)
  return links.get(normalizeLabel(key)) ?? ''
}

/**
 * An `<a>` with the three attributes this renderer sets, and no others.
 *
 * `target="_blank"` because the editor beside the preview may hold unsaved work, and a same-tab
 * navigation out of a note you are writing loses it — the browser's back button does not restore an
 * unsaved CodeMirror document.
 *
 * `rel="noopener noreferrer"` is the price of that, and it is not optional here. `noopener` denies
 * the opened page a `window.opener` handle back into kaya's origin, which is the origin holding a
 * live pandan PAT in `sessionStorage` (KAN-555). `noreferrer` keeps the note's URL — which contains
 * a `NOTE-n` ref — out of the destination's referrer log.
 */
function anchor(href: string, content: Node[]): HTMLElement {
  const el = element('a')
  el.setAttribute('href', href)
  el.setAttribute('target', '_blank')
  el.setAttribute('rel', 'noopener noreferrer')
  el.append(...content)
  return el
}

function imageInto(node: SyntaxNode, context: Context, into: ParentNode): void {
  const { source } = context
  const src = safeUrl(target(node, context))
  if (src === null) {
    // Including a `javascript:` or `data:` src: the source line shows instead, so nothing is hidden.
    into.append(textNode(source.slice(node.from, node.to)))
    return
  }
  const marks = childrenOf(node).filter((child) => child.name === 'LinkMark')
  const alt = source.slice(marks[0]?.to ?? node.from, marks[1]?.from ?? node.to)

  const el = element('img') as HTMLImageElement
  el.setAttribute('src', src)
  el.setAttribute('alt', alt)
  el.setAttribute('loading', 'lazy')
  // The preview's origin holds a credential, and an `<img>` is an outbound GET the reader did not
  // ask to make. `no-referrer` keeps the note's URL out of the image host's logs.
  el.setAttribute('referrerpolicy', 'no-referrer')
  into.append(el)
}

/**
 * `&amp;` → `&`. Unknown references come back verbatim, which is what the browser does too.
 *
 * Safe by construction: the caller puts the result in a `Text` node. See {@link NAMED_ENTITIES}.
 */
function decodeEntity(raw: string): string {
  const numeric = /^&#(x[0-9a-f]+|[0-9]+);$/i.exec(raw)
  if (numeric !== null) {
    const digits = numeric[1]
    const code =
      digits.startsWith('x') || digits.startsWith('X')
        ? Number.parseInt(digits.slice(1), 16)
        : Number.parseInt(digits, 10)
    // Surrogates and out-of-range code points would throw; a lone NUL is not worth emitting.
    if (Number.isFinite(code) && code > 0 && code <= 0x10ffff && (code < 0xd800 || code > 0xdfff)) {
      return String.fromCodePoint(code)
    }
    return raw
  }
  const named = /^&([a-z][a-z0-9]*);$/i.exec(raw)
  if (named !== null) {
    return NAMED_ENTITIES[named[1].toLowerCase()] ?? raw
  }
  return raw
}
