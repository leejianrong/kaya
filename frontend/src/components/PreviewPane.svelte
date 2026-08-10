<script lang="ts">
  import { untrack } from 'svelte'

  import { trackEditor, watchDocument } from '../lib/livedoc'
  import { renderMarkdown } from '../lib/markdown'
  import type { Note } from '../lib/types'

  /**
   * KAN-554's live preview: the markdown being edited, rendered as you type.
   *
   * **A sibling of the editor pane, never a child of CM6's subtree** (PLAN §S9, ADR 0001 §2). Nothing
   * here touches the editor's DOM; it reads the view's `state.doc` and writes into its own element.
   *
   * **The document arrives laterally.** `lib/livedoc.ts` has the argument in full: the preview
   * attaches its own `updateListener` to the live `EditorView`, so no keystroke passes through a prop
   * or through the parent's state, and therefore nothing the preview does can re-run the `$effect`
   * that owns the editor. `tests/preview.test.ts` asserts both halves — the preview follows the
   * document, and the parent's `note` object is the same object afterwards.
   *
   * **The rendered content is built imperatively, and that is the security decision.** `renderMarkdown`
   * returns a `DocumentFragment` of elements this repo named and `Text` nodes holding the author's
   * bytes; there is no HTML string anywhere on the path, so there is no `{@html}` here and no escaping
   * function that could have a bug in it. `tests/no-html-injection.test.ts` asserts the absence
   * structurally, over `src/`.
   *
   * That makes `.rendered` a second Svelte-owns-the-element-never-its-children boundary, for a
   * different reason than the editor's: not an update loop, but the fact that a `{#if}` or an
   * interpolation in there would be Svelte writing into a subtree `replaceChildren` replaces whole.
   */
  const { note }: { note: Note | null } = $props()

  /**
   * The region the editor lives in — this component's own parent.
   *
   * `parentElement` rather than a prop, because it is the same fact either way and a prop would put
   * the layout's shape in two files: `App.svelte` places the preview beside the editor, and "beside"
   * is exactly what `parentElement` means. `lib/livedoc.ts` only needs a `ParentNode` containing the
   * view.
   */
  let host: HTMLElement | undefined = $state()

  /** The element `replaceChildren` owns. No template children — see the docstring above. */
  let rendered: HTMLDivElement | undefined = $state()

  /** The document on screen in the editor. Written only by the watcher below. */
  let doc = $state('')

  $effect(() => {
    const region = host?.parentElement ?? null
    // The **ref**, so this re-runs per note: `EditorPane` rebuilds its view when the open note
    // changes, and a listener on the destroyed one would leave the preview on the previous note.
    const openedRef = note?.ref ?? null

    if (openedRef === null || region === null) {
      doc = ''
      return
    }

    // A seed for the frame before the view is found, `untrack`ed so reading it does not make this
    // effect depend on the *body*. It must not: the parent's copy goes stale the moment you type, and
    // an effect that re-ran on it would reseed the preview from the stale value. `watchDocument`
    // publishes the editor's real document immediately on attach and overwrites this.
    doc = untrack(() => note?.body ?? '')

    let unwatch: (() => void) | null = null
    const stop = trackEditor(region, (view) => {
      unwatch?.()
      unwatch = view === null ? null : watchDocument(view, (text) => (doc = text))
    })

    return () => {
      unwatch?.()
      stop()
    }
  })

  $effect(() => {
    const target = rendered
    if (target === undefined) {
      return
    }
    // `replaceChildren` and not an incremental patch: the fragment is the whole rendering, and a
    // preview is cheap to rebuild. A diff here would be a second rendering strategy to keep correct.
    target.replaceChildren(renderMarkdown(doc))
  })
</script>

