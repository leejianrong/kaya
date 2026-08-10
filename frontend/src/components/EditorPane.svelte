<script lang="ts">
  import { defaultKeymap, history, historyKeymap } from '@codemirror/commands'
  import { markdownKeymap, markdownLanguage } from '@codemirror/lang-markdown'
  import { defaultHighlightStyle, syntaxHighlighting } from '@codemirror/language'
  import { EditorState } from '@codemirror/state'
  import { EditorView, keymap, placeholder } from '@codemirror/view'

  import { ApiError } from '../lib/api'
  import { conflictVersions, needsRemount, syncDocument } from '../lib/editor'
  import { updateNote } from '../lib/notes'
  import type { Note } from '../lib/types'

  const { note, error }: { note: Note | null; error: string | null } = $props()

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
   * ADR 0009's `409`, held whole.
   *
   * KAN-556 renders the side-by-side and keep-mine/keep-theirs out of exactly this. What this card
   * owes it is that the conflict is **reachable and visible** rather than swallowed, with both
   * records intact — so both bodies are here, and the markup below names both timestamps.
   */
  let conflict: { attempted: Note; stored: Note } | null = $state(null)

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

  async function save(): Promise<void> {
    const opened = note
    const current = view
    if (opened === null || current === undefined || saving) {
      return
    }
    const body = current.state.doc.toString()
    const precondition = basedOn

    saving = true
    refusal = null
    conflict = null
    saved = null
    try {
      // `if_updated_at` present is the guarded write; **omitting it is the plain overwrite**, by
      // specification (ADR 0009). There is no `--force` in the CLI and there is no override here, for
      // the same reason: the unguarded write is spelled by not sending something.
      const stored = await updateNote(opened.ref, {
        body,
        ...(precondition === null ? {} : { if_updated_at: precondition }),
      })
      // The next edit is based on the version the server just wrote. Straight off the response, still
      // an opaque string.
      basedOn = stored.updated_at
      // Against the body that was **sent**, not a flat `false`. A save is a round trip and you can
      // type during it; clearing the flag unconditionally would mark those keystrokes saved when the
      // request that finished had never seen them, and the next `409` would be a mystery.
      dirty = current.state.doc.toString() !== body
      saved = `saved · now at ${stored.updated_at}`
    } catch (failure) {
      if (failure instanceof ApiError && failure.isConflict) {
        conflict = conflictVersions(failure.details)
        // A `409` whose extras did not parse is still a `409`. Say so rather than showing nothing.
        refusal = conflict === null ? failure.message : null
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
      ADR 0009's refusal, in the minimal honest form. **This is not the conflict banner** — KAN-556
      owns the side-by-side and keep-mine/keep-theirs, and it is blocked on this card only for the
      two records, which `conflictVersions` hands over whole. What this card owes it is that the
      conflict is impossible to miss and nothing was quietly overwritten.
    -->
    <p class="conflict" data-testid="conflict">
      <strong>Not saved.</strong> This note changed since you opened it, so nothing was written. You
      edited the version stamped
      <code data-testid="conflict-attempted">{conflict.attempted.updated_at}</code>; the stored
      version is <code data-testid="conflict-stored">{conflict.stored.updated_at}</code>. Both
      versions are here in full — KAN-556 turns this line into a side-by-side with keep mine / keep
      theirs.
    </p>
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
