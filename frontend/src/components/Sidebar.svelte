<script lang="ts">
  import { SvelteSet } from 'svelte/reactivity'

  import NavIcon from './NavIcon.svelte'
  import { interceptClick, routeHref, type Route } from '../lib/router'
  import { buildTree, type NoteTree, type TreeNode } from '../lib/tree'
  import type { Note } from '../lib/types'

  /**
   * KAN-554's sidebar: a folder tree over the `path` column, and the flat note list beside it.
   *
   * **Tree-only since KAN-1996.** The Tree/List toggle is gone; the flat list survives only as how a
   * search renders (KAN-962). What follows is the history of why it existed. The
   * tree is a *view* of paths (`lib/tree.ts`), and a view can be wrong about structure in ways nobody
   * notices — a segment rule that swallows a level, a sort that hides a row below a fold. The list is
   * the corpus in the order the API returned it, so "the tree is hiding a note" is always one click
   * from being disproved. `lib/tree.ts` asserts the same thing mechanically with `countNotes`; this is
   * the version a person can use. KAN-962 gave it a second job: a search is *rendered* by the list,
   * because relevance is an order and the tree has nowhere to put one.
   *
   * Everything here is presentation. No projection, no truncation, no aggregate over the payload
   * (ADR 0004, and `lib/api.ts`'s header on where the SPA sits relative to it): the counts on screen
   * are labels on groups of rows already downloaded, not a `summary` key computed into a payload.
   */
  const {
    notes,
    route,
    loading,
    query = '',
    onsearch = () => {},
    oncreate = () => {},
    onfolder = () => {},
  }: {
    notes: Note[]
    route: Route
    loading: boolean
    /** The **committed** search term — what the last search actually asked for, `''` for none. */
    query?: string
    /** Fired with the trimmed term on submit, and with `''` when the search is cleared. */
    onsearch?: (term: string) => void
    /**
     * KAY-166's "New note": fired with no arguments. `App.svelte` generates the `Untitled` title and
     * the path (`lib/newNote.ts`), owns the `createNote()` call and navigates afterwards, so a `401`
     * reaches its `discard()`.
     */
    oncreate?: () => void
    /** A folder row was clicked: its full path, the "current folder" for the next new note. */
    onfolder?: (key: string) => void
  } = $props()

  /**
   * The input's own text, kept apart from `query` on purpose (KAN-559).
   *
   * `query` is App's — it is what drove the request that produced `notes` — and this is the box's:
   * what is typed but not yet submitted. Conflating them would either fetch on every keystroke (no
   * card asked for that, and a note corpus scrolls fine without it) or make the box unable to hold
   * a draft that differs from the last search.
   *
   * A **writable** `$derived` rather than `$state` plus a syncing `$effect`: Svelte 5 lets a
   * `$derived` be reassigned locally, and that reassignment is exactly "the draft while typing"
   * until `query` changes again, at which point it recomputes and the override is gone — a clear
   * via the header or a fresh search both replace the draft with the newly committed term, with no
   * effect for typing to race.
   */
  let draft = $derived(query)

  function submit(event: SubmitEvent): void {
    event.preventDefault()
    onsearch(draft.trim())
  }

  function clear(): void {
    draft = ''
    onsearch('')
  }

  /**
   * KAY-166: "New note" asks `App` to create a note called `Untitled` at once; there is no prompt.
   * `N` with the tree focused does the same (Ctrl/Cmd+N belongs to the browser, so it is not used).
   * Never from a text field: the search box must still be able to type the letter.
   */
  function treeKeydown(event: KeyboardEvent): void {
    if (event.key.toLowerCase() !== 'n' || event.ctrlKey || event.metaKey || event.altKey) {
      return
    }
    const target = event.target as HTMLElement | null
    if (target?.closest('input, textarea, select, [contenteditable]')) {
      return
    }
    event.preventDefault()
    oncreate()
  }

  /** Whether `notes` is a *result set* rather than the corpus. `query` is the committed term. */
  const searching = $derived(query !== '')

  // KAN-1996: the tree is the only browse view; the Tree/List toggle and its `chosen` state are gone.
  // A search is still rendered as the flat list (KAN-962): the API ranks `ts_rank DESC, note.id DESC`
  // and the tree groups by `path`, so it has nowhere to put a relevance order.

  const tree: NoteTree = $derived(buildTree(notes))

  /**
   * Which folders are open, as the set of folders explicitly **closed**.
   *
   * Inverted on purpose: the default has to be "expanded", because a tree that starts collapsed hides
   * every note behind a click and makes the sidebar look empty on first load. Storing the closures
   * means a folder that appears later — a note moved into a new path — is open like its neighbours,
   * where a set of *open* keys would have it silently start closed.
   */
  const closed = new SvelteSet<string>()

  function toggle(key: string): void {
    if (!closed.delete(key)) {
      closed.add(key)
    }
  }

  function isOpen(note: Note): boolean {
    return route.name === 'note' && route.ref === note.ref
  }

  /**
   * The row's left inset, clamped.
   *
   * A path is `String(1024)` in migration `0001`, so a pathological note could nest deeper than the
   * pane is wide and push every title out of sight. Past the eighth level the indent stops growing:
   * the nesting is still visible in the folder rows above the row, and a title you can read beats a
   * position you can measure. `min-width: 0` plus the ellipsis below is the other half.
   */
  function inset(depth: number): string {
    return `${0.5 + Math.min(depth, 8) * 0.7}rem`
  }

  /** `title` when there is one, so a row is never a blank line. `''` is a legal title server-side. */
  function label(note: Note): string {
    return note.title === '' ? note.ref : note.title
  }
