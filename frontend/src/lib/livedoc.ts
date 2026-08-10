/**
 * How the preview reads the document being edited, **without the document going through a prop**.
 *
 * ## The constraint this module exists to satisfy
 *
 * `EditorPane.svelte` owns the `EditorView` and its `$effect` must not re-run because of the preview
 * — see that file's docstrings, and `lib/editor.ts` on the identity and echo guards. The obvious
 * wiring is the forbidden one: lift the document into the parent, hand it back down as `note.body`,
 * and the effect that owns the editor now re-runs on every keystroke. It would not *remount* (the
 * identity guard holds, and `needsRemount` takes no body parameter so no amount of content can reach
 * that decision) — but it would put a per-keystroke round trip through Svelte's reactive graph
 * between CM6 and itself, for a value CM6 already has, and the only thing standing between that and
 * PLAN §Open risks' update loop would be the echo guard firing thousands of times a minute.
 *
 * So the document flows **laterally**: the preview attaches its own listener to the live view and
 * nothing above either component learns that a character was typed. That is what makes "the editor
 * does not remount when the preview updates" a fact about the data path rather than a guard someone
 * has to keep passing.
 *
 * ## Why it finds the view through the DOM
 *
 * `EditorView.findFromDOM` is CM6's own public API for exactly this: recovering the view that owns a
 * node. The alternative is an `ondocument` callback prop on `EditorPane`, which would be a *better*
 * seam — and it is not available, because KAN-556 owns that file in this wave and a card may not edit
 * a file another card is holding. When someone adds that prop, `trackEditor` is the only thing that
 * has to change; `watchDocument` and `PreviewPane.svelte` are written against a view and a callback
 * and would not notice.
 *
 * PLAN §S9 is untouched by any of this. Reading a view is not rendering into its subtree: nothing
 * here creates, moves or removes a node, and the preview's own output goes in a sibling element.
 */

import { StateEffect } from '@codemirror/state'
import { EditorView } from '@codemirror/view'

/**
 * Every callback watching a given view, and the reason it is a `WeakMap` rather than a counter.
 *
 * A view's configuration can only be *appended* to (`StateEffect.appendConfig`), never trimmed, so
 * appending one `updateListener` per subscriber would leave a listener behind for every attach — and
 * with a `MutationObserver` driving re-attachment, "every attach" is not a number anyone controls.
 * One listener per view, dispatching to a set, keeps the view's configuration a constant size no
 * matter how many times {@link watchDocument} is called. The map is weak so a destroyed view is
 * collectable.
 */
const watchers = new WeakMap<EditorView, Set<(doc: string) => void>>()

/** The live view showing inside `scope`, or `null` while there is none. */
export function findEditor(scope: ParentNode): EditorView | null {
  const dom = scope.querySelector('.cm-editor')
  return dom === null ? null : EditorView.findFromDOM(dom as HTMLElement)
}

/**
 * Call `onEditor` with the view inside `scope` — now, and every time it is **replaced**.
 *
 * Replaced is the case that matters: `EditorPane`'s effect destroys and rebuilds the view when the
 * open note changes (ADR 0008's identity guard), so a listener attached to the old one would leave the
 * preview showing the previous note's text. A `MutationObserver` rather than trust in effect ordering,
 * because the ordering that makes the synchronous path work — `EditorPane` earlier in the parent's
 * markup, so its effect is created and therefore flushed first — is a property of a *third* file's
 * markup, and a preview that silently shows the wrong note when someone reorders two lines is not a
 * trade worth making. When the ordering does hold, `sync()` below finds the new view on the first,
 * synchronous call and the observer never has to fire.
 *
 * The identity comparison is what keeps this cheap: CM6 mutates its own DOM on every keystroke, so
 * the observer fires constantly, and `onEditor` runs only when the answer actually changed.
 */
export function trackEditor(scope: ParentNode, onEditor: (view: EditorView | null) => void): () => void {
  let current: EditorView | null = null

  const sync = (): void => {
    const found = findEditor(scope)
    if (found === current) {
      return
    }
    current = found
    onEditor(found)
  }

  const observer = new MutationObserver(sync)
  observer.observe(scope as Node, { childList: true, subtree: true })
  sync()

  return () => {
    observer.disconnect()
  }
}

/**
 * Publish `view`'s document to `onDoc` now, and on every change to it. Returns an unsubscribe.
 *
 * The notification is CM6's `updateListener`, appended to the live view with
 * `StateEffect.appendConfig` — the sanctioned way to extend a view that already exists. Nothing
 * cheaper is correct: a DOM `input` listener sees only the changes a browser makes to the
 * `contenteditable`, missing every command-driven one (`Mod-Z`, Enter continuing a list), and reading
 * the rendered DOM instead of `state.doc` would read a *virtualised* document — CM6 renders the
 * viewport, not the file, so a long note's preview would end where the scroll did.
 *
 * The appended transaction carries no changes, so `update.docChanged` is `false` for it and
 * `EditorPane`'s own `updateListener` does not mark the note dirty. Attaching a preview must not make
 * a note look edited.
 */
export function watchDocument(view: EditorView, onDoc: (doc: string) => void): () => void {
  let subscribers = watchers.get(view)

  if (subscribers === undefined) {
    subscribers = new Set()
    watchers.set(view, subscribers)
    const listening = subscribers
    view.dispatch({
      effects: StateEffect.appendConfig.of(
        EditorView.updateListener.of((update) => {
          if (!update.docChanged) {
            return
          }
          const doc = update.state.doc.toString()
          for (const subscriber of listening) {
            subscriber(doc)
          }
        }),
      ),
    })
  }

  subscribers.add(onDoc)
  // `state.doc` and not the note's `body`: the view may already hold unsaved edits, and the preview's
  // first paint has to agree with what is on screen beside it.
  onDoc(view.state.doc.toString())

  const attached = subscribers
  return () => {
    attached.delete(onDoc)
  }
}
