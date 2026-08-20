/**
 * `BacklinksPanel`'s `subject` rune, over the **parsed script** rather than over behaviour — and this
 * file exists because two mutations came back **green**.
 *
 * Both of them are claims a jsdom test cannot see, for the same underlying reason: `flushSync` runs
 * the effects *and* the DOM update in one pass, so any property whose whole content is "these two
 * values are never observably out of step" is collapsed by the instrument that would check it. That
 * is `tests/document-seam.test.ts`'s situation exactly, and this file is written in its shape.
 *
 * ## The first green mutation: render the subject off the prop
 *
 * Replacing `panelState({ ref: subject, … })` with `panelState({ ref: note?.ref ?? null, … })` passes
 * all thirty assertions in `tests/backlinks-panel.test.ts` and `tests/backlinks-rail.test.ts`. It is
 * still wrong, and the window is a real one: `note` moves first, so the `$derived` recomputes with the
 * **new** ref over the **old** answer's rows and the count above them, and the effect that clears
 * `found` runs afterwards. In a browser that is one render of a heading that says `NOTE-2` and a `3`
 * over three notes linking to `NOTE-1`. `flushSync` cannot show it because it does both halves before
 * returning. So the property is asserted here instead: the rendered subject comes from the rune the
 * *answer* set, never from the prop.
 *
 * ## The second: the effect reading the rune without `untrack`
 *
 * `subject` is one variable doing two jobs — the guard's memory and the rendered subject — where
 * `EditorPane` uses two (`mountedRef`, a plain `let`, and `basedOn`, a rune) precisely because "a rune
 * an effect both reads and writes is an effect that retriggers itself". Untracking the *read* buys the
 * same property with one variable, and nothing about that is visible from outside: the extra run is a
 * run the identity guard immediately returns out of, so it does nothing at all. Asserting it needs the
 * mechanism rather than the harm.
 *
 * If either goes red, do not relax it. Put the read back inside `untrack` and the render back on the
 * rune — or, if the design genuinely changed, replace this file with the guard covering whatever
 * replaced it, because the property is "what the rail says it is about is what it asked about".
 */

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { parse } from 'svelte/compiler'
import { describe, expect, it } from 'vitest'

const COMPONENT = fileURLToPath(new URL('../src/components/BacklinksPanel.svelte', import.meta.url))

/** The rune whose reads this file is about. */
const SUBJECT = 'subject'

interface Node {
  type?: string
  name?: string
  start?: number
  end?: number
  callee?: Node
  arguments?: Node[]
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

function script(): Node[] {
  const root = parse(readFileSync(COMPONENT, 'utf8'), { modern: true }) as unknown as Record<
    string,
    unknown
  >
  return Array.from(walk(root.instance))
}

/** Every call in the script whose callee is the plain identifier `name`. */
function calls(nodes: Node[], name: string): Node[] {
  return nodes.filter((node) => node.type === 'CallExpression' && node.callee?.name === name)
}

/** The identifiers inside one node's span, by name. */
function identifiersIn(nodes: Node[], span: Node): string[] {
  return nodes
    .filter(
      (node) =>
        node.type === 'Identifier' &&
        (node.start ?? -1) >= (span.start ?? 0) &&
        (node.end ?? -1) <= (span.end ?? 0),
    )
    .map((node) => node.name!)
}

describe('what the rail says it is about is what it asked about', () => {
  const nodes = script()
  const rendered = calls(nodes, 'panelState')
  const guarded = calls(nodes, 'needsFetch')
  const untracked = calls(nodes, 'untrack')

  it('parses the component and finds all three calls, so an empty sweep cannot pass', () => {
    // The positive control, and the reason the rest is trustworthy: a rename, a moved call or a
    // parser returning nothing would otherwise make every assertion below vacuously true. This
    // repo's own near-miss on that is an XSS probe scoped to a selector that matched a button.
    expect(rendered).toHaveLength(1)
    expect(guarded).toHaveLength(1)
    expect(untracked.length).toBeGreaterThan(0)
    expect(nodes.filter((node) => node.name === SUBJECT).length).toBeGreaterThan(2)
  })

  it('derives the rendered state from the `subject` rune', () => {
    // Mutation M10, which was green: `ref: note?.ref ?? null`. One render of the new note's heading
    // over the previous note's rows, invisible to `flushSync`.
    expect(identifiersIn(nodes, rendered[0])).toContain(SUBJECT)
  })

  it('does not derive it from the `note` prop, which moves one render earlier', () => {
    expect(identifiersIn(nodes, rendered[0])).not.toContain('note')
  })

  it('reads the rune through `untrack` where the effect compares it', () => {
    // Mutation M10b, also green: drop the `untrack` and the effect depends on its own output. It
    // terminates — the second run's guard returns immediately — so nothing observable happens, which
    // is exactly why this is a structural assertion and not a behavioural one.
    const [argument] = guarded[0].arguments ?? []
    expect(argument?.type).toBe('CallExpression')
    expect(argument?.callee?.name).toBe('untrack')
    expect(identifiersIn(nodes, argument!)).toContain(SUBJECT)
  })
})
