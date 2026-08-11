/**
 * **Every runtime byte of CodeMirror in this app, behind one `import()`.**
 *
 * This module exists for the bundle rather than for the design (KAN-767). KAN-553 measured CM6
 * honestly at **+313,729 B raw / +100,506 B gzip -9** and put it in the entry chunk, which was
 * correct on the day: there was no other state for the app to be in. Then KAN-555 made the landing
 * page the first thing an unauthenticated visitor sees, and it is where they paste a pandan PAT — so
 * a person who may not even have an account was downloading a markdown grammar, a view layer and an
 * undo history *before* they could type into a password field. The editor's bytes are not wrong; the
 * *time* they arrived was.
 *
 * So the five value imports below used to sit at the top of `EditorPane.svelte`, and moving them one
 * file across is the whole fix. `EditorPane.svelte` is still statically imported by `App.svelte` —
 * which is what keeps PLAN §S9's two guards (`tests/editor-container.test.ts` and
 * `tests/shell.test.ts`) parsing and mounting the same component they always did, and keeps the pane
 * **outside** the preview's `{#if}` where `App.svelte` argues it belongs. What became lazy is the
 * *library*, not the component.
 *
 * `tests/editor-chunk-is-lazy.test.ts` is the guard, and it guards two things because either one
 * alone silently re-merges the chunk: this is the **only** file under `src/` that value-imports
 * `@codemirror/*`, and **nothing** static-imports this file.
 *
 * ## What is in here and what deliberately is not
 *
 * In: the extension set, the theme, and `new EditorView(...)` — everything that cannot be written
 * without a CodeMirror value in scope, and nothing else.
 *
 * Out: every decision that is about *the note*. The two guards stay in `lib/editor.ts` as pure
 * predicates over an erased `import type` (so they still load in vitest's `node` environment), the
 * save path and ADR 0009's precondition stay in `EditorPane.svelte`, and the runes stay there too.
 * This file takes a document, a flag and two callbacks; it has never heard of a `Note`.
 */

import { defaultKeymap, history, historyKeymap, isolateHistory } from '@codemirror/commands'
import { markdownKeymap, markdownLanguage } from '@codemirror/lang-markdown'
import { defaultHighlightStyle, syntaxHighlighting } from '@codemirror/language'
import type { Annotation } from '@codemirror/state'
import { EditorState } from '@codemirror/state'
import { EditorView, keymap, placeholder } from '@codemirror/view'

/** What a caller has to say to get an editor, and the whole of what this module knows about it. */
export interface EditorSpec {
  /** PLAN §S9's container. `new EditorView({ parent })` is the only thing that ever writes in it. */
  parent: HTMLElement
  /** The initial document. */
  doc: string
  /** Whether there is a note to edit — `false` is the zero state, which is a read-only view. */
  editable: boolean
  /** The zero-state and empty-note copy, passed in so user-facing words stay in the component. */
  placeholder: string
  /** `Mod-s`. CM6 keybindings are synchronous and return whether they handled the key. */
  onSave: () => boolean
  /** Every `docChanged` transaction, as the document it produced. */
  onChange: (document: string) => void
}

/**
 * ADR 0009's "keep theirs" annotation, exported because `isolateHistory` lives in
 * `@codemirror/commands` and this file is the only place that may name it.
 *
 * The reasoning is `EditorPane.svelte`'s `keepTheirs`, and it stays there: a discard has to be
 * exactly **one** undo, and without isolation CM6 merges it into the typing group it interrupted, so
 * undo would throw the user's own text away as well. `'full'` isolates on both sides.
 */
export const HISTORY_ISOLATION: readonly Annotation<unknown>[] = [isolateHistory.of('full')]

/**
 * CM6 injects its own CSS through `style-mod` at runtime, so this theme costs JavaScript rather than
 * stylesheet — and it reads `app.css`'s tokens, so the editor is one surface with the app in both
 * colour schemes instead of a light rectangle inside a dark page.
 *
 * A module-level `const` here rather than in the component, for the plain reason that
 * `EditorView.theme` needs `EditorView`, which is exactly the value this module exists to defer.
 */
const theme = EditorView.theme({
  '&': {
    backgroundColor: 'transparent',
    color: 'var(--ink)',
    fontFamily: 'var(--mono)',
    fontSize: '0.9rem',
    height: '100%',
  },
  '.cm-scroller': { fontFamily: 'inherit', lineHeight: '1.6' },
  '.cm-content': { caretColor: 'var(--accent)' },
  '.cm-cursor, .cm-dropCursor': { borderLeftColor: 'var(--accent)' },
  '.cm-gutters': { backgroundColor: 'transparent', borderRight: '1px solid var(--edge)' },
  '.cm-activeLine': { backgroundColor: 'color-mix(in srgb, var(--accent) 6%, transparent)' },
  '&.cm-focused': { outline: 'none' },
  '.cm-placeholder': { color: 'var(--muted)' },
})

/** The extension set, and the one place a new CodeMirror package would have to earn its bytes. */
export function createView(spec: EditorSpec): EditorView {
  return new EditorView({
    parent: spec.parent,
    state: EditorState.create({
      doc: spec.doc,
      extensions: [
        // Undo history is part of what the identity guard protects: a remount per keystroke would
        // throw this away silently, so it is here from the first commit rather than later.
        history(),
        keymap.of([
          { key: 'Mod-s', preventDefault: true, run: spec.onSave },
          ...markdownKeymap,
          ...historyKeymap,
          ...defaultKeymap,
        ]),
        // **`markdownLanguage.extension`, not `markdown()`, and this is a measurement rather than a
        // preference.** Both give the same GFM grammar; `markdown()` additionally wires
        // `@codemirror/lang-html` in as the parser for raw HTML blocks, and lang-html drags
        // `lang-javascript` and `lang-css` behind it for embedded script and style tags. Measured on
        // this tree with esbuild, minified: `markdown()` costs **500,618 B raw / 171,369 B gzip -9**
        // against **312,798 / 101,872** for the language plus its keymap — **187,820 B raw /
        // 69,497 B gzip** for highlighting HTML that a markdown note rarely contains.
        // `markdownKeymap` is imported explicitly because it is the part of `markdown()` worth
        // keeping (Enter continues a list), and taking it by name is what lets the html import
        // tree-shake away.
        //
        // If you replace this with `markdown()`, the lazy chunk grows by two thirds. That is now a
        // cost paid on opening a note rather than on loading the page, which makes it cheaper and
        // not free — KAN-767 moved where the bytes are, not whether they exist.
        markdownLanguage.extension,
        syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
        EditorView.lineWrapping,
        EditorView.editable.of(spec.editable),
        // The zero states, as CM6's own placeholder rather than as a Svelte node — the container has
        // no template children and this is why it does not need any.
        placeholder(spec.placeholder),
        // Out through the update listener, as ADR 0001 §2 requires. The caller sets runes its mount
        // effect never reads, so its own wiring cannot cycle; the echo guard in `lib/editor.ts` is
        // what holds when someone else's wiring does.
        EditorView.updateListener.of((update) => {
          if (update.docChanged) {
            spec.onChange(update.state.doc.toString())
          }
        }),
        theme,
      ],
    }),
  })
}
