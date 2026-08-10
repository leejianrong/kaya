// @vitest-environment jsdom
/**
 * The same guards, against a real `EditorView`.
 *
 * `tests/editor-guards.test.ts` proves the predicates in isolation, which cannot be defeated by
 * jsdom. This file is the other half of CLAUDE.md's "a structural guard does not cover a behavioural
 * claim": a predicate that returns the right boolean still has to be *wired* to the right thing, and
 * the un-guarded write-back is a real failure in a real editor rather than a wrong return value.
 *
 * The un-guarded version of the echo path is not subtle. Dispatching from inside an
 * `updateListener` re-enters CM6's update cycle, so it recurses until
 * `RangeError: Maximum call stack size exceeded` — measured, in this environment, while writing
 * these tests. That is the loop PLAN §Open risks names, and the test below is it with the guard in.
 */

import { history, historyKeymap, undo } from '@codemirror/commands'
import { markdownLanguage } from '@codemirror/lang-markdown'
import { defaultHighlightStyle, ensureSyntaxTree, syntaxHighlighting } from '@codemirror/language'
import { EditorState } from '@codemirror/state'
import { EditorView, keymap } from '@codemirror/view'
import { afterEach, describe, expect, it } from 'vitest'

import { syncDocument } from '../src/lib/editor'

const views: EditorView[] = []
let parent: HTMLDivElement

function open(doc: string, extensions: readonly unknown[] = []): EditorView {
  parent = document.createElement('div')
  document.body.append(parent)
  const view = new EditorView({
    parent,
    state: EditorState.create({ doc, extensions: extensions as never[] }),
  })
  views.push(view)
  return view
}

afterEach(() => {
  for (const view of views.splice(0)) {
    view.destroy()
  }
  parent?.remove()
})

describe('the echo guard, wired to a real editor', () => {
  it('survives an update listener that writes straight back, which is the loop itself', () => {
    // The exact cycle, minus Svelte: every transaction is fed back in through `syncDocument`. With
    // the guard, the echo finds the incoming value is already the document and dispatches nothing, so
    // the cycle has depth one. Without it this recurses until the stack is gone.
    const held: { view?: EditorView } = {}
    let echoes = 0
    held.view = open('a', [
      EditorView.updateListener.of((update) => {
        if (!update.docChanged) {
          return
        }
        echoes += 1
        syncDocument(held.view as EditorView, update.state.doc.toString())
      }),
    ])

    // One user keystroke.
    held.view.dispatch({ changes: { from: 1, insert: 'b' } })

    expect(held.view.state.doc.toString()).toBe('ab')
    // One listener call for the keystroke and none for an echo: the guard refused to dispatch, so
    // there was no second transaction to be told about.
    expect(echoes).toBe(1)
  })

  it('applies a genuine external document as one transaction, keeping one view', () => {
    const view = open('before')
    const node = parent.firstElementChild

    expect(syncDocument(view, 'after')).toBe(true)

    expect(view.state.doc.toString()).toBe('after')
    // The document changed and the DOM node did not: a transaction, not a remount. This is the
    // property the browser check watches by node identity.
    expect(parent.firstElementChild).toBe(node)
    expect(parent.querySelectorAll('.cm-editor')).toHaveLength(1)
  })

  it('keeps the undo history across an incoming transaction, which a remount would discard', () => {
    // Why the identity guard is worth a test rather than a comment: a rebuilt view starts with an
    // empty history, so the visible symptom of getting this wrong is not a crash but an editor that
    // cannot undo — noticed long after the change that caused it.
    // `newGroupDelay: 0` so the two transactions below are two undo steps rather than one. CM6's
    // default groups changes made within 500 ms, which a test makes in under a millisecond — without
    // this the first `undo` jumps straight to the start and the assertion proves less than it looks.
    const view = open('one', [history({ newGroupDelay: 0 }), keymap.of(historyKeymap)])

    view.dispatch({ changes: { from: 3, insert: ' typed' } })
    expect(syncDocument(view, 'external')).toBe(true)

    expect(undo(view)).toBe(true)
    expect(view.state.doc.toString()).toBe('one typed')
    expect(undo(view)).toBe(true)
    expect(view.state.doc.toString()).toBe('one')
  })
})

describe('markdown language support', () => {
  it('parses the constructs the product needs — headings, fences, links', () => {
    // SLICES §V3's unit row. Over the syntax tree rather than over rendered colours: a class name on
    // a span is a fact about a highlight style, while the tree is the fact that the *language* is
    // installed — which is what wikilink decorations and `[[` autocomplete (KAN-567, V5) later hang
    // off.
    //
    // `markdownLanguage.extension` and not `markdown()`, because that is what the component installs
    // and a language test against a language the app does not use is worth nothing. The component's
    // comment carries the measurement that decided it; the point here is that the cheaper choice
    // still parses everything the product needs.
    const view = open('# Heading\n\n```js\nlet x = 1\n```\n\n[link](https://example.test)\n', [
      markdownLanguage.extension,
      syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
    ])

    const tree = ensureSyntaxTree(view.state, view.state.doc.length, 5000)
    const names = new Set<string>()
    tree?.iterate({
      enter: (node) => {
        names.add(node.name)
      },
    })

    expect(names).toContain('ATXHeading1')
    expect(names).toContain('FencedCode')
    expect(names).toContain('Link')
    expect(names).toContain('URL')
  })
})

describe('teardown', () => {
  it('leaves nothing behind in the container', () => {
    const view = open('gone')
    expect(parent.querySelectorAll('.cm-editor')).toHaveLength(1)

    view.destroy()

    // `destroy()` removes CM6's own root, so a leaked view is a visible node rather than an
    // invisible listener — which is what makes the DOM guard in `shell.test.ts` able to see one.
    expect(parent.childNodes).toHaveLength(0)
  })
})
