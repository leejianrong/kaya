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
 *
 * **KAN-567 widened this file's own claim about itself.** It used to take a document, a flag and two
 * callbacks and "never heard of a `Note`"; it now also takes the open note's resolved wikilinks
 * (`EditorSpec.links`) and fetches note titles for `[[` completion. Both stay inside the boundary the
 * paragraph above draws, for two different reasons. The **pill** needs `Decoration` and `ViewPlugin`
 * to turn a `/links` answer into a highlighted span, which — like the guards above — is a decision
 * that only becomes a CodeMirror concern at the point it is rendered; the *data* is still fetched by
 * `EditorPane.svelte`, keyed on the `note` prop exactly as `BacklinksPanel.svelte` fetches its own
 * data, and handed in here as a plain value ({@link setWikilinks}) rather than fetched from inside a
 * decoration extension — a `ViewPlugin`'s `update` runs synchronously on every view update, and an
 * extension that went and fetched from inside one would be exactly the kind of side effect this
 * file's guards exist to keep out of an `$effect`. The **autocomplete** source is different: CM6's
 * own `autocompletion()` is built for an async source, `context.aborted` is how it tells a stale
 * request from a live one, and `lib/notes.ts`'s `listNotes` is already the side-effect-free,
 * unshaped call every other reader of `/api/v1/notes` makes (ADR 0004 exempts the SPA from shaping
 * entirely) — so calling it directly from the source is the idiomatic use of the API CM6 offers,
 * not a rule bent to fit a card.
 *
 * **R14 (KAN-1067) widened this file the same way again**, for a drop/paste-to-upload handler:
 * `EditorView.domEventHandlers` needs `EditorView` in scope to construct, so the extension lives
 * here, and `lib/attachments.ts`'s `uploadAttachment` is called directly from it — the identical
 * shape the autocomplete source above already established for a plain, unshaped API call made from
 * inside a CodeMirror extension. See {@link attachmentDropPaste}.
 */

import {
  autocompletion,
  type Completion,
  type CompletionContext,
  type CompletionResult,
} from '@codemirror/autocomplete'
import { defaultKeymap, history, historyKeymap, isolateHistory } from '@codemirror/commands'
import { markdownKeymap, markdownLanguage } from '@codemirror/lang-markdown'
import { defaultHighlightStyle, syntaxHighlighting, syntaxTree } from '@codemirror/language'
import type { Annotation } from '@codemirror/state'
import { EditorState, StateEffect, StateField } from '@codemirror/state'
import {
  Decoration,
  type DecorationSet,
  EditorView,
  keymap,
  placeholder,
  ViewPlugin,
  type ViewUpdate,
} from '@codemirror/view'

