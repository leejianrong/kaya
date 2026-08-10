<!-- KAN-554 replaces this file: the folder tree over `path`, and the real note list. -->
<script lang="ts">
  import { interceptClick, routeHref, type Route } from '../lib/router'
  import type { Note } from '../lib/types'

  const {
    notes,
    route,
    loading,
  }: { notes: Note[]; route: Route; loading: boolean } = $props()

  /** Whether this row is the note currently open. */
  function isOpen(note: Note): boolean {
    return route.name === 'note' && route.ref === note.ref
  }
</script>

<!--
  A flat list of links, on purpose. KAN-554 owns the folder tree built from `path` and whatever the
  real list becomes; this exists so the shell has working navigation to prove the router, the
  credential seam and the fetch layer are wired together end to end. Do not grow it — replace it.
-->
<nav class="sidebar" aria-label="Notes">
  <h2>Notes</h2>

  {#if loading}
    <p class="empty">Loading…</p>
  {:else if notes.length === 0}
    <p class="empty">No notes yet.</p>
  {:else}
    <ul>
      {#each notes as note (note.ref)}
        <li>
          <a
            href={routeHref({ name: 'note', ref: note.ref })}
            class:open={isOpen(note)}
            aria-current={isOpen(note) ? 'page' : undefined}
            onclick={(event) => interceptClick(event, `/notes/${note.ref}`)}
          >
            <span class="title">{note.title}</span>
            <!-- `path` is empty for a legitimate note (ADR 0008), so this row must not assume one.
                 An em dash beats an empty line that looks like a rendering bug. -->
            <span class="path">{note.path === '' ? '—' : note.path}</span>
          </a>
        </li>
      {/each}
    </ul>
  {/if}
</nav>

<style>
  .sidebar {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    overflow-y: auto;
    padding: 1.5rem 1rem;
    border-right: 1px solid var(--edge);
  }

  h2 {
    margin: 0;
    color: var(--muted);
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  ul {
    margin: 0;
    padding: 0;
    list-style: none;
  }

  a {
    display: block;
    padding: 0.4rem 0.5rem;
    border-radius: 0.3rem;
    color: inherit;
    text-decoration: none;
  }

  a:hover {
    background: color-mix(in srgb, var(--accent) 10%, transparent);
  }

  a.open {
    background: color-mix(in srgb, var(--accent) 16%, transparent);
    color: var(--accent);
  }

  .title {
    display: block;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .path {
    display: block;
    overflow: hidden;
    color: var(--muted);
    font-family: var(--mono);
    font-size: 0.75rem;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .empty {
    margin: 0;
    color: var(--muted);
    font-size: 0.9rem;
  }
</style>
