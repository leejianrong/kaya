<script lang="ts">
  import { renderMarkdown } from '../lib/markdown'
  import type { Note } from '../lib/types'

  /**
   * KAN-554's live preview: the markdown being edited, rendered as you type.
   *
   * **A sibling of the editor pane, never a child of CM6's subtree** (PLAN §S9, ADR 0001 §2). Nothing
   * here touches the editor's DOM, and this component holds no editor reference at all.
   *
   * **The document arrives through `EditorPane`'s `ondocument` seam**, which `App.svelte` wires into a
   * rune and hands down here as `source`. That is the second design this card had: the first found the
   * live `EditorView` through `EditorView.findFromDOM` and attached its own `updateListener`, because
   * KAN-556 held `EditorPane.svelte` and a card may not edit a file another card is holding. KAN-556
   * landed, so the blocker lifted and the reach was replaced with the seam — `findFromDOM` is public
   * CM6 API, but a cross-component reach into another component's internals is not a seam whichever
   * API makes it possible. V5's wikilink pills and backlinks panel read the same prop.
   *
   * That leaves this component with no imperative machinery and one job: render a string. The
   * `MutationObserver` that used to re-find the view when the editor was rebuilt, and the
   * `StateEffect.appendConfig` that attached the listener, are both gone — a note change now reaches
   * the preview as an ordinary prop update, so there is no ordering hazard left to insure against.
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
  const { note, source }: { note: Note | null; source: string } = $props()

  /** The element `replaceChildren` owns. No template children — see the docstring above. */
  let rendered: HTMLDivElement | undefined = $state()

  $effect(() => {
    const target = rendered
    if (target === undefined) {
      return
    }
    // `replaceChildren` and not an incremental patch: the fragment is the whole rendering, and a
    // preview is cheap to rebuild. A diff here would be a second rendering strategy to keep correct.
    target.replaceChildren(renderMarkdown(source))
  })
</script>

<section class="preview" aria-label="Preview">
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

  /*
    A link this renderer will not make clickable, shown as the markdown that was typed. Same principle
    as the raw-HTML block: a refusal a reader can see beats a silent disappearance. `lib/markdown.ts`
    has the argument, and `title` carries the reason for anyone who hovers.
  */
  .rendered :global(span.unlinked) {
    border-bottom: 1px dotted var(--muted);
    color: var(--muted);
    font-family: var(--mono);
    font-size: 0.9em;
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
