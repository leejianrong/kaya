/**
 * PLAN §S9, checked over the **template source** rather than over one rendered instance.
 *
 * "Svelte never renders inside CM6's subtree" is a claim about the markup, and a DOM test can only
 * ever see the props that test happened to pass. This one fires unconditionally: it parses
 * `EditorPane.svelte` with Svelte's own compiler and asserts the container element has **zero**
 * template children. Anything a future author could put in there — a word of text, `{note.title}`,
 * `{#if}`, `{#each}`, `{@html}`, a `<span>` — is a node in that fragment, so one assertion covers
 * the whole class.
 *
 * The repo already prefers this shape twice, both for the same reason: `kaya-cli`'s
 * `tests/test_no_prompting.py` asserts over the package's AST rather than over behaviour, and
 * `test_bare_invocation.py` counts `render` call sites the same way. A structural claim wants a
 * structural check.
 *
 * **This exists because the DOM guard beside it was not enough, and the way it failed is worth
 * keeping.** The first version of that guard walked `container.children` and looked for a Svelte
 * scoping class. It missed a text node (`children` is an `HTMLCollection` of *elements*;
 * `childNodes` is the one that sees text), it missed an unstyled element (Svelte only emits a
 * scoping class when a scoped style rule matches, so `<span>` carried none), and it missed the
 * comment anchor a `{#if}` leaves behind even when it renders nothing. Three blind spots in the
 * one guard the next card depends on. The DOM check is now an identity check over `childNodes`,
 * and this file is the belt to its braces.
 */

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { parse } from 'svelte/compiler'
import { describe, expect, it } from 'vitest'

const COMPONENT = fileURLToPath(new URL('../src/components/EditorPane.svelte', import.meta.url))

/** The class naming S9's container. The same string the component and the DOM guard use. */
const CONTAINER_CLASS = 'editor-host'

interface TemplateNode {
  type?: string
  name?: string
  attributes?: TemplateNode[]
  value?: TemplateNode[] | boolean
  data?: string
  fragment?: { nodes: TemplateNode[] }
}

/** Every node in the template, depth first. `parent` is skipped or the walk never terminates. */
function* walk(node: unknown): Generator<TemplateNode> {
  if (node === null || typeof node !== 'object') {
    return
  }
  if (Array.isArray(node)) {
    for (const item of node) {
      yield* walk(item)
    }
    return
  }
  const candidate = node as TemplateNode & Record<string, unknown>
  if (typeof candidate.type === 'string') {
    yield candidate
  }
  for (const [key, value] of Object.entries(candidate)) {
    if (key === 'parent') {
      continue
    }
    yield* walk(value)
  }
}

/** A static `class` attribute's text, or `null` when it is absent or interpolated. */
function staticClass(element: TemplateNode): string | null {
  const attribute = element.attributes?.find((candidate) => candidate.name === 'class')
  if (attribute === undefined || !Array.isArray(attribute.value)) {
    return null
  }
  const parts = attribute.value.map((part) => part.data)
  return parts.every((part) => typeof part === 'string') ? parts.join('') : null
}

function containers(): TemplateNode[] {
  const source = readFileSync(COMPONENT, 'utf8')
  const root = parse(source, { modern: true })
  return Array.from(walk(root.fragment)).filter(
    (node) =>
      node.type === 'RegularElement' &&
      (staticClass(node) ?? '').split(/\s+/).includes(CONTAINER_CLASS),
  )
}

describe("PLAN §S9's container, over the template source", () => {
  it('exists exactly once, so there is one boundary rather than two', () => {
    // A second container would be a second place the rule has to be remembered, and the DOM guard
    // beside this one would only ever check whichever came first.
    expect(containers()).toHaveLength(1)
  })

  it('has no template children at all', () => {
    const [container] = containers()
    const children = (container.fragment?.nodes ?? []).map(
      (node) => `${node.type}${node.data === undefined ? '' : ` ${JSON.stringify(node.data)}`}`,
    )

    // The failure message names what was put inside, which is the whole value of parsing rather
    // than pattern-matching the file: `Text " loading "`, `IfBlock`, `ExpressionTag`.
    //
    // If this is red, do not add the node to an allow-list. The element belongs to CodeMirror
    // (ADR 0001 §2) and the loop PLAN §Open risks warns about starts with exactly one word of
    // Svelte-owned content in here.
    expect(children).toEqual([])
  })
})
