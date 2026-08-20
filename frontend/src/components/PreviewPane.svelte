<script lang="ts">
  import type { Note } from '../lib/types'

  /**
   * `lib/markdown.ts`, named as a **type** so naming it costs nothing.
   *
   * `typeof import(…)` is erased by `verbatimModuleSyntax` exactly like an `import type` is, so this
   * line does not put the renderer — or the `@lezer/markdown` grammar it walks — in the entry chunk.
   * The only thing that reaches it is the `import()` in the loader effect below, which is what makes
   * it a chunk of its own. Same shape, and the same reasoning, as `EditorPane.svelte`'s `EditorKit`.
   */
  type Renderer = typeof import('../lib/markdown')

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
   *
   * **The renderer arrives on its own chunk (KAN-836), and the loader is deliberately not in the
   * effect that renders.** See {@link renderer} for the whole of that argument.
   */
  const { note, source }: { note: Note | null; source: string } = $props()

  /** The element `replaceChildren` owns. No template children — see the docstring above. */
  let rendered: HTMLDivElement | undefined = $state()

  /**
   * The renderer, once it has arrived — **KAN-836, and the only reason this component is
   * asynchronous at all.**
   *
   * `lib/markdown.ts` walks `@lezer/markdown`'s syntax tree, and that grammar is **20,362 B gzip -9**
   * of parser. KAN-767 moved CodeMirror out of the entry chunk and this was what was left: 43% of the
   * remaining entry, paid by an unauthenticated visitor pasting a PAT into a password field and by a
   * signed-in user sitting on `/`, neither of whom can see a rendered byte. Same argument as KAN-767,
   * one layer down — the bytes are not wrong, the *time* they arrived was.
   *
   * **It is a rune, and the render effect below *reads* it — so that effect stays synchronous.** The
   * obvious implementation is `await import('../lib/markdown')` at the top of the render effect, and
   * it is wrong here for a reason that is *not* the editor's. `EditorPane` risks two views in one host
   * or an orphan whose `destroy()` is never called, because it builds a stateful object and owns a
   * teardown; this component builds nothing and tears nothing down — `replaceChildren` is total and
   * idempotent, so a second run cannot leak the first. What an `await` costs here is the
   * **subscription**: Svelte registers an effect's dependencies during its *synchronous* pass only, so
   * `source` read after an `await` is not a dependency at all. The preview would render the document
   * it was mounted with and then never move again — no error, no leak, and nothing in the DOM to look
   * at. (`tests/preview-lazy-render.test.ts` is the alarm; the mutation was run and it is the test
   * that goes red.) The lesser cost is ordering: two awaited runs resolve in whatever order their
   * promises settle, so a stale document can land on top of a fresh one.
   *
   * Reading a rune instead means the load resolves **once** per component, in the effect below that
   * reads nothing, and every render after that is the same straight-line code KAN-554 wrote. Only the
   * *first* render waits for a chunk; a keystroke still renders inside its own flush.
   */
  let renderer: Renderer | null = $state(null)

  /**
   * The renderer's chunk never arrived (KAN-836). Rendered as a notice, **beside** `.rendered`.
   *
   * A lazy chunk is one more request, so it is one more thing that can fail — offline, or a deploy
   * that replaced the asset while this tab was open. Unhandled, the symptom is an empty bordered
   * rectangle beside an editor that works, which reads as "this note is empty" and is the worst answer
   * available. The notice is a sibling for the same reason `EditorPane`'s is: an element whose children
   * belong to `replaceChildren` cannot hold the sentence explaining why `replaceChildren` never ran.
   */
  let unavailable: string | null = $state(null)

  /**
   * The component's one once-per-lifetime job: **fetch the renderer.**
   *
   * Reads nothing, so it runs exactly once — which is the property the render effect below leans on
   * when it treats `renderer` as a value that only ever arrives. `live` stops a component unmounted
   * mid-flight from assigning a rune afterwards; as in `EditorPane`, what actually holds the property
   * is the shape rather than the flag.
   */
  $effect(() => {
    let live = true
    import('../lib/markdown').then(
      (loaded) => {
        if (live) {
          renderer = loaded
        }
      },
      () => {
        if (live) {
          unavailable = 'The preview could not be loaded. Reload the page to try again.'
        }
      },
    )
    return () => {
      live = false
    }
  })

  $effect(() => {
    // All three reads are **above** the guard, because that is what registers them as dependencies.
    // Returning before the `source` read would leave this effect unsubscribed from the document and
    // the preview would freeze on whatever it first rendered — which is exactly the failure an
    // `await` at the top of this effect produces, by moving the read out of the synchronous pass.
    const target = rendered
    const loaded = renderer
    const markdown = source
    if (target === undefined || loaded === null) {
      return
    }
    // `replaceChildren` and not an incremental patch: the fragment is the whole rendering, and a
    // preview is cheap to rebuild. A diff here would be a second rendering strategy to keep correct.
    target.replaceChildren(loaded.renderMarkdown(markdown))
  })
</script>

<section class="preview" aria-label="Preview">
  <header>
    <h2>Preview</h2>
    {#if note === null}
      <span class="hint">nothing open</span>
    {/if}
  </header>
  {#if unavailable}
    <!-- KAN-836's lazy chunk failing to arrive. A **sibling** of the element below, for the same
         reason `EditorPane`'s notice is a sibling of S9's container: `.rendered`'s children belong
         to `replaceChildren`, which is precisely what did not run. -->
    <p class="notice" data-testid="preview-unavailable">{unavailable}</p>
  {/if}

  <!--
    The rendered document. Svelte owns this element and **never its children** — no {#if}, no
    {#each}, no {@html}, no text interpolation may go inside it. `replaceChildren` replaces this
    subtree whole, so a Svelte-owned node in here is a node Svelte will later try to update after
    the renderer has already thrown it away.
  -->
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

  /* KAN-836's chunk that did not arrive. Same shape as `EditorPane`'s notice, so the two failure
     states read as one app rather than as two. */
  .notice {
    margin: 0;
    padding: 0.75rem 1rem;
    border: 1px solid var(--edge);
    border-left: 3px solid var(--accent);
    border-radius: 0.35rem;
    font-size: 0.85rem;
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
