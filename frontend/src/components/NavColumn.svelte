<!--
  The persistent left rail switching between kaya's own top-level sections: Notes, Graph, Tokens.

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

  const { route }: { route: Route } = $props()

  interface Section {
    label: string
    href: string
    isActive: (route: Route) => boolean
  }

  const SECTIONS: readonly Section[] = [
    { label: 'Notes', href: '/', isActive: (r) => r.name === 'home' || r.name === 'note' },
    { label: 'Graph', href: '/graph', isActive: (r) => r.name === 'graph' },
    { label: 'Tokens', href: '/tokens', isActive: (r) => r.name === 'tokens' },
    { label: 'Settings', href: '/settings', isActive: (r) => r.name === 'settings' },
  ]
</script>

<nav class="nav-column" aria-label="Sections" data-testid="nav-column">
  {#each SECTIONS as section (section.label)}
    {@const active = section.isActive(route)}
    <a
      class="nav-item"
      class:active
      href={section.href}
      aria-current={active ? 'page' : undefined}
      onclick={(event) => interceptClick(event, section.href)}
      data-testid={`nav-item-${section.label.toLowerCase()}`}
    >
      {section.label}
    </a>
  {/each}
</nav>

<style>
  .nav-column {
    grid-area: nav;
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    padding: 0.75rem 0.4rem;
    background: var(--card-bg);
    border-right: 1px solid var(--border);
  }

  .nav-item {
    display: block;
    padding: 0.45rem 0.6rem;
    border-radius: 0.35rem;
    color: var(--muted);
    text-decoration: none;
    font-size: 0.82rem;
    font-weight: 500;
    white-space: nowrap;
  }

  .nav-item:hover {
    color: var(--text);
    background: var(--hover);
  }

  .nav-item:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: -2px;
  }

  .nav-item.active {
    color: var(--accent);
    background: var(--accent-soft);
  }

  /* Matches `App.svelte`'s own narrow-viewport column width (measured against a real 390px
     viewport) — smaller padding and type so three words still read as three words rather than
     wrapping inside a track half as wide as the laptop layout's. */
  @media (max-width: 60rem) {
    .nav-column {
      padding: 0.6rem 0.25rem;
    }

    .nav-item {
      padding: 0.4rem 0.35rem;
      font-size: 0.72rem;
    }
  }
</style>