<section class="preview" aria-label="Preview" bind:this={host}>
  <header>
    <h2>Preview</h2>
    {#if note === null}
      <span class="hint">nothing open</span>
    {/if}
  </header>
  <div class="rendered" data-testid="preview" bind:this={rendered}></div>
</section>

<style>
  .preview {
    display: flex;
    flex-direction: column;
    gap: 1rem;
    min-width: 0;
    height: 100%;
    padding: 1.5rem 1.5rem 1.5rem 0;
  }

  header {
    display: flex;
    align-items: baseline;
    gap: 0.5rem;
  }

  h2 {
    margin: 0;
    color: var(--muted);
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  .hint {
    color: var(--muted);
    font-family: var(--mono);
    font-size: 0.75rem;
  }

  .rendered {
    flex: 1;
    min-width: 0;
    overflow: auto;
    padding: 0.75rem 1rem;
    border: 1px solid var(--edge);
    border-radius: 0.4rem;
    line-height: 1.6;
  }

  /*
    Every rule below is `:global`, because every node it describes was made by `renderMarkdown` and
    not by Svelte — so none of them carries a scoping class. The `.rendered` prefix is scoped, which
    keeps the reach of these rules to this component's own subtree.
  */
  .rendered :global(> :first-child) {
    margin-top: 0;
  }

  .rendered :global(h1),
  .rendered :global(h2),
  .rendered :global(h3),
  .rendered :global(h4),
  .rendered :global(h5),
  .rendered :global(h6) {
    margin: 1.2em 0 0.4em;
    letter-spacing: -0.01em;
    line-height: 1.3;
  }

  .rendered :global(h1) {
    font-size: 1.5rem;
  }

  .rendered :global(h2) {
    font-size: 1.25rem;
  }

  .rendered :global(h3) {
    font-size: 1.05rem;
  }

  .rendered :global(p),
  .rendered :global(ul),
  .rendered :global(ol),
  .rendered :global(blockquote),
  .rendered :global(pre),
  .rendered :global(table) {
    margin: 0 0 0.75em;
  }

  .rendered :global(ul),
  .rendered :global(ol) {
    padding-left: 1.4rem;
  }

  .rendered :global(li) {
    margin: 0.1em 0;
  }

  .rendered :global(p.task) {
    display: flex;
    align-items: baseline;
    gap: 0.4rem;
    margin: 0;
  }

  .rendered :global(blockquote) {
    padding-left: 0.9rem;
    border-left: 3px solid var(--edge);
    color: var(--muted);
  }

  .rendered :global(code) {
    padding: 0.1em 0.3em;
    border-radius: 0.2rem;
    background: color-mix(in srgb, var(--ink) 8%, transparent);
    font-family: var(--mono);
    font-size: 0.85em;
  }

  .rendered :global(pre) {
    overflow-x: auto;
    padding: 0.6rem 0.8rem;
    border-radius: 0.3rem;
    background: color-mix(in srgb, var(--ink) 6%, transparent);
  }

  .rendered :global(pre code) {
    padding: 0;
    background: transparent;
  }

  /*
    Raw HTML from a note body, shown as text. The label is CSS content rather than a node, so the
    element still holds exactly the author's bytes and nothing else — see `lib/markdown.ts`.
  */
  .rendered :global(pre.raw-html) {
    border-left: 3px solid var(--accent);
  }

  .rendered :global(pre.raw-html)::before {
    display: block;
    margin-bottom: 0.3rem;
    color: var(--muted);
    content: 'raw HTML, not rendered';
    font-family: var(--mono);
    font-size: 0.7rem;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }

  .rendered :global(table) {
    border-collapse: collapse;
    font-size: 0.9em;
  }

  .rendered :global(th),
  .rendered :global(td) {
    padding: 0.3rem 0.6rem;
    border: 1px solid var(--edge);
    text-align: left;
  }

  .rendered :global(hr) {
    margin: 1.2em 0;
    border: 0;
    border-top: 1px solid var(--edge);
  }

  .rendered :global(img) {
    max-width: 100%;
  }

  .rendered :global(a) {
    color: var(--accent);
  }
</style>
