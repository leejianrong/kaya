/**
 * `EditorPane`'s `ondocument` seam, over the **parsed script** rather than over behaviour.
 *
 * KAN-554 replaced a cross-component reach (`EditorView.findFromDOM` from inside the preview) with a
 * published callback prop, once KAN-556 released `EditorPane.svelte`. The prop is the better seam, and
 * it comes with one hazard the reach did not have: the callback is a *value the parent owns*, so
 * reading it can make the `$effect` that owns the `EditorView` depend on it — and the parent's own
 * state changes on every keystroke that seam delivers. A parent handing down `ondocument={(d) => …}`
 * inline would then get a per-keystroke effect re-run, which is PLAN §Open risks' update loop arriving
 * through the reactivity system instead of through CM6.
 *
 * The fix is one word: the prop is read inside `untrack`. **This file is the only place that claim can
 * be checked**, because the two outcomes are indistinguishable from outside — an effect that re-runs
 * with the same ref and an unchanged body does nothing observable, so a DOM test watching for a
 * remount or a moved caret stays green either way. `tests/preview.test.ts` asserts the harm is absent;
 * this asserts the mechanism is present.
 *
 * Same technique and same reasoning as `tests/editor-container.test.ts` (the container has no template
 * children), `tests/no-html-injection.test.ts` (no markup sink in `src/`) and `kaya-cli`'s
 * `test_no_prompting.py` (nothing reads stdin). A structural claim wants a structural check.
 *
 * If this is red: do not delete the assertion. Put the read back inside `untrack`, or — if the design
 * genuinely changed — replace this file with the guard that covers whatever replaced it, because the
 * property being protected is "the editor's mount effect does not depend on its own consumer".
 */

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { parse } from 'svelte/compiler'
import { describe, expect, it } from 'vitest'

const COMPONENT = fileURLToPath(new URL('../src/components/EditorPane.svelte', import.meta.url))

/** The seam's prop name, and the identifier every read below is looking for. */
const SEAM = 'ondocument'

interface Node {
  type?: string
  name?: string
  start?: number
  end?: number
  callee?: Node
  init?: Node
  id?: Node
}

/** Every node in a parsed tree, depth first. `parent` is skipped or the walk never terminates. */
function* walk(node: unknown): Generator<Node> {
  if (node === null || typeof node !== 'object') {
    return
  }
  if (Array.isArray(node)) {
    for (const item of node) {
      yield* walk(item)
    }
    return
  }
  const candidate = node as Node & Record<string, unknown>
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

interface Range {
  start: number
  end: number
}

function script(): Node[] {
  const root = parse(readFileSync(COMPONENT, 'utf8'), { modern: true }) as unknown as Record<
    string,
    unknown
  >
  return Array.from(walk(root.instance))
}

function ranges(nodes: Node[], predicate: (node: Node) => boolean): Range[] {
  return nodes
    .filter((node) => predicate(node) && node.start !== undefined && node.end !== undefined)
    .map((node) => ({ start: node.start!, end: node.end! }))
}

function inside(node: Node, spans: Range[]): boolean {
  return spans.some((span) => (node.start ?? -1) >= span.start && (node.end ?? -1) <= span.end)
}

describe("the editor's document seam cannot make its own effect a dependency", () => {
  const nodes = script()

  // `untrack(...)` calls, and the `$props()` declarator where the prop is *declared* rather than read.
  const untracked = ranges(
    nodes,
    (node) => node.type === 'CallExpression' && node.callee?.name === 'untrack',
  )
  const declaration = ranges(
    nodes,
    (node) =>
      node.type === 'VariableDeclarator' &&
      node.init?.type === 'CallExpression' &&
      node.init.callee?.name === '$props',
  )
  const mentions = nodes.filter((node) => node.type === 'Identifier' && node.name === SEAM)

  it('parses the component and finds the seam at all, so an empty sweep cannot pass', () => {
    // The positive control, and it is the whole reason this file is trustworthy: without it, a rename
    // of the prop or a parser returning nothing would make every assertion below vacuously true. The
    // same mistake scoped a security probe to the wrong element on this card's review and reported a
    // clean result while measuring nothing.
    expect(untracked.length).toBeGreaterThan(0)
    expect(declaration).toHaveLength(1)
    expect(mentions.length).toBeGreaterThan(1)
  })

  it('reads the callback only inside `untrack`', () => {
    const offenders = mentions
      .filter((node) => !inside(node, declaration) && !inside(node, untracked))
      .map((node) => `${SEAM} at offset ${node.start}`)

    // The failure names the offset, because "somewhere in EditorPane.svelte" is not actionable.
    expect(offenders).toEqual([])
  })

  it('has at least one read that really is inside `untrack`', () => {
    // Paired with the test above: together they say "every read is untracked **and** a read exists".
    // Either one alone passes on a component that never reads the prop, which is a broken seam.
    expect(mentions.filter((node) => inside(node, untracked))).not.toHaveLength(0)
  })
})

describe('the remount decision still cannot see the document', () => {
  it('`needsRemount` takes exactly three parameters and none of them is a body', async () => {
    // ADR 0008 and `lib/editor.ts`: a remount may depend on the ref and on nothing else. Asserted as
    // arity rather than as behaviour, the same shape as `kaya-client`'s `attach_summary` taking one
    // argument — "it cannot see the body" is then a fact about what is in scope rather than a rule
    // somebody follows, and the mutation that breaks it has to widen a signature first.
    const { needsRemount } = await import('../src/lib/editor')
    expect(needsRemount).toHaveLength(3)
  })
})
