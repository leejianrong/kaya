/**
 * **A bundle guard, not a style rule** (KAN-836) — `tests/editor-chunk-is-lazy.test.ts` one layer
 * down, over the same instrument, for the bytes KAN-767 left behind.
 *
 * `lib/markdown.ts` walks `@lezer/markdown`'s syntax tree to build the live preview's DOM, and that
 * grammar is **20,362 B gzip -9**. After KAN-767 moved CodeMirror onto its own chunk it was 43% of
 * what was left in the entry — paid by an unauthenticated visitor on KAN-555's landing page, whose next
 * action is pasting a live pandan PAT into a password field, and by a signed-in user sitting on `/`.
 * Neither can see a rendered byte.
 *
 * Two rules, and each one alone silently re-merges the chunk:
 *
 * - `lib/markdown.ts` is the **only** file under `src/` that value-imports `@lezer/*`;
 * - **nothing** static-imports `lib/markdown.ts` — it is reached through `import()` and nowhere else.
 *
 * A static `import { renderMarkdown } from '../lib/markdown'` in `PreviewPane.svelte` keeps the first
 * rule perfectly true while undoing all of it, which is why there are two sentences rather than one.
 * That is KAN-767's finding restated, and it is the same finding because it is the same failure: the
 * app works, every other test stays green, and the only witness is `frontend/README.md`'s table, which
 * nobody re-measures on an unrelated card.
 *
 * **`@lezer/*` rather than `@lezer/markdown` alone**, because `@lezer/common` is the grammar's own
 * runtime and a value import of it is the same chunk arriving under a different name. `lib/markdown.ts`
 * imports `SyntaxNode` and `Tree` from it as **types**, which `verbatimModuleSyntax` erases, so that
 * import is invisible here and is what lets the renderer's types be named anywhere.
 *
 * **The over-approximation is deliberate and is the same one KAN-767 recorded.** `@lezer/markdown`
 * declares `"sideEffects": false`, so an import whose binding is never used is tree-shaken away and
 * costs nothing while still reddening this file. That is the right direction: a dead grammar import is
 * not something to leave in a file, and the failure mode to fear is a check that stays *green* on the
 * defect. Do not teach this file reachability analysis.
 *
 * If this goes red, the fix is not an allow-list entry. Reach the renderer through `PreviewPane`'s
 * loader — or, if the design genuinely changed, re-measure the bundle, update `frontend/README.md`'s
 * table, and replace this file with the guard that covers whatever replaced it.
 */

import { describe, expect, it } from 'vitest'

import { chunkEdges, moduleGraph, sources } from './module-graph'

/** The one file allowed to name a `@lezer` value, because it is the chunk. */
const LAZY_MODULE = 'lib/markdown.ts'

/** Anything under this scope is a runtime lezer package: the grammar, or the tree it produces. */
const LEZER = /^@lezer\//

/** How `lib/markdown.ts` is spelled by an importer, with or without the extension. */
const LAZY_SPECIFIER = /(^|\/)lib\/markdown(\.ts)?$/

const files = sources()
const graph = moduleGraph()

describe('the parser reaches real code, so an empty sweep cannot pass', () => {
  // Every assertion in the next block is of the form "this list is empty", which is exactly what a
  // broken sweep, a renamed file or a parser returning nothing would also produce. These say the
  // instrument is pointed at the two files this card is about.
  it('finds the whole tree, including the two files this card is about', () => {
    expect(files.length).toBeGreaterThan(8)
    expect(graph.has(LAZY_MODULE)).toBe(true)
    expect(graph.has('components/PreviewPane.svelte')).toBe(true)
  })

  it('sees the lazy module really does import the grammar for its values', () => {
    // If this drops to zero the rule below has nothing left to be meaningful about — the preview
    // would have stopped parsing markdown, which is a different and much louder bug.
    const lezer = graph.get(LAZY_MODULE)!.staticValue.filter((s) => LEZER.test(s))

    expect(lezer).toEqual(['@lezer/markdown'])
  })

  it('distinguishes a type-only import from a value one', () => {
    // `lib/markdown.ts`'s `@lezer/common` import is erased, and it has to be readable as erased or
    // this file is either a permanent false positive or has to exempt the very module it guards.
    const renderer = graph.get(LAZY_MODULE)!

    expect(renderer.staticType).toContain('@lezer/common')
    expect(renderer.staticValue).not.toContain('@lezer/common')
  })
})

describe('the markdown grammar stays out of the entry chunk', () => {
  it('is value-imported by `lib/markdown.ts` and by nothing else in `src/`', () => {
    // The mutation this is written for: `import { parser } from '@lezer/markdown'` added to any module
    // the entry reaches statically. The bundler follows it, the grammar re-merges, the landing page
    // pays ~20 KB gzip again, and nothing else in the suite notices.
    const { packageOffenders } = chunkEdges(graph, {
      owner: LAZY_MODULE,
      pkg: LEZER,
      specifier: LAZY_SPECIFIER,
    })

    expect(packageOffenders).toEqual([])
  })

  it('is reached only through `import()`, so the chunk boundary exists at all', () => {
    // The other half, and it fails differently: a static `import … from '../lib/markdown'` in
    // `PreviewPane.svelte` would keep the assertion above green — the file that names the grammar is
    // still the only one — while pulling the whole module back into the entry chunk.
    const { staticImporters, lazyImporters } = chunkEdges(graph, {
      owner: LAZY_MODULE,
      pkg: LEZER,
      specifier: LAZY_SPECIFIER,
    })

    expect(staticImporters).toEqual([])
    // And someone does load it, or the preview never renders and the property above is vacuous.
    expect(lazyImporters).toEqual(["components/PreviewPane.svelte: import('../lib/markdown')"])
  })

  it('keeps the renderer under `src/`, where the XSS guard is still looking', () => {
    // KAN-836's own hazard, and it is not a bundle one. `tests/no-html-injection.test.ts` and
    // `tests/markdown.test.ts` both sweep `src/`, and this card's obvious wrong turn is moving the
    // DOM-building code somewhere those globs stop reaching — the XSS guard would narrow its scope
    // silently while staying green. Making the module lazy must not move the module.
    expect(files.some((file) => file.endsWith('src/lib/markdown.ts'))).toBe(true)
  })
})
