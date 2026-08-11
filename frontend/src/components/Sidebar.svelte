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
   * the version a person can use.
   *
   * Everything here is presentation. No projection, no truncation, no aggregate over the payload
   * (ADR 0004, and `lib/api.ts`'s header on where the SPA sits relative to it): the counts on screen
   * are labels on groups of rows already downloaded, not a `summary` key computed into a payload.
   */
  const {
    notes,
    route,
    loading,
  }: { notes: Note[]; route: Route; loading: boolean } = $props()

  type View = 'tree' | 'list'
  let view: View = $state('tree')

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
  <div class="views" role="group" aria-label="Sidebar view">
    <button type="button" class:active={view === 'tree'} onclick={() => (view = 'tree')}>
      Tree
    </button>
    <button type="button" class:active={view === 'list'} onclick={() => (view = 'list')}>
      List
    </button>
  </div>

  {#if loading}
    <p class="empty">Loading…</p>
  {:else if notes.length === 0}
    <p class="empty">No notes yet.</p>
  {:else if view === 'list'}
    <!-- Every note, in the order `GET /api/v1/notes` returned them (newest first). Nothing is
         grouped, sorted or hidden here, which is the whole reason this view exists. -->
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
