<!--
  The persistent left rail switching between kaya's own top-level sections: Notes, Graph, Settings. KAN-1818: one element, three
  presentations by window class, all through the same `data-testid`s — a bottom navigation bar on
  compact (<600px), a slim rail on medium, the labelled column on expanded. Tokens and the pandan link
  live under Settings now, no longer here.

  Distinct from `Sidebar.svelte`, which lists individual *notes* — this is one level up, the thing
  that decides which of the app's sections `Sidebar`/the editor/`Tokens.svelte` even apply to.
  Kaya had no equivalent of this before: the topbar carried a single "Tokens" text link and
  everything else was reached by editing the address bar or clicking a note. "Workspaces" has no
  entry here yet — there is nothing to switch to until that feature exists, and a disabled
  placeholder was a considered and rejected option (reads as a broken link, not as intent).

  **Shown only when `App.svelte`'s `authed` is true**, the same reasoning `Sidebar.svelte` already
  applies to itself ("no sidebar without a credential... reads as a broken app rather than as a
  locked one") — `/tokens` stays reachable pre-auth through the topbar's own link exactly as before
  (KAN-1739), so this column is additive, never a replacement for that path. It renders across
  *all three* of `App.svelte`'s post-auth branches (`tokens`, `device`, and the note/graph view),
  which is why `App.svelte` places it as a sibling of that whole branch rather than nested inside
  one arm of it — the entire point is that it survives being wherever you are.

  Text labels only, no icons: nothing else in kaya's UI has ever used one (`App.svelte`'s topbar,
  `Sidebar.svelte`, `Tokens.svelte` are all plain text), and a rail matching that is a considered
  choice, not an oversight — introducing lucide-svelte (pandan's own icon set) for this one column
  would be the first icon anywhere in the product and the first new runtime dependency since
  CodeMirror (`lib/router.ts`'s own docstring argues the bar that has to clear).
-->
<script lang="ts">
  import { interceptClick, type Route } from '../lib/router'
  import { NAV_DESTINATIONS, navActive } from '../lib/shell'

  const { route }: { route: Route } = $props()
</script>

<nav class="nav-column" aria-label="Sections" data-testid="nav-column">
  {#each NAV_DESTINATIONS as destination (destination.label)}
    {@const active = navActive(destination, route)}
    <a
      class="nav-item"
      class:active
      href={destination.href}
      aria-current={active ? 'page' : undefined}
      onclick={(event) => interceptClick(event, destination.href)}
      data-testid={`nav-item-${destination.label.toLowerCase()}`}
    >
      <span class="nav-label">{destination.label}</span>
    </a>
  {/each}
</nav>

<style>
  /* Re-themable: the nav bar reads only these tokens (the M3 palette card overrides them). */
  .nav-column {
    --nav-bg: var(--card-bg);
    --nav-border: var(--border);
    --nav-fg: var(--muted);
    --nav-fg-active: var(--accent);
    --nav-indicator: var(--accent-soft);
    --nav-hover: var(--hover);

    grid-area: nav;
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    min-width: 0;
    padding: 0.75rem 0.25rem;
    background: var(--nav-bg);
    border-right: 1px solid var(--nav-border);
  }

  .nav-item {
    display: block;
    padding: 0.4rem 0.35rem;
    border-radius: 0.35rem;
    color: var(--nav-fg);
    text-decoration: none;
    font-size: 0.72rem;
    font-weight: 500;
    text-align: center;
    white-space: nowrap;
  }

  .nav-item:hover {
    color: var(--text);
    background: var(--nav-hover);
  }

  .nav-item:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: -2px;
  }

  .nav-item.active {
    color: var(--nav-fg-active);
    background: var(--nav-indicator);
  }

  @media (min-width: 840px) {
    .nav-column {
      padding: 0.75rem 0.4rem;
    }

    .nav-item {
      padding: 0.45rem 0.6rem;
      font-size: 0.82rem;
      text-align: left;
    }
  }

  /* Compact: an M3-style bottom navigation bar. 56px destinations, the active one marked by a pill
     behind its label. */
  @media (max-width: 599.98px) {
    .nav-column {
      flex-direction: row;
      gap: 0;
      padding: 0 0 env(safe-area-inset-bottom);
      border-top: 1px solid var(--nav-border);
      border-right: 0;
    }

    .nav-item {
      display: flex;
      flex: 1;
      align-items: center;
      justify-content: center;
      min-height: 3.5rem;
      padding: 0.25rem;
      border-radius: 0;
      background: transparent;
      font-size: 0.75rem;
      font-weight: 600;
    }

    .nav-item:hover,
    .nav-item.active {
      background: transparent;
    }

    .nav-label {
      padding: 0.3rem 1.1rem;
      border-radius: 1rem;
    }

    .nav-item.active .nav-label {
      background: var(--nav-indicator);
    }
  }
</style>