import { uploadAttachment } from './attachments'
import { listNotes } from './notes'
import type { Link } from './types'
import {
  excludeFenced,
  findWikilinkSpans,
  isResolved,
  matchingLink,
  wikilinkTooltip,
  wikilinkTrigger,
} from './wikilinks'

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
  /**
   * KAN-567: the open note's outbound wikilinks, as `/links` last answered — the initial paint
   * only. A later answer (the fetch resolving after mount, or a re-fetch after a save) reaches the
   * live view through {@link setWikilinks}, not through a second `createView` call.
   */
  links: readonly Link[]
  /**
   * R14 (KAN-1067): the ref an uploaded file attaches to, or `null` in the zero state (no note
   * open — `EditorPane.svelte`'s read-only view). `null` is what turns drop/paste-to-upload off
   * entirely: {@link attachmentDropPaste}'s handlers decline the event and let the browser's
   * default behaviour run (typically opening the dropped file), the same "there is nothing to do
   * this without" reasoning `EditorSpec.editable`'s `false` already gives the zero state.
   */
  noteRef: string | null
  /**
   * A drop/paste upload was attempted and failed — `ApiError`/`NetworkError`'s message, or a
   * generic fallback. Optional: a caller that does not wire this simply shows no failure message,
   * same convention as every other optional callback here.
   */
  onAttachmentError?: (message: string) => void
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
    color: 'var(--text)',
    fontFamily: 'var(--mono)',
    fontSize: '0.9rem',
    height: '100%',
  },
  '.cm-scroller': { fontFamily: 'inherit', lineHeight: '1.6' },
  '.cm-content': { caretColor: 'var(--accent)' },
  '.cm-cursor, .cm-dropCursor': { borderLeftColor: 'var(--accent)' },
  '.cm-gutters': { backgroundColor: 'transparent', borderRight: '1px solid var(--border)' },
  '.cm-activeLine': { backgroundColor: 'color-mix(in srgb, var(--accent) 6%, transparent)' },
  '&.cm-focused': { outline: 'none' },
  '.cm-placeholder': { color: 'var(--muted)' },
  // KAN-567's pill, `Decoration.mark` over the raw `[[...]]` span — the text stays exactly what the
  // caret can edit, and only the styling changes. The two states mirror the app's existing visual
  // language rather than inventing a new one: `.cm-wikilink-resolved` is the same accent-tinted
  // rounded badge `App.svelte`'s `.toggle.on` already uses, and `.cm-wikilink-unresolved` is
  // `lib/markdown.ts`'s `.unlinked` span — muted, monospace, a dotted underline — so a link that
  // could not be confirmed reads the same way in the editor as it does in the preview beside it.
  '.cm-wikilink': { borderRadius: '0.25rem', padding: '0 0.15rem' },
  '.cm-wikilink-resolved': {
    backgroundColor: 'color-mix(in srgb, var(--accent) 14%, transparent)',
    color: 'var(--accent)',
  },
  '.cm-wikilink-unresolved': {
    color: 'var(--muted)',
    borderBottom: '1px dotted var(--muted)',
  },
})

/** KAN-567: what {@link setWikilinks} carries into a live view, outside any transaction the caller
 *  already has in flight. */
const setWikilinksEffect = StateEffect.define<readonly Link[]>()

/** The open note's resolved wikilinks, as the pill decoration reads them on every rebuild. */
const wikilinksField = StateField.define<readonly Link[]>({
  create: () => [],
  update(value, transaction) {
    for (const effect of transaction.effects) {
      if (effect.is(setWikilinksEffect)) {
        return effect.value
      }
    }
    return value
  },
})

/**
 * Hand the view a fresh `/links` answer, outside any transaction the caller already has.
 *
 * `createView`'s `EditorSpec.links` seeds the very first paint; this is how a *later* answer
 * reaches an already-live view — the initial fetch resolving after mount, or a re-fetch after a
 * save reconciles `note_link` server-side — without a remount. `EditorPane.svelte` is the only
 * caller, right after its own fetch settles.
 */
export function setWikilinks(view: EditorView, links: readonly Link[]): void {
  view.dispatch({ effects: setWikilinksEffect.of(links) })
}

/** Every fenced-code-block range in `state`'s parsed document — the one thing `lib/wikilinks.ts`
 *  cannot compute itself, because it has no CodeMirror value to ask (see that module's header). */
function fencedRanges(state: EditorState): { from: number; to: number }[] {
  const ranges: { from: number; to: number }[] = []
  syntaxTree(state).iterate({
    enter: (node) => {
      if (node.name === 'FencedCode') {
        ranges.push({ from: node.from, to: node.to })
        return false
      }
      return undefined
    },
  })
  return ranges
}

function wikilinkDecorations(state: EditorState): DecorationSet {
  const links = state.field(wikilinksField)
  const visible = excludeFenced(findWikilinkSpans(state.doc.toString()), fencedRanges(state))
  const marks = visible.map((span) => {
    const link = matchingLink(span, links)
    const resolved = isResolved(link)
    return Decoration.mark({
      class: resolved ? 'cm-wikilink cm-wikilink-resolved' : 'cm-wikilink cm-wikilink-unresolved',
      attributes: { title: wikilinkTooltip(span, link) },
    }).range(span.start, span.end)
  })
  return Decoration.set(marks, true)
}