</script>

{#snippet noteRow(note: Note, secondary: string, depth: number)}
  <li>
    <a
      href={routeHref({ name: 'note', ref: note.ref })}
      class="row note"
      class:open={isOpen(note)}
      aria-current={isOpen(note) ? 'page' : undefined}
      style:padding-left={inset(depth)}
      onclick={(event) => interceptClick(event, `/notes/${note.ref}`)}
    >
      <span class="title">{label(note)}</span>
      <span class="sub">{secondary}</span>
    </a>
  </li>
{/snippet}

{#snippet branch(node: TreeNode, depth: number)}
  {#if node.kind === 'folder'}
    <li>
      <button
        type="button"
        class="row folder"
        style:padding-left={inset(depth)}
        aria-expanded={!closed.has(node.key)}
        onclick={() => {
          toggle(node.key)
          onfolder(node.key)
        }}
      >
        <span class="twist" aria-hidden="true">{closed.has(node.key) ? '▸' : '▾'}</span>
        <span class="title">{node.name}</span>
      </button>
      {#if !closed.has(node.key)}
        <ul>
          {#each node.children as child (child.kind === 'folder' ? `d:${child.key}` : `n:${child.note.ref}`)}
            {@render branch(child, depth + 1)}
          {/each}
        </ul>
      {/if}
    </li>
  {:else}
    <!-- The filename, because the folder rows above already say the rest of the path. -->
    {@render noteRow(node.note, node.filename, depth)}
  {/if}
{/snippet}

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<nav class="sidebar" aria-label="Notes" onkeydown={treeKeydown}>
  <!-- KAY-166: a tonal button; the note is created immediately, see `oncreate`. -->
  <div class="create">
    <button type="button" class="new-note" onclick={() => oncreate()} data-testid="new-note-button">
      <NavIcon name="add" size={20} />
      New note
    </button>
  </div>

  <!--
    KAN-559's search box. `--q` on the client is one flag and one input here, and it stays that
    shape: submitting sends `draft.trim()` up to `onsearch`, which is App's request to make, not
    this component's — a `Sidebar` that fetched would be a second network caller for the one list
    App already owns.
  -->
  <form class="search" onsubmit={submit} data-testid="search-form">
    <input
      type="search"
      class="search-input"
      placeholder="Search notes…"
      bind:value={draft}
      aria-label="Search notes"
      data-testid="search-input"
    />
    {#if query !== ''}
      <button type="button" class="clear-search" onclick={clear} data-testid="clear-search">
        Clear
      </button>
    {/if}
  </form>

  {#if searching}
    <p class="ordering" data-testid="search-ordering">Matches, best first. Ordered by relevance, not grouped by folder.</p>
  {/if}

  {#if loading}
    <p class="empty">Loading…</p>
  {:else if notes.length === 0}
    <!-- Presentation over the same empty array either way (ADR 0004: no aggregate to read a
         count from here) — only the wording tells a "you own nothing yet" apart from a search
         that matched nothing. -->
    <p class="empty">{query === '' ? 'No notes yet. Create one, or ask your agent to.' : `No notes match "${query}".`}</p>
  {:else if searching}
    <!-- Every note, in the order `GET /api/v1/notes` returned them: `updated_at DESC, id DESC` for
         the corpus, `ts_rank DESC, id DESC` for a search (KAN-558). Nothing is grouped, sorted or
         hidden here, which is the whole reason this view exists — and, since KAN-962, the whole
         reason a search renders through it . -->
    <ul data-testid="note-list">
      {#each notes as note (note.ref)}
        <!-- `path` is legitimately empty (ADR 0008), and an em dash beats a blank line that reads
             as a rendering bug. -->
        {@render noteRow(note, note.path === '' ? '—' : note.path, 0)}
      {/each}
    </ul>
  {:else}
    <ul data-testid="note-tree">
      {#each tree.roots as node (node.kind === 'folder' ? `d:${node.key}` : `n:${node.note.ref}`)}
        {@render branch(node, 0)}
      {/each}
    </ul>

    {#if tree.unpathed.length > 0}
      <!--
        Notes with no path, under a label that names the **absence** of one.
        `lib/tree.ts` explains why they are a separate field rather than a folder: `path: ''` is a
        legitimate note (ADR 0008) and two of the seeded ten are like that, so the two failures
        available were dropping them silently and inventing a root folder called `''`. The count is
        here because "somewhere below" is not visible enough for the thing this card is most likely
        to get wrong — it is a label on rows already on screen, not an aggregate over a payload.
      -->
      <section class="unpathed" data-testid="unpathed" aria-label="Notes with no path">
        <h3>no path <span class="count">{tree.unpathed.length}</span></h3>
        <ul>
          {#each tree.unpathed as note (note.ref)}
            {@render noteRow(note, note.ref, 0)}
          {/each}
        </ul>
      </section>
    {/if}
  {/if}
</nav>

<style>
  .sidebar {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    min-width: 0;
    overflow-y: auto;
    padding: 1rem 0.5rem 1.5rem;
    background: var(--surface-container);
    border-right: 1px solid var(--outline-variant);
  }

  .create {
    padding: 0 0.5rem;
  }

  .new-note {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
    width: 100%;
    padding: 0.65rem 1rem;
    border: 0;
    border-radius: var(--shape-full);
    background: var(--secondary-container);
    color: var(--on-secondary-container);
    cursor: pointer;
    font: inherit;
    font-size: var(--type-body-medium-size);
    font-weight: 500;
  }

  .new-note:hover {
    background: color-mix(in srgb, var(--on-secondary-container) calc(var(--state-hover) * 100%), var(--secondary-container));
  }

  .new-note:focus-visible {
    outline: 2px solid var(--primary);
    outline-offset: 2px;
  }

  .search {
    display: flex;
    gap: 0.3rem;
    padding: 0 0.5rem;
  }

  .search-input {
    flex: 1;
    min-width: 0;
    padding: 0.3rem 0.5rem;
    border: 1px solid var(--outline);
    border-radius: var(--shape-full);
    background: transparent;
    color: inherit;
    font: inherit;
    font-size: var(--type-body-medium-size);
  }

  .clear-search {
    flex: none;
    padding: 0.2rem 0.5rem;
    border: 1px solid var(--outline);
    border-radius: var(--shape-full);
    background: transparent;
    color: var(--on-surface-variant);
    cursor: pointer;
    font: inherit;
    font-size: var(--type-label-medium-size);
  }

  /* The ordering notice sits exactly where the toggle was, so the swap reads as one control saying
     something rather than as a row of the sidebar disappearing. */
  .ordering {
    margin: 0;
    padding: 0 0.5rem;
    color: var(--on-surface-variant);
    font-size: var(--type-label-medium-size);
    line-height: 1.35;
  }

  ul {
    margin: 0;
    /* The indent is on the row, not on the list: see `inset()` on why it has to be clampable. */
    padding: 0;
    list-style: none;
  }

  .row {
    display: block;
    width: 100%;
    min-width: 0;
    padding: 0.3rem 0.5rem;
    border: 0;
    border-radius: var(--shape-md);
    background: transparent;
    color: inherit;
    font: inherit;
    text-align: left;
    text-decoration: none;
  }

  .row:hover {
    background: var(--layer-hover);
  }

  .row.folder {
    display: flex;
    align-items: baseline;
    gap: 0.35rem;
    color: var(--on-surface-variant);
    cursor: pointer;
    font-size: var(--type-body-medium-size);
  }

  .twist {
    flex: none;
    font-size: var(--type-label-small-size);
  }

  a.row.open {
    background: var(--secondary-container);
    color: var(--on-secondary-container);
  }

  .title {
    display: block;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .sub {
    display: block;
    overflow: hidden;
    color: var(--on-surface-variant);
    font-family: var(--mono);
    font-size: var(--type-label-medium-size);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .unpathed {
    margin-top: 0.5rem;
    padding-top: 0.5rem;
    border-top: 1px dashed var(--outline-variant);
  }

  .unpathed h3 {
    display: flex;
    gap: 0.4rem;
    align-items: baseline;
    margin: 0 0 0.15rem;
    padding: 0 0.5rem;
    color: var(--on-surface-variant);
    font-size: var(--type-label-medium-size);
    font-style: italic;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }

  .count {
    font-family: var(--mono);
    font-style: normal;
  }

  .empty {
    margin: 0;
    padding: 0 0.5rem;
    color: var(--on-surface-variant);
    font-size: 0.9rem;
  }

  /* KAN-1818, compact: the list is its own full-width screen, so its controls and rows are touch
     targets (48px; the M3 minimum is 44). */
  @media (max-width: 599.98px) {
    .new-note,
    .search-input,
    .clear-search {
      min-height: 3rem;
      font-size: 1rem;
    }

    .row {
      display: flex;
      flex-direction: column;
      justify-content: center;
      min-height: 3rem;
    }

    /* `.row` centres its content (vertically, in a column); a folder row is a row, so the inherited
       `justify-content: center` would centre the name and caret horizontally. */
    .row.folder {
      flex-direction: row;
      align-items: center;
      justify-content: flex-start;
    }
  }
</style>
