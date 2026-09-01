<script lang="ts">
  import { SvelteSet } from 'svelte/reactivity'

  import { interceptClick, routeHref, type Route } from '../lib/router'
  import { buildTree, type NoteTree, type TreeNode } from '../lib/tree'
  import type { Note } from '../lib/types'

  /**
   * KAN-554's sidebar: a folder tree over the `path` column, and the flat note list beside it.
   *
   * **Two views rather than one, and the second is a safety property rather than a preference.** The
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
  }: {
    notes: Note[]
    route: Route
    loading: boolean
    /** The **committed** search term — what the last search actually asked for, `''` for none. */
    query?: string
    /** Fired with the trimmed term on submit, and with `''` when the search is cleared. */
    onsearch?: (term: string) => void
    /**
     * KAN-1040's "+ New note": fired with the trimmed, non-empty title once the inline prompt is
     * submitted. `App.svelte` owns the actual `createNote()` call and the navigation afterwards —
     * same split as `onsearch`, and for the same reason: this component has no client of its own,
     * and a `401` from a stale credential has to reach `App`'s `discard()`, not stop here.
     */
    oncreate?: (title: string) => void
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

  /** Whether the inline title prompt (A1-UI2) is on screen in place of the "+ New note" button. */
  let creating = $state(false)
  let newTitle = $state('')

  function openCreate(): void {
    creating = true
    newTitle = ''
  }

  function cancelCreate(): void {
    creating = false
    newTitle = ''
  }

  /** A blank title is refused here rather than sent — `title` is required server-side and a prompt
   *  that submits nothing should say nothing happened, not round-trip a `422`. */
  function submitCreate(event: SubmitEvent): void {
    event.preventDefault()
    const title = newTitle.trim()
    if (title === '') {
      return
    }
    oncreate(title)
    creating = false
    newTitle = ''
  }

  type View = 'tree' | 'list'

  /**
   * Which view the **user** chose — not necessarily the one on screen (KAN-962).
   *
   * A search always renders as a flat list (`view` below), so this rune has to survive one: the
   * toggle writes it and nothing else does, which is what makes clearing a search put a person back
   * where they were. Option (a) on the card — flipping this to `'list'` when a search commits — looks
   * identical on screen and is not the same thing at all, because nothing would ever flip it back.
   */
  let chosen: View = $state('tree')

  /** Whether `notes` is a *result set* rather than the corpus. `query` is the committed term. */
  const searching = $derived(query !== '')

  /**
   * The view that actually renders: the flat list whenever a search is active.
   *
   * KAN-962, and the defect was at this layer rather than in KAN-558 or KAN-559. The API ranks a
   * search `ts_rank DESC, note.id DESC` and went to real trouble to make equal ranks order
   * deterministically, because they are common — two notes on the seeded corpus tie at 0.9910 on
   * `reading list`. The tree groups by the `path` column, so it *cannot* carry an arbitrary row
   * order: a folder exists because some note's path names it, and every ordering the server chose
   * is destroyed by the grouping. The tree is not sorting wrongly, it is answering a different
   * question — and since TREE is the default, the *default* rendering of a search was the one that
   * threw the ranking away, silently. "These are your notes, arranged" and "these matched, best
   * first" are two objects and one toggle cannot mean both, so a search is rendered by the view
   * that can hold an order.
   *
   * The toggle is **off the screen while a search is active** (the template below), not merely
   * ignored. A visible control reading `Tree` above a flat list is the same lie as silently
   * overriding the choice; what takes its place says what the ordering is instead.
   */
  const view: View = $derived(searching ? 'list' : chosen)

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
        onclick={() => toggle(node.key)}
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

