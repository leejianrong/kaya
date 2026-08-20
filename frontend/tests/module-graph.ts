/**
 * `src/`'s import graph, split by **what an edge costs at runtime** — the instrument the bundle
 * guards are written over.
 *
 * KAN-767 built this inside `tests/editor-chunk-is-lazy.test.ts` for one lazy chunk. KAN-836 added a
 * second (`lib/markdown.ts`, and the `@lezer/markdown` grammar behind it), and two copies of a
 * hundred-line AST scanner is two instruments that can drift apart while both look green. So it moved
 * here, verbatim, and each guard keeps its own positive controls — a shared instrument still needs
 * per-file proof that it reached the code that file is about.
 *
 * **Over parsed ASTs and never over the file's text**, and that is measured rather than fastidious:
 * `src/` contains a dozen prose mentions of `@codemirror` and `@lezer` that are comments *arguing*
 * about exactly these rules, and `tests/no-html-injection.test.ts` records the same file having to
 * move from grep to AST for the same reason. So `svelte/compiler` for components and `typescript` for
 * modules, and a comment cannot be mistaken for code either way.
 *
 * **Type-only imports are their own bucket and that is not a loophole.** `verbatimModuleSyntax` erases
 * `import type` and `import { type X }` completely, so they cost zero bytes and cannot pull a chunk
 * anywhere; `lib/editor.ts` legitimately has two CodeMirror ones, and both lazy modules are named as
 * `typeof import(…)` types by their consumers, which is erased the same way.
 */

import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

import { parse } from 'svelte/compiler'
import ts from 'typescript'

/** The tree every guard sweeps. */
export const SRC = fileURLToPath(new URL('../src', import.meta.url))

/** One file's module graph edges, split by what they cost at runtime. */
export interface Edges {
  /** Specifiers whose *values* are pulled in at module load: `import {x} from 's'`, `export … from`. */
  staticValue: string[]
  /** Specifiers imported type-only, which `verbatimModuleSyntax` erases. */
  staticType: string[]
  /** Specifiers reached through `import('s')`, i.e. a chunk boundary. */
  dynamic: string[]
}

export function sources(directory: string = SRC): string[] {
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

/** A `Literal`/`StringLiteral` node's text, or `null` if the specifier is computed. */
function literal(node: unknown): string | null {
  const candidate = node as Record<string, unknown> | null | undefined
  return typeof candidate?.value === 'string' ? candidate.value : null
}

/**
 * A component's script blocks, as ESTree.
 *
 * Svelte parses `lang="ts"` through `acorn-typescript`, which puts `importKind`/`exportKind` on the
 * declaration *and* on each specifier — so `import type {…}` and `import { type X }` are both
 * distinguishable here, and a dynamic import is an `ImportExpression` rather than a call.
 */
function scanSvelte(file: string): Edges {
  const root = parse(readFileSync(file, 'utf8'), { modern: true }) as unknown as Record<
    string,
    unknown
  >
  const edges: Edges = { staticValue: [], staticType: [], dynamic: [] }
  for (const node of [...walk(root.instance), ...walk(root.module)]) {
    const source = literal(node.source)
    if (source === null) {
      continue
    }
    if (node.type === 'ImportExpression') {
      edges.dynamic.push(source)
      continue
    }
    if (node.type === 'ImportDeclaration') {
      const specifiers = (node.specifiers ?? []) as Record<string, unknown>[]
      // A bare `import 's'` has no specifiers and is a value import: it runs the module.
      const value =
        node.importKind !== 'type' &&
        (specifiers.length === 0 ||
          specifiers.some((specifier) => specifier.importKind !== 'type'))
      ;(value ? edges.staticValue : edges.staticType).push(source)
      continue
    }
    if (node.type === 'ExportNamedDeclaration' || node.type === 'ExportAllDeclaration') {
      // A re-export is an import with a different name on it, and costs the same bytes.
      ;(node.exportKind === 'type' ? edges.staticType : edges.staticValue).push(source)
    }
  }
  return edges
}

function scanTypescript(file: string): Edges {
  const source = ts.createSourceFile(
    file,
    readFileSync(file, 'utf8'),
    ts.ScriptTarget.ESNext,
    true,
    ts.ScriptKind.TS,
  )
  const edges: Edges = { staticValue: [], staticType: [], dynamic: [] }
  const visit = (node: ts.Node): void => {
    if (
      ts.isCallExpression(node) &&
      node.expression.kind === ts.SyntaxKind.ImportKeyword &&
      node.arguments.length > 0 &&
      ts.isStringLiteral(node.arguments[0])
    ) {
      edges.dynamic.push(node.arguments[0].text)
    }
    if (ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier)) {
      const clause = node.importClause
      const named = clause?.namedBindings
      const value =
        clause === undefined ||
        (!clause.isTypeOnly &&
          (clause.name !== undefined ||
            named === undefined ||
            !ts.isNamedImports(named) ||
            named.elements.some((element) => !element.isTypeOnly)))
      edges[value ? 'staticValue' : 'staticType'].push(node.moduleSpecifier.text)
    }
    if (
      ts.isExportDeclaration(node) &&
      node.moduleSpecifier !== undefined &&
      ts.isStringLiteral(node.moduleSpecifier)
    ) {
      edges[node.isTypeOnly ? 'staticType' : 'staticValue'].push(node.moduleSpecifier.text)
    }
    ts.forEachChild(node, visit)
  }
  ts.forEachChild(source, visit)
  return edges
}

export function scan(file: string): Edges {
  return file.endsWith('.svelte') ? scanSvelte(file) : scanTypescript(file)
}

/** Every file under `src/`, keyed by its path relative to `src/`. */
export function moduleGraph(): Map<string, Edges> {
  return new Map(sources().map((file) => [relative(SRC, file), scan(file)]))
}

/**
 * The one shape a lazy-chunk guard needs: nothing but `owner` value-imports `pkg`, and nothing
 * static-imports `owner`'s module — reported as two lists of named offenders rather than as two
 * booleans, because a guard whose failure does not say *which file* sends the next reader to a grep.
 */
export interface ChunkEdges {
  /** `file: import 'specifier'` for every value import of a matched package outside `owner`. */
  packageOffenders: string[]
  /** `file: import 'specifier'` for every *static* import of the lazy module itself. */
  staticImporters: string[]
  /** `file: import('specifier')` for every dynamic import of the lazy module. */
  lazyImporters: string[]
}

export function chunkEdges(
  graph: Map<string, Edges>,
  options: { owner: string; pkg: RegExp; specifier: RegExp },
): ChunkEdges {
  return {
    packageOffenders: Array.from(graph)
      .filter(([file]) => file !== options.owner)
      .flatMap(([file, edges]) =>
        edges.staticValue.filter((s) => options.pkg.test(s)).map((s) => `${file}: import '${s}'`),
      ),
    staticImporters: Array.from(graph).flatMap(([file, edges]) =>
      edges.staticValue
        .filter((s) => options.specifier.test(s))
        .map((s) => `${file}: import '${s}'`),
    ),
    lazyImporters: Array.from(graph).flatMap(([file, edges]) =>
      edges.dynamic.filter((s) => options.specifier.test(s)).map((s) => `${file}: import('${s}')`),
    ),
  }
}
