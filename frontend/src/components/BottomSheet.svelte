<script lang="ts">
  import type { Snippet } from 'svelte'

  import { shouldDismissDrag, wrapFocusIndex } from '../lib/sheet'
  import { watchViewport } from '../lib/viewport'

  /**
   * KAN-1827: a modal bottom sheet. Mounted only while open (`{#if}` in the caller), so everything
   * here is set up on mount and undone on destroy.
   *
   * Behaviour a modal owes its user: focus moves in and returns to whatever opened it; Escape, the
   * scrim, the close button and a downward drag of the handle all close it; Tab stays inside; the
   * page behind does not scroll. The soft keyboard's inset (`lib/viewport.ts`) lifts it, and the
   * safe-area inset pads it, so neither covers its content.
   */
  const {
    label,
    onclose,
    children,
  }: { label: string; onclose: () => void; children: Snippet } = $props()

  let dialog: HTMLElement | undefined = $state()
  let inset = $state(0)
  let drag = $state(0)
  let dragging = $state(false)
  let startY = 0

  $effect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const stopWatching = watchViewport((next) => (inset = next))
    // Into the sheet: the selected tab, which is the one stop of its tablist.
    const first = dialog?.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]')
    ;(first ?? dialog)?.focus()
    return () => {
      document.body.style.overflow = previousOverflow
      stopWatching()
      if (opener?.isConnected) {
        opener.focus()
      }
    }
  })

  /** Tab stops only: a `tabindex="-1"` control (the unselected tab) is not one, and neither is a
   *  disabled button (Refresh while loading). Counting either made the wrap miss the last stop. */
  const FOCUSABLE =
    ':is(a[href], button, input, textarea, select, [tabindex]):not([tabindex="-1"]):not([disabled])'

  function onkeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      onclose()
      return
    }
    if (event.key !== 'Tab' || dialog === undefined) {
      return
    }
    const items = [...dialog.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(
      (el) => el.offsetParent !== null || el === document.activeElement,
    )
    const target = wrapFocusIndex(items.indexOf(document.activeElement as HTMLElement), items.length, event.shiftKey)
    if (target !== null) {
      event.preventDefault()
      items[target].focus()
    }
  }

  function dragStart(event: PointerEvent): void {
    dragging = true
    startY = event.clientY
    ;(event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId)
  }

  function dragMove(event: PointerEvent): void {
    if (dragging) {
      drag = Math.max(0, event.clientY - startY)
    }
  }

  function dragEnd(): void {
    if (!dragging) {
      return
    }
    dragging = false
    const dismiss = shouldDismissDrag(drag)
    drag = 0
    if (dismiss) {
      onclose()
    }
  }
</script>

<svelte:window {onkeydown} />

<div class="scrim" role="presentation" onclick={onclose} data-testid="sheet-scrim"></div>
<div
  bind:this={dialog}
  class="sheet"
  class:dragging
  role="dialog"
  aria-modal="true"
  aria-label={label}
  tabindex="-1"
  style:--sheet-inset="{inset}px"
  style:transform={drag > 0 ? `translateY(${drag}px)` : undefined}
  data-testid="links-sheet"
>
  <div
    class="grab"
    role="presentation"
    onpointerdown={dragStart}
    onpointermove={dragMove}
    onpointerup={dragEnd}
    onpointercancel={dragEnd}
    data-testid="sheet-handle"
  >
    <span></span>
  </div>
  <div class="head">
    <h2>{label}</h2>
    <button type="button" class="close" aria-label="Close" onclick={onclose} data-testid="sheet-close">
      <span aria-hidden="true">&times;</span>
    </button>
  </div>
  <div class="content">
    {@render children()}
  </div>
</div>

<style>
  .scrim {
    position: fixed;
    inset: 0;
    z-index: 30;
    background: rgb(0 0 0 / 0.42);
  }

  /* The note stays visible above it: at most 70% of the visible height, less the keyboard. */
  .sheet {
    position: fixed;
    right: 0;
    bottom: var(--sheet-inset, 0px);
    left: 0;
    z-index: 31;
    display: flex;
    flex-direction: column;
    max-height: min(70dvh, calc(100dvh - var(--sheet-inset, 0px) - 4rem));
    padding-bottom: env(safe-area-inset-bottom, 0px);
    border-radius: 28px 28px 0 0;
    background: var(--surface-2);
    box-shadow: var(--shadow-md);
    outline: none;
  }

  .sheet.dragging {
    transition: none;
  }

  .grab {
    display: grid;
    flex: none;
    place-items: center;
    height: 1.75rem;
    cursor: grab;
    touch-action: none;
  }

  .grab span {
    width: 2rem;
    height: 0.25rem;
    border-radius: 0.125rem;
    background: var(--muted);
    opacity: 0.6;
  }

  .head {
    display: flex;
    flex: none;
    align-items: center;
    justify-content: space-between;
    padding: 0 0.5rem 0 1.25rem;
  }

  h2 {
    margin: 0;
    font-size: 1rem;
    font-weight: 600;
  }

  .close {
    min-width: 2.75rem;
    min-height: 2.75rem;
    border: 0;
    border-radius: 50%;
    background: transparent;
    color: var(--muted);
    cursor: pointer;
    font: inherit;
    font-size: 1.5rem;
    line-height: 1;
  }

  .close:hover {
    background: var(--hover);
  }

  .content {
    display: flex;
    flex: 1;
    flex-direction: column;
    min-height: 0;
  }

  /* The rail was built to be a column of the shell; in the sheet it is the sheet's body. */
  .content :global(.right-rail) {
    flex: 1;
    border: 0;
    background: transparent;
  }

  .content :global(.right-rail .tabs button) {
    min-height: 2.75rem;
    padding-inline: 1rem;
  }

  @media (prefers-reduced-motion: no-preference) {
    .scrim {
      animation: fade 0.2s ease-out;
    }

    .sheet {
      animation: rise 0.25s ease-out;
    }

    @keyframes fade {
      from {
        opacity: 0;
      }
    }

    @keyframes rise {
      from {
        transform: translateY(100%);
      }
    }
  }
</style>
