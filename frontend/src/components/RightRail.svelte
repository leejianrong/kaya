<script lang="ts">
  import BacklinksPanel from './BacklinksPanel.svelte'
  import HistoryPanel from './HistoryPanel.svelte'
  import { nextTabIndex } from '../lib/tabs'
  import type { Note } from '../lib/types'

  /**
   * The fourth region of the shell (KAN-568), now two tabs instead of one — R13/KAN-1064's History
   * beside KAN-568's Backlinks, per BREADBOARD.md's placement call ("a History tab beside the
   * existing Backlinks tab in the right rail").
   *
   * **This file owns the tab strip and nothing else.** `BacklinksPanel` and `HistoryPanel` are each
   * still a complete, self-contained rail — their own `<aside>`, their own fetch lifecycle, their
   * own `panelState` — exactly as `BacklinksPanel` was before this card, so `App.svelte`'s existing
   * mount point changes by one component name and nothing about either panel's own behaviour or
   * tests had to move. That is deliberate: the alternative was pulling both panels' markup apart
   * into a shared header plus two content-only fragments, which would have put every existing
   * `data-testid="backlinks-…"` assertion at risk for a purely cosmetic gain (one border instead of
   * two). A tab strip above a self-contained pane costs one extra `<div>`; a merge costs a rewrite
   * of a component this card did not otherwise need to touch.
   *
   * **Only one tab's panel is mounted at a time.** Switching tabs unmounts the other rather than
   * hiding it with CSS, so a tab that is not showing holds no in-flight request and no stale
   * `AbortController` — the same "the rail's fetch lifecycle only exists while it can be seen" rule
   * `App.svelte`'s `railed` already applies one level up, applied again one level down.
   */
  const {
    note,
    onexpired,
    onrestored,
    id = 'supporting-pane',
  }: {
    /** Prefix for the tab and panel ids, and the element id the toggle's `aria-controls` names. */
    id?: string
    note: Note | null
    onexpired: (reason: string) => void
    onrestored: (stored: Note) => void
  } = $props()

  const TABS = ['backlinks', 'history'] as const
  let tab: (typeof TABS)[number] = $state('backlinks')

  /**
   * KAN-1827, the ARIA tabs pattern: one tab stop (the selected tab), Left/Right/Home/End move
   * focus and select (automatic activation, so the cheap tab needs no extra Enter).
   */
  function onTabKey(event: KeyboardEvent): void {
    const next = nextTabIndex(event.key, TABS.indexOf(tab), TABS.length)
    if (next === null) {
      return
    }
    event.preventDefault()
    tab = TABS[next]
    document.getElementById(`${id}-tab-${tab}`)?.focus()
  }
</script>

<div class="right-rail" {id}>
  {#if note?.team_id != null}
    <!-- ADR 0011, R16.7: sits above the tab strip rather than inside either tab's pane, since it
         is a fact about the note itself — not about its backlinks or its history — and stays
         visible whichever tab is open. -->
    <p class="team-note" data-testid="rail-team-badge">
      Shared by default with team {note.team_id}
    </p>
  {/if}
  <div class="tabs" role="tablist" aria-label="Note details">
    <button
      type="button"
      role="tab"
      onkeydown={onTabKey}
      id="{id}-tab-backlinks"
      aria-controls="{id}-panel"
      tabindex={tab === 'backlinks' ? 0 : -1}
      aria-selected={tab === 'backlinks'}
      class:active={tab === 'backlinks'}
      onclick={() => (tab = 'backlinks')}
      data-testid="rail-tab-backlinks"
    >
      Backlinks
    </button>
    <button
      type="button"
      role="tab"
      onkeydown={onTabKey}
      id="{id}-tab-history"
      aria-controls="{id}-panel"
      tabindex={tab === 'history' ? 0 : -1}
      aria-selected={tab === 'history'}
      class:active={tab === 'history'}
      onclick={() => (tab = 'history')}
      data-testid="rail-tab-history"
    >
      History
    </button>
  </div>
  <div class="pane" role="tabpanel" id="{id}-panel" aria-labelledby="{id}-tab-{tab}">
    {#if tab === 'backlinks'}
      <BacklinksPanel {note} {onexpired} />
    {:else}
      <HistoryPanel {note} {onexpired} {onrestored} />
    {/if}
  </div>
</div>

<style>
  .right-rail {
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
    background: var(--surface-container);
    border-left: 1px solid var(--outline-variant);
  }

  .team-note {
    flex: none;
    margin: 0.75rem 0.5rem 0;
    color: var(--on-surface-variant);
    font-size: var(--type-body-small-size);
  }

  /* M3 primary tabs: label colour for the selected tab, a 3px primary indicator under it. */
  .tabs {
    display: flex;
    flex: none;
    flex-wrap: wrap;
    padding: 0.5rem 0.5rem 0;
    border-bottom: 1px solid var(--outline-variant);
  }

  .tabs button {
    min-height: 2.5rem;
    padding: 0 1rem;
    border: 0;
    border-bottom: 3px solid transparent;
    border-radius: var(--shape-sm) var(--shape-sm) 0 0;
    background: transparent;
    color: var(--on-surface-variant);
    cursor: pointer;
    font: inherit;
    font-size: var(--type-label-large-size);
    font-weight: var(--type-label-large-weight);
  }

  .tabs button.active {
    border-bottom-color: var(--primary);
    color: var(--primary);
  }

  .pane {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
  }
</style>