/**
 * SLICES §V5 build-plan step 7's pill: `Decoration.mark` over every `[[...]]` span, recomputed
 * whenever the document or {@link wikilinksField} changes.
 *
 * A mark rather than a widget that replaces the raw text — the underlying `[[KAN-501]]` stays
 * exactly what a person can select and edit, and the pill is styling plus a native tooltip carrying
 * the resolved `KAN-501 · in_progress · "…"` string, the same convention `lib/markdown.ts`'s
 * `unlinked()` uses for a refused preview link.
 */
const wikilinkPills = ViewPlugin.fromClass(
  class {
    decorations: DecorationSet
    constructor(view: EditorView) {
      this.decorations = wikilinkDecorations(view.state)
    }
    update(update: ViewUpdate): void {
      if (
        update.docChanged ||
        update.state.field(wikilinksField) !== update.startState.field(wikilinksField)
      ) {
        this.decorations = wikilinkDecorations(update.state)
      }
    }
  },
  { decorations: (instance) => instance.decorations },
)

/** Where on the current line `[[` completion should trigger, as a **document** offset. */
function triggerAt(context: CompletionContext): { from: number; query: string } | null {
  const line = context.state.doc.lineAt(context.pos)
  const found = wikilinkTrigger(line.text, context.pos - line.from)
  return found === null ? null : { from: line.from + found.from, query: found.query }
}

/**
 * `[[` autocomplete over **existing note titles** (SLICES §V5 build-plan step 7), `GET
 * /api/v1/notes?q=` through `lib/notes.ts`'s already-unshaped `listNotes`.
 *
 * Deliberately narrow: there is no browser-reachable search over pandan's `KAN-`/`EPIC-` cards, so a
 * `[[KAN-501]]` reference is still hand-typed and only pill-decorated once `/links` resolves it —
 * this source only ever offers a note title, and selecting one inserts `Title]]` after the `[[` the
 * person already typed.
 */
async function completeWikilink(context: CompletionContext): Promise<CompletionResult | null> {
  const trigger = triggerAt(context)
  if (trigger === null) {
    return null
  }
  const found = await listNotes({ q: trigger.query === '' ? undefined : trigger.query }).catch(
    () => [],
  )
  if (context.aborted) {
    return null
  }
  const options: Completion[] = found.map((candidate) => ({
    label: candidate.title === '' ? candidate.ref : candidate.title,
    detail: candidate.ref,
    apply: `${candidate.title}]]`,
  }))
  return { from: trigger.from, options, validFor: /^[^[\]\n]*$/ }
}

// --- R14: drop/paste-to-upload (KAN-1067) --------------------------------------------------------

/** The file a `drop` carried, or `null` for a drop that carried none (an internal text drag, a
 *  link dropped from another tab). */
function fileFromDrop(event: DragEvent): File | null {
  return event.dataTransfer?.files.item(0) ?? null
}

/** The file a `paste` carried, or `null` for an ordinary text paste. A paste's `DataTransferItem`
 *  list can hold a file *and* its text representation at once (some OSes offer both for a copied
 *  image), so this returns the first item whose `kind` is `'file'` rather than assuming index 0. */
function fileFromPaste(event: ClipboardEvent): File | null {
  const items = event.clipboardData?.items
  if (items === undefined) {
    return null
  }
  for (const item of items) {
    if (item.kind === 'file') {
      return item.getAsFile()
    }
  }
  return null
}

/**
 * A short, collision-resistant token embedded in the placeholder text {@link uploadDroppedFile}
 * inserts, so the later find-and-replace (`resolvePlaceholder`) matches the exact insertion this
 * upload made rather than a coincidentally identical one from a second drop landed in between.
 * `Math.random`, not `crypto.randomUUID`: this is not a security boundary, only an anti-collision
 * tag inside one document, and `randomUUID` is unavailable in some older embedders' `WebView`s.
 */
function placeholderToken(): string {
  return Math.random().toString(36).slice(2, 10)
}

/**
 * The markdown placeholder shown while an upload is in flight — a real, syntactically valid empty
 * image reference rather than plain text, so it renders as *something* in the preview pane rather
 * than as literal asterisks or brackets while the network round trip is outstanding.
 */
function placeholderText(filename: string, token: string): string {
  const label = filename === '' ? 'file' : filename
  return `![Uploading ${label}… #${token}]()`
}