<nav class="sidebar" aria-label="Notes">
  <!--
    KAN-1040's "+ New note", A1 in BREADBOARD.md: the button opens an inline title prompt in place
    of itself, and Create hands the trimmed title up to `oncreate` — this component makes no
    network call and does not navigate itself.
  -->
  <div class="create">
    {#if creating}
      <form class="create-form" onsubmit={submitCreate} data-testid="create-form">
        <input
          type="text"
          class="create-input"
          placeholder="Note title…"
          bind:value={newTitle}
          aria-label="New note title"
          data-testid="create-title-input"
        />
        <button type="submit" data-testid="create-confirm">Create</button>
        <button type="button" data-testid="create-cancel" onclick={cancelCreate}>Cancel</button>
      </form>
    {:else}
      <button type="button" class="new-note" onclick={openCreate} data-testid="new-note-button">
        + New note
      </button>
    {/if}
  </div>

  <!--
    KAN-1050's graph view: the only reachable link to it in the app. A row rather than a button —
    it is a navigation, the same as every other `<a>` in this component — placed beside "+ New
    note" because that is where a person already looks for "what can I do with my notes as a
    whole" rather than with one of them.
  -->
  <a
    href={routeHref({ name: 'graph' })}
    class="graph-link"
    class:open={route.name === 'graph'}
    aria-current={route.name === 'graph' ? 'page' : undefined}
    onclick={(event) => interceptClick(event, '/graph')}
    data-testid="graph-link"
  >
    Graph
  </a>

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

  <!--
    The view toggle — or, while a search is active, the one line saying why there is no choice to make
    (KAN-962). Two arms of one `{#if}` rather than two conditions, so "a toggle reading Tree above a
    flat search result" is unreachable rather than merely untested.
  -->
  {#if searching}
    <p class="ordering" data-testid="search-ordering">
      Ordered by relevance, not grouped by folder. The view toggle returns when you clear the search.
    </p>
  {:else}
    <div class="views" role="group" aria-label="Sidebar view">
      <button type="button" class:active={chosen === 'tree'} onclick={() => (chosen = 'tree')}>
        Tree
      </button>
      <button type="button" class:active={chosen === 'list'} onclick={() => (chosen = 'list')}>
        List
      </button>
    </div>
  {/if}

  {#if loading}
    <p class="empty">Loading…</p>
  {:else if notes.length === 0}
    <!-- Presentation over the same empty array either way (ADR 0004: no aggregate to read a
         count from here) — only the wording tells a "you own nothing yet" apart from a search
         that matched nothing. -->
    <p class="empty">{query === '' ? 'No notes yet.' : `No notes match "${query}".`}</p>
  {:else if view === 'list'}
    <!-- Every note, in the order `GET /api/v1/notes` returned them: `updated_at DESC, id DESC` for
         the corpus, `ts_rank DESC, id DESC` for a search (KAN-558). Nothing is grouped, sorted or
         hidden here, which is the whole reason this view exists — and, since KAN-962, the whole
         reason a search renders through it whatever the toggle was set to. -->
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
    border-right: 1px solid var(--edge);
  }

  .create {
    padding: 0 0.5rem;
  }

  .new-note {
    width: 100%;
    padding: 0.35rem 0.5rem;
    border: 1px dashed var(--edge);
    border-radius: 0.3rem;
    background: transparent;
    color: var(--accent);
    cursor: pointer;
    font: inherit;
    font-size: 0.8rem;
    text-align: left;
  }

  .new-note:hover {
    background: color-mix(in srgb, var(--accent) 10%, transparent);
  }

  .graph-link {
    display: block;
    margin: 0 0.5rem;
    padding: 0.3rem 0.5rem;
    border-radius: 0.3rem;
    color: var(--muted);
    font-size: 0.8rem;
    font-weight: 600;
    letter-spacing: 0.02em;
    text-decoration: none;
  }

  .graph-link:hover {
    background: color-mix(in srgb, var(--accent) 10%, transparent);
  }

  a.graph-link.open {
    background: color-mix(in srgb, var(--accent) 16%, transparent);
    color: var(--accent);
  }

  .create-form {
    display: flex;
    gap: 0.3rem;
  }

  .create-input {
    flex: 1;
    min-width: 0;
    padding: 0.3rem 0.5rem;
    border: 1px solid var(--edge);
    border-radius: 0.3rem;
    background: transparent;
    color: inherit;
    font: inherit;
    font-size: 0.8rem;
  }

  .create-form button {
    flex: none;
    padding: 0.2rem 0.5rem;
    border: 1px solid var(--edge);
    border-radius: 0.3rem;
    background: transparent;
    color: var(--muted);
    cursor: pointer;
    font: inherit;
    font-size: 0.7rem;
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
    border: 1px solid var(--edge);
    border-radius: 0.3rem;
    background: transparent;
    color: inherit;
    font: inherit;
    font-size: 0.8rem;
  }

  .clear-search {
    flex: none;
    padding: 0.2rem 0.5rem;
    border: 1px solid var(--edge);
    border-radius: 0.3rem;
    background: transparent;
    color: var(--muted);
    cursor: pointer;
    font: inherit;
    font-size: 0.7rem;
  }

  /* The ordering notice sits exactly where the toggle was, so the swap reads as one control saying
     something rather than as a row of the sidebar disappearing. */
  .ordering {
    margin: 0;
    padding: 0 0.5rem;
    color: var(--muted);
    font-size: 0.7rem;
    line-height: 1.35;
  }

  .views {
    display: flex;
    gap: 0.25rem;
    padding: 0 0.5rem;
  }

  .views button {
    padding: 0.2rem 0.55rem;
    border: 1px solid var(--edge);
    border-radius: 0.3rem;
    background: transparent;
    color: var(--muted);
    cursor: pointer;
    font: inherit;
    font-size: 0.7rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }

  .views button.active {
    border-color: color-mix(in srgb, var(--accent) 45%, var(--edge));
    background: color-mix(in srgb, var(--accent) 12%, transparent);
    color: var(--accent);
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
    border-radius: 0.3rem;
    background: transparent;
    color: inherit;
    font: inherit;
    text-align: left;
    text-decoration: none;
  }

  .row:hover {
    background: color-mix(in srgb, var(--accent) 10%, transparent);
  }

  .row.folder {
    display: flex;
    align-items: baseline;
    gap: 0.35rem;
    color: var(--muted);
    cursor: pointer;
    font-size: 0.85rem;
  }

  .twist {
    flex: none;
    font-size: 0.65rem;
  }

  a.row.open {
    background: color-mix(in srgb, var(--accent) 16%, transparent);
    color: var(--accent);
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
    color: var(--muted);
    font-family: var(--mono);
    font-size: 0.7rem;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .unpathed {
    margin-top: 0.5rem;
    padding-top: 0.5rem;
    border-top: 1px dashed var(--edge);
  }

  .unpathed h3 {
    display: flex;
    gap: 0.4rem;
    align-items: baseline;
    margin: 0 0 0.15rem;
    padding: 0 0.5rem;
    color: var(--muted);
    font-size: 0.7rem;
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
    color: var(--muted);
    font-size: 0.9rem;
  }
</style>
