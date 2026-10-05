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

  Each destination carries a Material-style icon (`NavIcon.svelte`, KAN-1822) with its label under
  it on compact and beside it on the rail; the active one sits on a tonal pill. The icons are
  decorative, the label is the accessible name, and the landing page's phone demo reuses them.
-->
<script lang="ts">
  import { interceptClick, type Route } from '../lib/router'
  import { NAV_DESTINATIONS, navActive } from '../lib/shell'
  import NavIcon from './NavIcon.svelte'

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
      <span class="nav-pill"><NavIcon name={destination.icon} /></span>
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
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.15rem;
    padding: 0.4rem 0.2rem;
    border-radius: 0.5rem;
    color: var(--nav-fg);
    text-decoration: none;
    font-size: 0.72rem;
    font-weight: 500;
    text-align: center;
    white-space: nowrap;
  }

  /* The tonal pill sits behind the icon; the active destination fills it. */
  .nav-pill {
    display: grid;
    place-items: center;
    width: 3.25rem;
    height: 1.75rem;
    border-radius: 0.9rem;
  }

  .nav-item:hover {
    color: var(--text);
  }

  .nav-item:hover .nav-pill {
    background: var(--nav-hover);
  }

  .nav-item:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: -2px;
  }

  .nav-item.active {
    color: var(--text);
    font-weight: 650;
  }

  .nav-item.active .nav-pill {
    background: var(--nav-indicator);
    color: var(--nav-fg-active);
  }

  /* Expanded: the labelled column, icon beside label, the whole row tinted when active. */
  @media (min-width: 840px) {
    .nav-column {
      padding: 0.75rem 0.4rem;
    }

    .nav-item {
      flex-direction: row;
      gap: 0.55rem;
      padding: 0.35rem 0.6rem 0.35rem 0.35rem;
      font-size: 0.82rem;
      text-align: left;
    }

    .nav-pill {
      width: 2rem;
      height: 2rem;
      border-radius: 0.5rem;
    }

    .nav-item.active {
      background: var(--nav-indicator);
    }

    .nav-item.active .nav-pill,
    .nav-item:hover .nav-pill {
      background: transparent;
    }

    .nav-item:hover {
      background: var(--nav-hover);
    }

    .nav-item.active:hover {
      background: var(--nav-indicator);
    }
  }

  /* Compact: an M3-style bottom navigation bar. 56px destinations, the active one marked by a pill
     behind its icon. */
  @media (max-width: 599.98px) {
    .nav-column {
      flex-direction: row;
      gap: 0;
      padding: 0 0 env(safe-area-inset-bottom);
      border-top: 1px solid var(--nav-border);
      border-right: 0;
    }

    .nav-item {
      flex: 1;
      justify-content: center;
      min-height: 3.5rem;
      padding: 0.35rem 0.25rem;
      border-radius: 0;
      font-size: 0.75rem;
      font-weight: 500;
    }

    .nav-item.active {
      font-weight: 650;
    }
  }
</style>