/**
 * Replace `placeholder` with `replacement`, found by an exact substring search over the **current**
 * document — never by the numeric position the drop/paste handler recorded, which the user may
 * have typed past by the time the upload resolves. CM6 has no "insert at this range, wherever it
 * ends up" primitive that survives an async gap the way a `StateEffect` does across a *synchronous*
 * dispatch; searching for the placeholder's own text is what stands in for one here.
 *
 * If the placeholder is not found — the user deleted it, or edited through it, before the upload
 * settled — this is a silent no-op. Reinserting text the user actively removed would be a surprise
 * edit landing on a document they believe they have finished changing, which is a worse failure
 * than the upload's result simply not appearing.
 */
function resolvePlaceholder(view: EditorView, placeholder: string, replacement: string): void {
  const doc = view.state.doc.toString()
  const at = doc.indexOf(placeholder)
  if (at === -1) {
    return
  }
  view.dispatch({ changes: { from: at, to: at + placeholder.length, insert: replacement } })
}

/**
 * Insert a placeholder at `at`, upload `file` to `noteRef`, and resolve the placeholder to the
 * returned markdown reference — or remove it and report the failure through `onError`.
 *
 * `spec.onSave`/`onChange` are untouched by any of this: an upload is not a save, and CM6's own
 * `updateListener` (wired in {@link createView}) already fires for the placeholder's insertion and
 * its later resolution exactly as it would for anything the person typed, which is what keeps
 * `dirty`/`ondocument` correct without this function knowing either rune exists.
 */
function uploadDroppedFile(
  view: EditorView,
  noteRef: string,
  file: File,
  at: number,
  onError: ((message: string) => void) | undefined,
): void {
  const token = placeholderToken()
  const placeholder = placeholderText(file.name, token)
  view.dispatch({ changes: { from: at, to: at, insert: placeholder } })

  uploadAttachment(noteRef, file).then(
    (attachment) => {
      resolvePlaceholder(view, placeholder, attachment.markdown)
    },
    (failure: unknown) => {
      resolvePlaceholder(view, placeholder, '')
      const message = failure instanceof Error ? failure.message : 'Could not upload the attachment.'
      onError?.(message)
    },
  )
}

/**
 * `EditorView.domEventHandlers` for drop-to-upload and paste-to-upload (R14, KAN-1067).
 *
 * Both handlers return `false` — "not handled, let CM6 and the browser do their ordinary thing" —
 * whenever there is nowhere to upload to (`spec.noteRef === null`, the zero state) or the event
 * carried no file at all, so an ordinary text drop or an ordinary text paste is entirely
 * unaffected: neither handler ever calls `preventDefault` on those.
 */
function attachmentDropPaste(spec: EditorSpec) {
  return EditorView.domEventHandlers({
    drop(event, view) {
      const noteRef = spec.noteRef
      const file = fileFromDrop(event)
      if (noteRef === null || file === null) {
        return false
      }
      event.preventDefault()
      const at = view.posAtCoords({ x: event.clientX, y: event.clientY }) ?? view.state.doc.length
      uploadDroppedFile(view, noteRef, file, at, spec.onAttachmentError)
      return true
    },
    paste(event, view) {
      const noteRef = spec.noteRef
      const file = fileFromPaste(event)
      if (noteRef === null || file === null) {
        return false
      }
      event.preventDefault()
      uploadDroppedFile(view, noteRef, file, view.state.selection.main.head, spec.onAttachmentError)
      return true
    },
  })
}

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
        // KAN-567. `wikilinksField.init` seeds the field from this specific note's initial
        // `/links` answer, which may still be `[]` if `EditorPane.svelte`'s own fetch has not
        // settled yet — `setWikilinks` is how a later answer reaches this same view.
        wikilinksField.init(() => spec.links),
        wikilinkPills,
        autocompletion({ override: [completeWikilink] }),
        // R14 (KAN-1067). Reads `spec.noteRef`/`spec.onAttachmentError` at call time through the
        // closure, same as `onSave`/`onChange` above — there is no rune here to react to a later
        // change, exactly as there is none for those two.
        attachmentDropPaste(spec),
      ],
    }),
  })
}
