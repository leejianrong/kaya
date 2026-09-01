/**
 * The structural half of KAN-554's XSS defence: **no HTML string is ever built from note content.**
 *
 * `tests/markdown.test.ts` proves the renderer's output is inert for a battery of payloads. This
 * proves the *shape* of the code that produced it, over the whole `src/` tree, which is the stronger
 * of the two claims: a payload test refuses the payloads someone wrote down, and this refuses the
 * construct that makes any payload possible in the first place.
 *
 * The repo already prefers this shape three times over, for the same reason —
 * `kaya-cli/tests/test_no_prompting.py` asserts over an AST rather than over behaviour,
 * `test_bare_invocation.py` counts `render` call sites, and `tests/editor-container.test.ts` parses a
 * component to assert an element has no children. A structural claim wants a structural check.
 *
 * **Over parsed ASTs and never over the file's text**, and that is not fastidiousness — the first
 * version of this file grepped, and it went red on four docstrings that *warn against* `{@html}`,
 * including one in `EditorPane.svelte` and one in this card's own renderer. A grep would have to be
 * weakened with exemptions until it stopped meaning anything, and the same weakening is what would
 * let a real sink through on a line that also contains a URL. So: `svelte/compiler` for the
 * templates, `typescript` for the scripts, and a comment cannot be mistaken for code either way.
 *
 * If this is red, do **not** add an exemption. Svelte does not escape `{@html}` — that is its entire
 * purpose — and `innerHTML` does not either. KAN-555 chose `sessionStorage` over `localStorage`
 * *because* this app renders user-controlled markdown in the same origin as a live pandan PAT, so the
 * cost of one of these appearing is a credential, not a layout bug. Build DOM nodes:
 * `lib/markdown.ts` shows the pattern, and its header explains why there is no escaping function to
 * get wrong.
 */

import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

import { parse } from 'svelte/compiler'
import ts from 'typescript'
import { describe, expect, it } from 'vitest'

const SRC = fileURLToPath(new URL('../src', import.meta.url))

/**
 * Every writable-markup sink in a browser. Each one parses a string as HTML.
 *
 * `{@html}` is not here because it is not a member name — it is a template node type, checked
 * separately below.
 */
const SINKS = new Set([
  'innerHTML',
  'outerHTML',
  'insertAdjacentHTML',
  'write',
  'writeln',
  'createContextualFragment',
])

/** Svelte's `{@html …}`, as its parsed node type. */
const HTML_TAG = 'HtmlTag'

function sources(directory: string): string[] {
  return readdirSync(directory)
    .flatMap((entry) => {
      const full = join(directory, entry)
      if (statSync(full).isDirectory()) {
        return sources(full)
      }
      return /\.(svelte|ts)$/.test(entry) ? [full] : []
    })
    .sort()
}

/** Every node in a parsed tree, depth first. `parent` is skipped or the walk never terminates. */
function* walk(node: unknown): Generator<Record<string, unknown>> {
  if (node === null || typeof node !== 'object') {
    return
  }
  if (Array.isArray(node)) {
    for (const item of node) {
      yield* walk(item)
    }
    return
  }
  const candidate = node as Record<string, unknown>
  if (typeof candidate.type === 'string') {
    yield candidate
  }
  for (const [key, value] of Object.entries(candidate)) {
    if (key === 'parent' || key === 'leadingComments' || key === 'trailingComments') {
      continue
    }
    yield* walk(value)
  }
}

/** The member names an ESTree tree reads or writes: `a.b` → `b`, `a['b']` → `b`. */
function estreeMembers(tree: unknown): string[] {
  const names: string[] = []
  for (const node of walk(tree)) {
    if (node.type !== 'MemberExpression') {
      continue
    }
    const property = node.property as Record<string, unknown> | undefined
    if (typeof property?.name === 'string') {
      names.push(property.name)
    }
    if (typeof property?.value === 'string') {
      names.push(property.value)
    }
  }
  return names
}

interface Scan {
  /** Member names touched anywhere in the file's code. */
  members: string[]
  /** `{@html}` occurrences in the file's template. */
  htmlTags: number
}

function scanSvelte(file: string): Scan {
  const root = parse(readFileSync(file, 'utf8'), { modern: true }) as unknown as Record<
    string,
    unknown
  >
  const htmlTags = Array.from(walk(root.fragment)).filter((node) => node.type === HTML_TAG).length
  return { members: [...estreeMembers(root.instance), ...estreeMembers(root.module)], htmlTags }
}

