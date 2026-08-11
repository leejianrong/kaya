<script lang="ts">
  import { untrack } from 'svelte'

  import { defaultKeymap, history, historyKeymap, isolateHistory } from '@codemirror/commands'
  import { markdownKeymap, markdownLanguage } from '@codemirror/lang-markdown'
  import { defaultHighlightStyle, syntaxHighlighting } from '@codemirror/language'
  import { EditorState } from '@codemirror/state'
  import { EditorView, keymap, placeholder } from '@codemirror/view'

  import { ApiError } from '../lib/api'
  import { type ConflictVersions, keepMinePatch } from '../lib/conflict'
  import { conflictVersions, needsRemount, syncDocument } from '../lib/editor'
  import { updateNote } from '../lib/notes'
  import type { Note, NoteUpdate } from '../lib/types'
  import ConflictBanner from './ConflictBanner.svelte'

  const {
    note,
    error,
    ondocument,
  }: {
    note: Note | null
    error: string | null
    /**
     * **The document seam: what the editor is showing right now, whenever that changes.**
     *
     * Named for the thing rather than for its first consumer. KAN-554's live preview is one reader;
     * V5's wikilink pills and backlinks panel (KAN-567/568) need the same value, and none of them
     * should have to reach for it. It publishes the **view's** `state.doc`, not the note's `body`,
     * because the two differ the moment you type and every consumer wants what is on screen.
     *
     * Fired once per mounted note with the initial document, then on every `docChanged` transaction —
     * including the ones this component dispatches itself (`syncDocument`, and KAN-556's
     * `keepTheirs`), because from a reader's point of view those are the document changing.
     *
     * ## Two rules this seam must not break, and how it doesn't
     *
     * **It must not re-run the `$effect` below.** The callback is read through {@link untrack} in
     * {@link publish}, so a parent that hands down a new closure per render — the ordinary case, since
     * the parent's own state changes on every keystroke it receives — cannot make this component's
     * mount effect a dependency of its own output. That matters most because `syncDocument` dispatches
     * *from inside* that effect: without `untrack`, the prop would be read while the effect was
     * collecting dependencies, and a per-keystroke effect re-run would be one closure identity away.
     * `needsRemount` still takes no body parameter, so even a re-run could not remount.
     *
     * **It must not put a Svelte node in CM6's subtree** (PLAN §S9). It cannot: it hands a `string`
     * out and takes nothing back, so a consumer renders into its own element or nowhere.
     */
    ondocument?: (document: string) => void
  } = $props()

  /**
   * Hand the current document to {@link ondocument}, if anyone asked for it.
   *
   * `untrack` is the load-bearing word — see the prop's docstring. It is *reading the prop* that has
   * to be untracked, not calling it, which is why the read is inside the callback rather than hoisted.
   */
  function publish(document: string): void {
    untrack(() => ondocument)?.(document)
  }

  /**
   * The element CodeMirror owns.
   *
   * PLAN §S9 and ADR 0001 §2: **Svelte never renders inside CM6's subtree.** KAN-552 put this
   * boundary in before the editor existed, precisely so this card would not have to move it, and
   * `tests/editor-container.test.ts` parses this file to assert the container below has zero template
   * children. Nothing in the markup may put a node in there — not a word of text, not an `{#if}`,
   * not a `{@html}` — because from that moment CM6's transactions and Svelte's rerenders are editing
   * one subtree and PLAN §Open risks' update loop is live.
   */
  let host: HTMLDivElement | undefined = $state()

  /**
   * The live view, the ref it was built for, and ADR 0009's precondition. **Plain `let`, not
   * `$state`.**
   *
   * `view` and `mountedRef` are read *and* written by the `$effect` below, and a rune that an effect
   * both reads and writes is an effect that retriggers itself — the update loop again, arriving
   * through the reactivity system instead of through CM6. They are bookkeeping for an imperative
   * object, they are never read by the markup, and so they must stay outside the graph.
   *
   * `basedOn` is different and *is* a rune: the header shows it, and it has to change when a save
   * returns a new stamp.
   */
  let view: EditorView | undefined
  let mountedRef: string | null = null
  /**
   * The last body this component took **from the prop**, and the reason it exists is data loss.
   *
   * The echo guard asks "is this already the document?"; this asks "is this even an update?". They
   * catch disjoint cases and neither covers the other. A parent that hands down a *new object with
   * unchanged content* while you are typing — which is exactly the parent the identity guard is
   * written for — produces an incoming body that differs from the editor's document (you typed) but
   * is not new (nobody changed the note). Dispatching there would replace your in-flight edit with
   * the server's copy, silently, on a re-render that changed nothing. So the incoming document is
   * only applied when the *source* moved, and the echo guard then decides whether that value needs a
   * transaction at all.
   */
  let appliedBody = ''

  /**
   * The `updated_at` this edit is based on — ADR 0009's precondition, carried as an **opaque
   * string**.
   *
   * Never parsed, never reformatted, never round-tripped through a `Date`. The comparison on the
   * backend is exact to the microsecond and `new Date(s).toISOString()` rounds to milliseconds, so a
   * token touched anywhere on this path refuses *every* correct write. It is set from the note the
   * view was built for and re-set from the **response** of a successful save; nothing here ever
   * fetches it. A read-before-write would look safer and would disable the guarantee — the token
   * would then name a version read microseconds ago rather than the version this edit was made
   * against, so the `409` would only fire on a race inside that window.
   */
  let basedOn: string | null = $state(null)

  let dirty = $state(false)
  let saving = $state(false)
  /** What the last save did, as one line. Cleared by the next edit. */
  let saved: string | null = $state(null)
  /** A refusal that is not ADR 0009's, or one whose two versions did not parse. */
  let refusal: string | null = $state(null)
  /**
   * ADR 0009's `409`, held whole — and what `ConflictBanner` renders (KAN-556).
   *
   * Both notes arrive complete because a side-by-side of two prose bodies needs both bodies whole
   * (`backend/app/api/concurrency.py`), and a client cannot reconstruct one from a patch it no longer
   * holds. Cleared on a successful resolution and **replaced** by a fresh `409`, never cleared at the
   * *start* of a write: the banner has to stay on the screen while the resolution it launched is in
   * flight, or the buttons vanish under the cursor.
   */
  let conflict: ConflictVersions | null = $state(null)
  /**
   * Whether the stored version moved *between* two refusals.
   *
   * The note can change again while the banner is open — that is the whole shape of this feature —
   * and "keep mine" is guarded, so it can be refused a second time by a third writer. Comparing the
   * two `stored` stamps is what tells a genuinely new conflict from the same one refused again (a
   * plain Save after a `409` re-sends the same stale precondition and is refused identically, which
   * is correct and is *not* news).
   */
  let movedAgain = $state(false)
  /**
   * What a resolution that made no request did, as one line. Cleared by the next edit.
   *
   * Separate from `saved` because "kept theirs" is emphatically not a save: nothing was written, and
   * saying `saved` there would claim the server holds text it does not.
   */
  let resolution: string | null = $state(null)

  /**
   * Mount CodeMirror once per note, and hand it every later document as a transaction.
   *
   * **Reading the `note` prop registers it as a dependency**, so this effect re-runs whenever the
   * parent hands down a new object — per keystroke, if some future parent does that. That is not
   * avoidable by reading a narrower field: `note.ref` and `note.body` are the same signal read.
   * What is avoidable is *remounting*, which is what {@link needsRemount} decides.
   *
   * **So the teardown is not in this effect's cleanup, and that is a deliberate departure from
   * KAN-552's rehearsal.** Svelte runs an effect's cleanup *before* every re-run, so a
   * `return () => view.destroy()` here would destroy the view on the very content change the
   * identity guard exists to survive — the guard would return early into a view that had already
   * been torn down. The per-note destroy therefore sits in the body, immediately beside the
   * construction it replaces, and the per-component destroy is the second effect below, which reads
   * nothing and whose cleanup can only fire on unmount.
   */
  $effect(() => {
    const parent = host
    const opened = note
    if (parent === undefined) {
      return
    }
    const incomingRef = opened?.ref ?? null
    const incomingBody = opened?.body ?? ''

    // --- Guard 1 of 2: the identity guard (see lib/editor.ts). ---
    if (!needsRemount(view !== undefined, mountedRef, incomingRef)) {
      // Same note, so the document goes in as a transaction and never as a remount — but only if the
      // prop actually moved (see `appliedBody`), and then only if guard 2 of 2 — the echo guard,
      // inside `syncDocument` — finds it is not already the value the editor holds.
      if (incomingBody !== appliedBody) {
        appliedBody = incomingBody
        syncDocument(view as EditorView, incomingBody)
      }
      return
    }

    view?.destroy()
    view = build(parent, opened)
    mountedRef = incomingRef
    appliedBody = incomingBody
    basedOn = opened?.updated_at ?? null
    dirty = false
    saved = null
    refusal = null
    conflict = null
    movedAgain = false
    resolution = null
    // A newly built view has a document nobody has been told about — no transaction happened, so the
    // update listener never fired. Read it off the view rather than from `incomingBody`, so the seam's
    // one promise ("what the editor is showing") is true even if those two ever diverge.
    publish(view.state.doc.toString())
  })

  /**
   * The component's own teardown. Reads nothing, so it runs once and its cleanup fires only when the
   * component is destroyed — which is what makes it safe to put `view.destroy()` in.
   *
   * SLICES §V3 asks for "mounts once per note and tears down cleanly on navigation (no leaked
   * listeners)". Navigation is the effect above; this is the pane going away.
   */
  $effect(() => {
    return () => {
      view?.destroy()
      view = undefined
      mountedRef = null
    }
  })

  /** The extension set, and the one place a new CodeMirror package would have to earn its bytes. */
  function build(parent: HTMLElement, opened: Note | null): EditorView {
    const editable = opened !== null
    return new EditorView({
      parent,
      state: EditorState.create({
        doc: opened?.body ?? '',
        extensions: [
          // Undo history is part of what the identity guard protects: a remount per keystroke would
          // throw this away silently, so it is here from the first commit rather than later.
          history(),
          keymap.of([
            { key: 'Mod-s', preventDefault: true, run: onSaveKey },
            ...markdownKeymap,
            ...historyKeymap,
            ...defaultKeymap,
          ]),
          // **`markdownLanguage.extension`, not `markdown()`, and this is a measurement rather than a
          // preference.** Both give the same GFM grammar; `markdown()` additionally wires
          // `@codemirror/lang-html` in as the parser for raw HTML blocks, and lang-html drags
          // `lang-javascript` and `lang-css` behind it for embedded script and style tags. (Do not
          // write those two tag names literally in this file: a bare opening script tag anywhere in a
          // Svelte component's source — comment or not — makes svelte-check report the real one as
          // left open, four files away.) Measured on this tree with esbuild, minified:
          // `markdown()` costs **500,618 B raw / 171,369 B gzip -9** against
          // **312,798 / 101,872** for the language plus its keymap — **187,820 B raw / 69,497 B gzip**
          // for highlighting HTML that a markdown note rarely contains. `markdownKeymap` is imported
          // explicitly because it is the part of `markdown()` worth keeping (Enter continues a list),
          // and taking it by name is what lets the html import tree-shake away.
          //
          // If you replace this with `markdown()`, the bundle grows by two thirds of the editor.
          // Fenced-code sub-language highlighting is what that would buy, and no card asks for it.
          markdownLanguage.extension,
          syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
          EditorView.lineWrapping,
          EditorView.editable.of(editable),
          // The zero states, as CM6's own placeholder rather than as a Svelte node — the container
          // has no template children and this is why it does not need any.
          placeholder(editable ? 'Write markdown…' : 'No note open.'),
          // Out through the update listener, as ADR 0001 §2 requires. It sets runes the effect above
          // never reads, so our own wiring cannot cycle; the echo guard is what holds when someone
          // else's wiring does.
          EditorView.updateListener.of((update) => {
            if (update.docChanged) {
              dirty = true
              saved = null
              // Including the transaction `keepTheirs` dispatches — from CM6's side that is an edit
              // like any other, which is why that function sets its own two runes *after* the
              // dispatch rather than before it.
              resolution = null
              // The document seam. `update.state.doc` and not the note's `body`: this is the value on
              // screen, which is the only one a preview or a link panel can honestly render.
              publish(update.state.doc.toString())
            }
          }),
          theme,
        ],
      }),
    })
  }

  /**
   * CM6 keybindings are synchronous and return whether they handled the key. The save is not, so the
   * promise is deliberately dropped here and every failure is reported through the runes below.
   */
  function onSaveKey(): boolean {
    void save()
    return true
  }

  /** The Save button and `Mod-s`: the document as it stands, guarded on the version it was based on. */
  function save(): Promise<void> {
    const current = view
    if (current === undefined) {
      return Promise.resolve()
    }
    // `if_updated_at` present is the guarded write; **omitting it is the plain overwrite**, by
    // specification (ADR 0009). There is no `--force` in the CLI and there is no override here, for
    // the same reason: the unguarded write is spelled by not sending something.
    const precondition = basedOn
    return write({
      body: current.state.doc.toString(),
      ...(precondition === null ? {} : { if_updated_at: precondition }),
    })
  }

  /**
   * "Keep mine": the refused write again, aimed at the version that refused it.
   *
   * The crossing — `body` from `attempted`, `if_updated_at` from `stored` — is
   * {@link keepMinePatch}, and it is a pure function in `lib/conflict.ts` rather than three lines
   * here because it is the **second** place in this SPA a precondition is built. Both stamps stay
   * opaque strings; a `Date` anywhere on either path refuses every correct write.
   */
  function keepMine(): Promise<void> {
    const versions = conflict
    return versions === null ? Promise.resolve() : write(keepMinePatch(versions))
  }

  /**
   * "Keep theirs": **no request at all**, and the caller's text is replaced in place.
   *
   * Nothing needs writing, because the stored version already *is* what the server holds — the whole
   * `409` was kaya refusing to overwrite it. So this is a discard, and three things make it one the
   * user is not surprised by:
   *
   * - The stored body goes in through `syncDocument`, the same **transaction** every external update
   *   uses (PLAN §S9: never a remount). So CM6's undo history survives, and the discarded text is one
   *   ⌘/Ctrl-Z away for as long as the pane lives. The banner says so before the click, and
   *   `resolution` says it again after. That is the only copy there is — ADR 0009 §Consequences:
   *   there is no revision history, so "keep theirs" really does discard.
   *   **`isolateHistory` is what makes "one undo" true**, and it was found by the test for it going
   *   red rather than reasoned out: CM6 groups adjacent changes into one history event, so a discard
   *   clicked within `newGroupDelay` (500 ms) of the last keystroke merged into the user's own typing
   *   and a single undo threw *that* away as well — the promise on the button reversing itself into
   *   the data loss ADR 0009 exists to prevent. `'full'` isolates on both sides, so a keystroke
   *   afterwards cannot join the discard's event either.
   * - `basedOn` becomes the stored stamp, so the *next* save is guarded against the version now in
   *   the editor. Leaving it would refuse that save with the stale precondition it already refused.
   * - `dirty` is cleared **after** the dispatch, because the update listener sets it: the document
   *   now equals the stored body, so there is genuinely nothing unsaved.
   *
   * `appliedBody` is deliberately *not* touched. It means "the last body taken from the prop", and
   * this body did not come from the prop — writing it here would make a later re-render carrying the
   * (older) prop body look like an update and dispatch it straight over the version just chosen.
   */
  function keepTheirs(): void {
    const versions = conflict
    const current = view
    if (versions === null || current === undefined || saving) {
      return
    }
    syncDocument(current, versions.stored.body, [isolateHistory.of('full')])
    basedOn = versions.stored.updated_at
    dirty = false
    conflict = null
    movedAgain = false
    refusal = null
    saved = null
    resolution = 'kept theirs · your text is one undo away (⌘/Ctrl-Z) until you edit again'
  }

  /**
   * The one `PATCH` in this component, shared by the Save button and by "keep mine".
   *
   * One write path rather than two, so the precondition is forwarded the same way whichever button
   * asked — and so a future card cannot fix a bug in one of them. What differs between the callers is
   * only *which* body and *which* stamp go in, which is exactly what the parameter is.
   *
   * `conflict` is not cleared on the way in. The banner must survive its own resolution's round trip,
   * and a fresh `409` replaces it below rather than flickering through empty.
   */
  async function write(update: NoteUpdate): Promise<void> {
    const opened = note
    const current = view
    if (opened === null || current === undefined || saving) {
      return
    }

    saving = true
    refusal = null
    saved = null
    resolution = null
    try {
      const stored = await updateNote(opened.ref, update)
      // The next edit is based on the version the server just wrote. Straight off the response, still
      // an opaque string.
      basedOn = stored.updated_at
      // Against the body that was **sent**, not a flat `false`. A save is a round trip and you can
      // type during it; clearing the flag unconditionally would mark those keystrokes saved when the
      // request that finished had never seen them, and the next `409` would be a mystery. It is also
      // what leaves the pane honest after a "keep mine" the user typed past.
      dirty = current.state.doc.toString() !== update.body
      saved = `saved · now at ${stored.updated_at}`
      conflict = null
      movedAgain = false
    } catch (failure) {
      if (failure instanceof ApiError && failure.isConflict) {
        const versions = conflictVersions(failure.details)
        // Two `stored` stamps apart, not "a second 409": a plain Save after a refusal re-sends the
        // same stale precondition and is refused identically, which is correct and is not news. The
        // note having moved *again* while the banner was open is.
        const previous = conflict?.stored.updated_at ?? null
        movedAgain = versions !== null && previous !== null && previous !== versions.stored.updated_at
        conflict = versions
        // A `409` whose extras did not parse is still a `409`. Say so rather than showing nothing.
        refusal = versions === null ? failure.message : null
      } else {
        refusal = failure instanceof Error ? failure.message : 'Could not save.'
      }
    } finally {
      saving = false
    }
  }

  /**
   * CM6 injects its own CSS through `style-mod` at runtime, so this theme costs JavaScript rather
   * than stylesheet — and it reads `app.css`'s tokens, so the editor is one surface with the app in
   * both colour schemes instead of a light rectangle inside a dark page.
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
</script>

<section class="pane" aria-label="Editor">
  {#if error}
    <p class="notice">{error}</p>
  {:else if note}
    <header>
      <h2>{note.title}</h2>
      <p class="meta">
        <code>{note.ref}</code>
        <!-- A note may legitimately have no path (ADR 0008: path is metadata, not identity), and
             two of the seeded notes do. Say so rather than rendering an empty element. -->
        <span class="path">{note.path === '' ? '(no path)' : note.path}</span>
        <!-- `basedOn` and not `note.updated_at`: after a save the prop is stale, and the version
             this edit is guarded against is the only honest thing to show here. -->
        <span class="stamp" title="ADR 0009's precondition, carried as an opaque string"
          >based on {basedOn}</span
        >
      </p>
    </header>

    <div class="bar">
      <button type="button" onclick={() => void save()} disabled={saving || !dirty}>
        {saving ? 'Saving…' : 'Save'}
      </button>
      <span class="hint">⌘/Ctrl-S</span>
      <span class="state" data-testid="save-state">
        <!-- `dirty` outranks `saved`, because you can type during a round trip: a save that
             finished is old news the moment the document moved past what it sent. -->
        {#if saving}
          saving…
        {:else if dirty}
          unsaved changes
        {:else if saved}
          {saved}
        {:else if resolution}
          <!-- A resolution that wrote nothing. It cannot say `saved`, because the server does not
               hold this text — see `keepTheirs`. -->
          {resolution}
        {:else}
          no changes
        {/if}
      </span>
    </div>
  {:else}
    <p class="notice">Pick a note from the sidebar.</p>
  {/if}

  {#if conflict}
    <!--
      ADR 0009's affordance (KAN-556), and a **sibling** of the editor container below — never a
      child of it. PLAN §S9: Svelte renders nothing inside CM6's subtree, and a banner that grew into
      the editor's element would be the update loop with a friendly face.

      The banner writes nothing. This component owns the write path, the precondition and the view, so
      both buttons come back here: `keepMine` re-`PATCH`es and `keepTheirs` dispatches a transaction.
    -->
    <ConflictBanner
      versions={conflict}
      busy={saving}
      {movedAgain}
      onkeepmine={() => void keepMine()}
      onkeeptheirs={keepTheirs}
    />
  {/if}

  {#if refusal}
    <p class="conflict" data-testid="save-error">{refusal}</p>
  {/if}

  <!--
    S9's container. Svelte owns this element and **never its children** — no {#if}, no {#each},
    no {@html}, no text interpolation may go inside it. `new EditorView({ parent })` is the only
    thing that writes in here, and `tests/editor-container.test.ts` asserts over this file's parsed
    template that it stays that way.
  -->
  <div class="editor-host" bind:this={host}></div>
</section>

<style>
  .pane {
    display: flex;
    flex-direction: column;
    gap: 1rem;
    min-width: 0;
    height: 100%;
    padding: 1.5rem;
  }

  h2 {
    margin: 0;
    font-size: 1.35rem;
    letter-spacing: -0.01em;
  }

  .meta {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem;
    margin: 0.35rem 0 0;
    color: var(--muted);
    font-size: 0.85rem;
  }

  .stamp {
    font-family: var(--mono);
  }

  .notice {
    margin: 0;
    color: var(--muted);
  }

  .bar {
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }

  button {
    padding: 0.35rem 0.9rem;
    border: 1px solid var(--edge);
    border-radius: 0.35rem;
    color: var(--paper);
    background: var(--accent);
    font: inherit;
    font-size: 0.85rem;
    cursor: pointer;
  }

  button:disabled {
    color: var(--muted);
    background: transparent;
    cursor: default;
  }

  .hint,
  .state {
    color: var(--muted);
    font-family: var(--mono);
    font-size: 0.75rem;
  }

  .conflict {
    margin: 0;
    padding: 0.75rem 1rem;
    border: 1px solid var(--edge);
    border-left: 3px solid var(--accent);
    border-radius: 0.35rem;
    font-size: 0.85rem;
  }

  .editor-host {
    flex: 1;
    min-height: 12rem;
    overflow: auto;
    padding: 0.25rem 0;
    border: 1px solid var(--edge);
    border-radius: 0.4rem;
  }
</style>
