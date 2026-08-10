<!-- KAN-553 replaces this file: CodeMirror 6 mounts into the element this component owns. -->
<script lang="ts">
  import type { Note } from '../lib/types'

  const { note, error }: { note: Note | null; error: string | null } = $props()

  /**
   * The element CodeMirror will own.
   *
   * PLAN §S9 and ADR 0001 §2: **Svelte never renders inside CM6's subtree.** That is the only
   * frontend unknown in PLAN §Open risks with teeth — a rune bound naively to the document, with
   * Svelte also emitting DOM in there, gives you an update loop that looks like a performance
   * problem and is actually a correctness one.
   *
   * So the shape is fixed here, before the editor exists, because it is most of what makes KAN-553
   * safe: Svelte owns *this element*, and everything inside it is written imperatively. The
   * `$effect` below is a rehearsal of the one that will construct an `EditorView` — same
   * boundary, same teardown, no library yet.
   *
   * **KAN-553: that effect must re-run on note *identity* and never on note content.** Reading the
   * `note` prop at all registers it, so a parent handing down a new object per keystroke re-runs
   * this effect whichever field you read — destroying and rebuilding the `EditorView` on every
   * character, losing the selection, the undo history and the scroll position with it. Compare the
   * incoming `note.ref` against the ref the view was built for and return early when they match;
   * the document goes in as a transaction, never as a remount. That is the loop PLAN §Open risks
   * warns about wearing different clothes, and this is the file its author will be reading.
   */
  let host: HTMLDivElement | undefined = $state()

  $effect(() => {
    const parent = host
    if (!parent) {
      return
    }

    // Imperative, exactly as `new EditorView({ parent })` will be. Nothing in the markup below
    // puts a node in here, so nothing Svelte owns can be invalidated by what CM6 does to it.
    const placeholder = document.createElement('p')
    placeholder.className = 'editor-placeholder'
    placeholder.textContent = note
      ? 'CodeMirror 6 mounts here (KAN-553). The body below is read-only for now.'
      : 'No note open.'
    parent.append(placeholder)

    // The teardown KAN-553 replaces with `view.destroy()`. SLICES §V3 asks for "mounts once per
    // note and tears down cleanly on navigation"; this is where that is proven.
    return () => {
      placeholder.remove()
    }
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
        <span class="stamp" title="ADR 0009's precondition, carried as an opaque string"
          >updated {note.updated_at}</span
        >
      </p>
    </header>
  {:else}
    <p class="notice">Pick a note from the sidebar.</p>
  {/if}

  <!--
    S9's container. Svelte owns this element and **never its children** — no {#if}, no {#each},
    no {@html}, no text interpolation may go inside it, in this card or in KAN-553. The moment
    anything above emits a node in here, CM6's transactions and Svelte's rerenders are editing the
    same subtree, and PLAN §Open risks' update loop is live.
  -->
  <div class="editor-host" bind:this={host}></div>

  {#if note}
    <!-- Read-only, and deliberately not the live preview: KAN-554 owns rendering markdown to HTML
         (which is presentation, not payload shaping — see lib/api.ts). -->
    <pre class="body">{note.body}</pre>
  {/if}
</section>

<style>
  .pane {
    display: flex;
    flex-direction: column;
    gap: 1rem;
    min-width: 0;
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

  .editor-host {
    min-height: 6rem;
    padding: 0.75rem 1rem;
    border: 1px dashed var(--edge);
    border-radius: 0.4rem;
    color: var(--muted);
    font-size: 0.9rem;
  }

  .body {
    margin: 0;
    overflow-x: auto;
    padding: 1rem;
    border-top: 1px solid var(--edge);
    font-family: var(--mono);
    font-size: 0.85rem;
    white-space: pre-wrap;
    word-break: break-word;
  }
</style>
