/**
 * **A bundle guard, not a style rule** (KAN-767). It exists because the regression it catches is
 * silent in every other way.
 *
 * CodeMirror is ~80 KB gzip and it lives behind one dynamic `import()`, so an unauthenticated visitor
 * on KAN-555's landing page — who may not even have an account yet, and whose next action is pasting
 * a live pandan PAT into a password field — does not download a markdown grammar, a view layer and an
 * undo history first. That property is held up by two lines of code and nothing else: the `import()`
 * in `EditorPane.svelte`'s loader effect, and `lib/codemirror.ts` being the only file that names a
 * `@codemirror/*` value.
 *
 * Break either one and **every test in this suite still passes**. `import { EditorView } from
 * '@codemirror/view'` at the top of any file in `src/` re-merges the chunk; so does turning the
 * `import()` into a static import. The app works perfectly either way — it is only bigger, and the
 * only witness is the bundle table in `frontend/README.md`, which nobody re-measures while working on
 * an unrelated card. So the witness is here instead.
 *
 * **Over parsed ASTs and never over the file's text.** A grep is not an option and that is measured
 * rather than guessed: there are five prose mentions of `@codemirror` in `src/` that are comments
 * arguing about exactly this — two in `lib/editor.ts`'s header, one in `lib/codemirror.ts`, one in
 * `EditorPane.svelte` and two in `lib/markdown.ts` — and `tests/no-html-injection.test.ts` records the
 * same file having to move from grep to AST for the same reason. So `svelte/compiler` for components
 * and `typescript` for modules, and a comment cannot be mistaken for code either way. The scanner
 * itself now lives in `tests/module-graph.ts`, because KAN-836 added a second lazy chunk and two copies
 * of it would be two instruments that can drift apart while both look green; the positive controls
 * stayed here, since a shared instrument still needs per-guard proof that it reached the code *this*
 * guard is about.
 *
 * **Type-only imports are allowed everywhere and are not a loophole.** `verbatimModuleSyntax` erases
 * `import type` and `import { type X }` completely, so they cost zero bytes and cannot pull a chunk
 * anywhere; `lib/editor.ts` legitimately has two, which is what lets its guards be tested in vitest's
 * `node` environment where `@codemirror/view`'s module-level browser sniffing would not load.
 *
 * **This is a deliberate over-approximation, and the measurement is worth recording** — the guard was
 * proven by mutation and the first attempt did *not* cost a byte. Every `@codemirror/*` package
 * declares `sideEffects: false`, so an import whose binding is never used is tree-shaken away:
 * `import { EditorView } from '@codemirror/view'` plus a bare `void EditorView` in `lib/tree.ts`
 * reddens this file while the built landing page stays at 50,002 B gzip. Adding one *use* of the
 * binding inside a function the app calls takes the entry chunk from 134,770 to **337,908 B raw**
 * and 47,581 to **112,256 B gzip** — the whole editor back where it started.
 *
 * So the guard is *stricter* than the bundler, and that is the right direction: it is red on the
 * import that costs 65 kB and also on the dead one that costs nothing, and a dead CodeMirror import is
 * not something to leave in a file anyway. Do not "fix" the false positive by teaching this file
 * reachability analysis — the CLAUDE.md failure mode to fear is a check that stays *green* on the
 * defect (`strings | grep GLIBC_`), and this one has no such state.
 *
 * If this goes red, the fix is not an allow-list entry. Put the value behind
 * `lib/codemirror.ts` and reach it through the loader, or — if the design genuinely changed —
 * re-measure the bundle, update `frontend/README.md`'s table, and replace this file with the guard
 * that covers whatever replaced it.
 */

import { describe, expect, it } from 'vitest'

import { chunkEdges, moduleGraph, sources } from './module-graph'

/** The one file allowed to name a CodeMirror value, because it is the chunk. */
const LAZY_MODULE = 'lib/codemirror.ts'

/** Anything under this scope is a runtime CodeMirror package. */
const CODEMIRROR = /^@codemirror\//

/** How `lib/codemirror.ts` is spelled by an importer, with or without the extension. */
const LAZY_SPECIFIER = /(^|\/)lib\/codemirror(\.ts)?$/

const files = sources()
const graph = moduleGraph()

describe('the parser reaches real code, so an empty sweep cannot pass', () => {
  // The positive controls, and they are the reason the three assertions below are trustworthy. Every
  // one of them is of the form "this list is empty", which is exactly what a broken `sources()`, a
  // renamed file or a parser returning nothing would also produce — the failure mode that let a
  // security probe on KAN-554's review report a clean result while measuring nothing.
  it('finds the whole tree, including the two files this card is about', () => {
    expect(files.length).toBeGreaterThan(8)
    expect(graph.has(LAZY_MODULE)).toBe(true)
    expect(graph.has('components/EditorPane.svelte')).toBe(true)
  })

  it('sees the lazy module really does import CodeMirror for its values', () => {
    const cm = graph.get(LAZY_MODULE)!.staticValue.filter((s) => CODEMIRROR.test(s))
    // Five packages, which is the whole of ADR 0001 §2's dependency list. If this drops to zero the
    // sweep below has nothing left to be meaningful about.
    expect(cm.length).toBeGreaterThanOrEqual(5)
  })

  it('distinguishes a type-only import from a value one', () => {
    // `lib/editor.ts` has exactly two CodeMirror imports and both are erased. If the scanner could not
    // tell, this file would either be a permanent false positive or would have to exempt the module
    // that holds the editor's guards — and an exemption there is the loophole a real import walks
    // through.
    const editor = graph.get('lib/editor.ts')!
    expect(editor.staticType.filter((s) => CODEMIRROR.test(s))).toHaveLength(2)
    expect(editor.staticValue.filter((s) => CODEMIRROR.test(s))).toHaveLength(0)
  })
})

describe('CodeMirror stays out of the entry chunk', () => {
  it('is value-imported by `lib/codemirror.ts` and by nothing else in `src/`', () => {
    // The mutation this is written for: `import { EditorView } from '@codemirror/view'` added to any
    // module the entry reaches statically. The bundler follows it, the chunk re-merges, the landing
    // page pays ~80 KB gzip again, and nothing else in the suite notices.
    const { packageOffenders } = chunkEdges(graph, {
      owner: LAZY_MODULE,
      pkg: CODEMIRROR,
      specifier: LAZY_SPECIFIER,
    })

    expect(packageOffenders).toEqual([])
  })

  it('is reached only through `import()`, so the chunk boundary exists at all', () => {
    // The other half, and it fails differently: a static `import … from '../lib/codemirror'` in
    // `EditorPane.svelte` would keep the first assertion green — the file that names CodeMirror is
    // still the only one — while pulling the whole module back into the entry chunk. One rule per
    // sentence, because they are two ways for the same byte count to come back.
    const { staticImporters, lazyImporters } = chunkEdges(graph, {
      owner: LAZY_MODULE,
      pkg: CODEMIRROR,
      specifier: LAZY_SPECIFIER,
    })

    expect(staticImporters).toEqual([])
    // And someone does load it, or the editor never appears and the property above is vacuous.
    expect(lazyImporters).toEqual(["components/EditorPane.svelte: import('../lib/codemirror')"])
  })
})
