<script lang="ts">
  import { fetchAttachmentBlobUrl } from '../lib/attachments'
  import { fetchBoardEmbed } from '../lib/embeds'
  import type { BoardEmbedResponse, Note } from '../lib/types'

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

    // KAN-1049: a second pass over the subtree just built, hydrating every `.embed-board`
    // placeholder `lib/markdown.ts` left behind. Not folded into `renderMarkdown` itself — that
    // function never makes a network call (a markdown renderer that fetches mid-parse cannot be
    // tested without a network), so the placeholder and its live content are necessarily two
    // steps, same as `EditorPane.svelte`'s CM6 tree rendering first and its `/links` pill
    // decoration arriving after.
    //
    // `abort` is this render pass's own token, not a component-lifetime one: this effect reruns on
    // every `source` change (a keystroke), `replaceChildren` above already discarded the previous
    // pass's DOM nodes, and the cleanup below fires before the next run starts (Svelte's ordering,
    // same guarantee `EditorPane.svelte`'s `linksInflight` leans on). So a response that lands after
    // ten more keystrokes finds `signal.aborted` true and writes into a node nobody can see — this
    // is the "ignore a stale response after remount" guard for this component, at render-pass
    // granularity rather than component-lifetime granularity, because a component doesn't remount
    // here but a render pass effectively does.
    const abort = new AbortController()
    hydrateBoardEmbeds(target, abort.signal)
    // R14 (KAN-1067/1068): every `blob:` URL this pass creates is tracked so the cleanup below can
    // revoke it — `replaceChildren` above already discarded the `<img>`s that held the previous
    // pass's URLs, so nothing but this array remembers them.
    const createdUrls: string[] = []
    hydrateAttachments(target, abort.signal, createdUrls)
    return () => {
      abort.abort()
      for (const url of createdUrls) {
        URL.revokeObjectURL(url)
      }
    }
  })

  /** Fetch and fill in every `.embed-board` placeholder under `root`. See the call site above. */
  function hydrateBoardEmbeds(root: HTMLElement, signal: AbortSignal): void {
    for (const el of root.querySelectorAll<HTMLElement>('.embed-board')) {
      const board = Number.parseInt(el.dataset.board ?? '', 10)
      if (!Number.isFinite(board)) {
        // `lib/markdown.ts` never emits `.embed-board` without a numeric `data-board` — this is
        // defence for a future change to that file, not a case reachable today.
        continue
      }
      const view = el.dataset.view === undefined ? undefined : Number.parseInt(el.dataset.view, 10)
      const column = el.dataset.column

      fetchBoardEmbed({ board, view, column, signal }).then((result) => {
        if (signal.aborted) {
          return
        }
        applyBoardEmbedResult(el, result)
      })
    }
  }

  /**
   * Replace a placeholder's "Loading board…" child with what `fetchBoardEmbed` answered.
   *
   * `null` (a transport failure) and `{ unavailable: true }` (pandan down, or the caller cannot see
   * this board — `app/integrations/board_embed.py` does not distinguish them either) render
   * identically: a caller of this component cannot and should not act differently on either, the
   * same argument `Link.resolved_ref` already makes for wikilink pills (Q26, ADR 0003).
   *
   * Every element is `document.createElement`, every value a `.textContent` assignment — the same
   * two safe primitives `lib/markdown.ts` uses, for the same reason: a card's `title` is another
   * author's prose (pandan's, not this note's, but no less arbitrary), and it must become a `Text`
   * node rather than a string ever passed to `innerHTML`.
   */
  function applyBoardEmbedResult(el: HTMLElement, result: BoardEmbedResponse | null): void {
    el.replaceChildren()

    if (result === null || result.unavailable) {
      const notice = document.createElement('p')
      notice.className = 'embed-board-unavailable'
      notice.dataset.testid = 'embed-board-unavailable'
      notice.textContent = 'This board could not be reached.'
      el.append(notice)
      return
    }

    if (result.cards.length === 0) {
      const notice = document.createElement('p')
      notice.className = 'embed-board-empty'
      notice.dataset.testid = 'embed-board-empty'
      notice.textContent = 'No cards match this query.'
      el.append(notice)
      return
    }

    const list = document.createElement('ul')
    list.className = 'embed-board-cards'
    list.dataset.testid = 'embed-board-cards'
    for (const card of result.cards) {
      const item = document.createElement('li')
      item.className = 'embed-board-card'

      const ref = document.createElement('span')
      ref.className = 'embed-board-ref'
      ref.textContent = card.ref

      const column = document.createElement('span')
      column.className = 'embed-board-column'
      column.textContent = card.column

      const title = document.createElement('span')
      title.className = 'embed-board-title'
      title.textContent = card.title

      item.append(ref, column, title)
      list.append(item)
    }
    el.append(list)
  }

  /**
   * Fetch and fill in every `.embed-attachment` placeholder under `root` — R14's render half
   * (KAN-1068). `lib/markdown.ts`'s `attachmentEmbedElement` is the only thing that produces this
   * class, and it always carries `data-attachment-note`/`data-attachment-id` together, so there is
   * nothing to validate here beyond parsing the id back out of the string it was serialized as.
   *
   * `createdUrls` collects every `blob:` URL this pass mints, so the caller (the render effect
   * above) can revoke them once this pass's DOM is thrown away — a `blob:` URL outlives the `<img>`
   * that used it until something calls `URL.revokeObjectURL`, and nothing else in this component
   * ever will.
   */
  function hydrateAttachments(root: HTMLElement, signal: AbortSignal, createdUrls: string[]): void {
    for (const el of root.querySelectorAll<HTMLElement>('.embed-attachment')) {
      const noteRef = el.dataset.attachmentNote
      const id = Number.parseInt(el.dataset.attachmentId ?? '', 10)
      if (noteRef === undefined || !Number.isFinite(id)) {
        // `lib/markdown.ts` never emits `.embed-attachment` without both — defence for a future
        // change to that file, not a case reachable today (same posture as `hydrateBoardEmbeds`'s
        // identical guard).
        continue
      }
      const alt = el.dataset.attachmentAlt ?? ''

      fetchAttachmentBlobUrl(noteRef, id, { signal }).then((url) => {
        if (signal.aborted) {
          // This pass was superseded before the fetch settled: `el` is detached (`replaceChildren`
          // already threw the whole previous fragment away), so nothing will ever read this URL —
          // revoke it immediately rather than leaving it for a cleanup that will never see it,
          // since it was never pushed onto this pass's `createdUrls`.
          if (url !== null) {
            URL.revokeObjectURL(url)
          }
          return
        }
        applyAttachmentResult(el, url, alt)
        if (url !== null) {
          createdUrls.push(url)
        }
      })
    }
  }

  /**
   * Replace an attachment placeholder's "Loading …" child with the fetched image, or a refusal
   * notice for `null` (no credential, a `403`/`404`, a transport failure — `fetchAttachmentBlobUrl`
   * collapses all of them, for the same over-disclosure reason `applyBoardEmbedResult` gives: a
   * reader cannot and should not act differently on any of them).
   */
  function applyAttachmentResult(el: HTMLElement, url: string | null, alt: string): void {
    el.replaceChildren()

    if (url === null) {
      const notice = document.createElement('span')
      notice.className = 'embed-attachment-unavailable'
      notice.dataset.testid = 'embed-attachment-unavailable'
      notice.textContent =
        alt === '' ? 'This attachment could not be loaded.' : `${alt} (could not be loaded)`
      el.append(notice)
      return
    }

    const img = document.createElement('img')
    img.src = url
    img.alt = alt
    img.loading = 'lazy'
    el.append(img)
  }
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
    border: 1px solid var(--border);
    border-left: 3px solid var(--accent);
    border-radius: 0.35rem;
    font-size: 0.85rem;
  }

  .rendered {
    flex: 1;
    min-width: 0;
    overflow: auto;
    padding: 0.75rem 1rem;
    border: 1px solid var(--border);
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
    border-left: 3px solid var(--border);
    color: var(--muted);
  }

  .rendered :global(code) {
    padding: 0.1em 0.3em;
    border-radius: 0.2rem;
    background: color-mix(in srgb, var(--text) 8%, transparent);
    font-family: var(--mono);
    font-size: 0.85em;
  }

  .rendered :global(pre) {
    overflow-x: auto;
    padding: 0.6rem 0.8rem;
    border-radius: 0.3rem;
    background: color-mix(in srgb, var(--text) 6%, transparent);
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

  /* A malformed `pandan-board` block (`lib/markdown.ts`) — no `data-*` attribute, so this is the
     whole of its rendering; nothing hydrates it. */
  .rendered :global(p.embed-board-error) {
    padding: 0.5rem 0.8rem;
    border: 1px dashed var(--border);
    border-radius: 0.3rem;
    color: var(--muted);
    font-size: 0.85em;
  }

  .rendered :global(table) {
    border-collapse: collapse;
    font-size: 0.9em;
  }

  /*
    KAN-1049's `pandan-board` embed. `:global` throughout — every node under `.embed-board` was
    built imperatively (`lib/markdown.ts`'s placeholder, this component's own hydration), never by
    Svelte's template, so none of it carries a scoping class.
  */
  .rendered :global(.embed-board) {
    padding: 0.6rem 0.8rem;
    border: 1px solid var(--border);
    border-left: 3px solid var(--accent);
    border-radius: 0.3rem;
    background: color-mix(in srgb, var(--text) 4%, transparent);
    font-size: 0.85em;
  }

  .rendered :global(.embed-board-unavailable),
  .rendered :global(.embed-board-empty) {
    margin: 0;
    color: var(--muted);
  }

  .rendered :global(.embed-board-cards) {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .rendered :global(.embed-board-card) {
    display: flex;
    align-items: baseline;
    gap: 0.5rem;
  }

  .rendered :global(.embed-board-ref) {
    color: var(--muted);
    font-family: var(--mono);
    font-size: 0.85em;
  }

  .rendered :global(.embed-board-column) {
    padding: 0.05em 0.4em;
    border-radius: 0.25rem;
    background: color-mix(in srgb, var(--accent) 15%, transparent);
    font-size: 0.75em;
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }

  /*
    R14's attachment embed (KAN-1067/1068). `:global` for the same reason `.embed-board`'s rules
    are: every node under `.embed-attachment` is built imperatively (`lib/markdown.ts`'s
    placeholder, this component's own hydration), never by Svelte's template.
  */
  .rendered :global(.embed-attachment) {
    display: inline-block;
  }

  .rendered :global(.embed-attachment-unavailable) {
    display: inline-block;
    padding: 0.1em 0.4em;
    border: 1px dashed var(--border);
    border-radius: 0.25rem;
    color: var(--muted);
    font-size: 0.85em;
  }

  .rendered :global(th),
  .rendered :global(td) {
    padding: 0.3rem 0.6rem;
    border: 1px solid var(--border);
    text-align: left;
  }

  .rendered :global(hr) {
    margin: 1.2em 0;
    border: 0;
    border-top: 1px solid var(--border);
  }

  .rendered :global(img) {
    max-width: 100%;
  }

  .rendered :global(a) {
    color: var(--accent);
  }
</style>
