<script lang="ts">
  import { availableModes, type NoteMode } from '../lib/noteMode'
  import type { WindowClass } from '../lib/windowClass'

  /**
   * The Read | Edit | Split segmented control (KAN-1819), M3's segmented button: one fully round
   * outline, the selected segment tonal-filled. A group of real `<button aria-pressed>`s, so Tab,
   * Enter and Space work with no script and a screen reader says "pressed" for the current one.
   *
   * Presentation only: which modes exist is `lib/noteMode.ts`'s `availableModes`, and a mode the
   * class does not offer is **absent** (never `disabled`), the way the sidebar's tree toggle hides
   * while a search is on.
   */
  const {
    mode,
    windowClass,
    onchange,
  }: {
    mode: NoteMode
    windowClass: WindowClass
    onchange: (next: NoteMode) => void
  } = $props()

  const LABELS: Record<NoteMode, string> = { read: 'Read', edit: 'Edit', split: 'Split' }

  const modes = $derived(availableModes(windowClass))
</script>

<div class="mode-switch" role="group" aria-label="View mode" data-testid="mode-switch">
  {#each modes as option (option)}
    <button
      type="button"
      class:selected={mode === option}
      aria-pressed={mode === option}
      onclick={() => onchange(option)}
      data-testid="mode-{option}"
    >
      {LABELS[option]}
    </button>
  {/each}
</div>

<style>
  .mode-switch {
    display: inline-flex;
    min-width: 0;
    overflow: hidden;
    border: 1px solid var(--border);
    border-radius: 999px;
  }

  button {
    min-height: 2.25rem;
    padding: 0 1.1rem;
    border: 0;
    border-right: 1px solid var(--border);
    background: transparent;
    color: var(--text);
    cursor: pointer;
    font: inherit;
    font-size: 0.85rem;
    font-weight: 600;
  }

  button:last-child {
    border-right: 0;
  }

  button.selected {
    background: var(--accent-soft);
    color: var(--accent);
  }

  /* Inset, so the ring is not clipped by the pill's `overflow: hidden`. */
  button:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: -2px;
  }

  /* Compact: a touch target, and the whole width — three segments (or two) share the row. */
  @media (max-width: 599.98px) {
    .mode-switch {
      display: flex;
      width: 100%;
    }

    button {
      flex: 1;
      min-height: 2.75rem;
    }
  }
</style>
