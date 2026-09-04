<script lang="ts">
  import BacklinksPanel from './BacklinksPanel.svelte'
  import HistoryPanel from './HistoryPanel.svelte'
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
  }: {
    note: Note | null
    onexpired: (reason: string) => void
    onrestored: (stored: Note) => void
  } = $props()

  let tab: 'backlinks' | 'history' = $state('backlinks')
</script>

<div class="right-rail">
  <div class="tabs" role="tablist" aria-label="Note details">
    <button
      type="button"
      role="tab"
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
      aria-selected={tab === 'history'}
      class:active={tab === 'history'}
      onclick={() => (tab = 'history')}
      data-testid="rail-tab-history"
    >
      History
    </button>
  </div>
  <div class="pane" role="tabpanel">
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
    background: var(--surface-2);
    border-left: 1px solid var(--border);
  }

  .tabs {
    display: flex;
    flex: none;
    gap: 0.25rem;
    padding: 0.75rem 0.5rem 0;
  }

  .tabs button {
    padding: 0.3rem 0.6rem;
    border: 1px solid transparent;
    border-radius: 0.35rem 0.35rem 0 0;
    background: transparent;
    color: var(--muted);
    cursor: pointer;
    font: inherit;
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }

  .tabs button.active {
    border-color: var(--border);
    border-bottom-color: transparent;
    color: inherit;
  }

  .pane {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
  }
</style>