function scanTypescript(file: string): Scan {
  const source = ts.createSourceFile(
    file,
    readFileSync(file, 'utf8'),
    ts.ScriptTarget.ESNext,
    true,
    ts.ScriptKind.TS,
  )
  const members: string[] = []
  const visit = (node: ts.Node): void => {
    if (ts.isPropertyAccessExpression(node)) {
      members.push(node.name.text)
    }
    if (ts.isElementAccessExpression(node) && ts.isStringLiteral(node.argumentExpression)) {
      members.push(node.argumentExpression.text)
    }
    ts.forEachChild(node, visit)
  }
  ts.forEachChild(source, visit)
  return { members, htmlTags: 0 }
}

function scan(file: string): Scan {
  return file.endsWith('.svelte') ? scanSvelte(file) : scanTypescript(file)
}

function tsSource(relativePath: string): ts.SourceFile {
  const file = join(SRC, relativePath)
  return ts.createSourceFile(
    file,
    readFileSync(file, 'utf8'),
    ts.ScriptTarget.ESNext,
    true,
    ts.ScriptKind.TS,
  )
}

/** Every call whose callee is a member named `name`, e.g. every `document.createElement(…)`. */
function callsTo(source: ts.SourceFile, name: string): ts.CallExpression[] {
  const found: ts.CallExpression[] = []
  const visit = (node: ts.Node): void => {
    if (
      ts.isCallExpression(node) &&
      ts.isPropertyAccessExpression(node.expression) &&
      node.expression.name.text === name
    ) {
      found.push(node)
    }
    ts.forEachChild(node, visit)
  }
  ts.forEachChild(source, visit)
  return found
}

describe('nothing in the SPA turns a string into markup', () => {
  const files = sources(SRC)

  it('finds and parses source files at all, so an empty sweep cannot pass', () => {
    // Without this, a broken `sources()` or a parser that returned nothing would make every
    // assertion below vacuously true — the same failure mode `tests/shell.test.ts` guards against by
    // asserting the editor container is *non*-empty before asserting what is not in it.
    expect(files.length).toBeGreaterThan(8)
    expect(files.some((file) => file.endsWith('lib/markdown.ts'))).toBe(true)
    expect(files.some((file) => file.endsWith('PreviewPane.svelte'))).toBe(true)

    // The parsers reach real code: a name only present in a script block, and one only in a template.
    expect(scan(join(SRC, 'lib/markdown.ts')).members).toContain('createTextNode')
    expect(scan(join(SRC, 'components/PreviewPane.svelte')).members).toContain('replaceChildren')
  })

  it('contains no `{@html}` in any component template', () => {
    const offenders = files
      .filter((file) => file.endsWith('.svelte'))
      .map((file) => ({ file: relative(SRC, file), tags: scanSvelte(file).htmlTags }))
      .filter((entry) => entry.tags > 0)

    expect(offenders).toEqual([])
  })

  it('writes to no markup sink anywhere in `src/`', () => {
    // One assertion over every file and every sink, so the failure names both.
    const offenders = files.flatMap((file) =>
      scan(file)
        .members.filter((member) => SINKS.has(member))
        .map((member) => `${relative(SRC, file)}: .${member}`),
    )

    expect(offenders).toEqual([])
  })
})

describe('the renderer builds DOM the only safe way there is', () => {
  const renderer = tsSource('lib/markdown.ts')

  it('creates every element through one `createElement` call, so a tag name is always a literal', () => {
    // The positive half. The sweeps above say what is absent; this says the renderer really does use
    // the safe constructors — and *once each*, which is what makes "a tag name never comes from the
    // source" checkable: there is exactly one call, its argument is a parameter, and every argument
    // passed to that parameter is a string literal in the file.
    expect(callsTo(renderer, 'createElement')).toHaveLength(1)
    expect(callsTo(renderer, 'createTextNode')).toHaveLength(1)
  })

  it('passes only literal attribute names to `setAttribute`', () => {
    // `setAttribute` is the one place a source-derived *value* lands in the DOM. Every name passed to
    // it has to be a literal here: a computed name is how `'on' + 'error'` becomes an event handler.
    //
    // The pattern allows one internal hyphen group (`data-board`, KAN-1049's embed markers) on top
    // of the plain lowercase names every earlier attribute used (`href`, `rel`, …) — widened, not
    // loosened: it is still exactly one `ts.isStringLiteral` literal per call, so a name built from
    // a template string or a concatenation still fails this the same way it always did.
    const calls = callsTo(renderer, 'setAttribute')

    expect(calls.length).toBeGreaterThan(4)
    for (const call of calls) {
      const [name] = call.arguments
      expect(ts.isStringLiteral(name) && /^[a-z]+(-[a-z]+)*$/.test(name.text)).toBe(true)
    }
  })
})
