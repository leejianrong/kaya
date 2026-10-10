<!--
  KAY-165: the draggable edge of a side panel, a WAI-ARIA window splitter (`role="separator"`, focusable,
  `aria-valuenow/min/max` in px). The same component serves the list's right edge (`side="left"`)
  and the pane's left edge (`side="right"`); `lib/panels.ts` holds the arithmetic.

  Dragging does not re-render anything: each `pointermove` hands the clamped width to `onlive`, which
  only sets a CSS custom property on the shell, and the one state change (and the `localStorage`
  write) happens in `oncommit` on release. The pointer is captured, so the drag survives leaving the
  thin handle or the window; `touch-action: none` keeps a touch drag from scrolling the page.
-->
<script lang="ts">
  import { dragWidth, keyboardWidth, type PanelSide } from '../lib/panels'

  interface Props {
    side: PanelSide
    value: number
    min: number
    max: number
    /** What a double-click resets to. */
    fallback: number
    label: string
    /** The id of the panel it resizes (`aria-controls`). */
    controls?: string
    /** During a drag: apply the width cheaply (a CSS variable), do not touch state. */
    onlive: (width: number) => void
    /** A finished change (release, key, double-click): store it. */
    oncommit: (width: number) => void
  }

  const { side, value, min, max, fallback, label, controls, onlive, oncommit }: Props = $props()

  let dragging = $state(false)
  let startX = 0
  let startWidth = 0
  let latest = 0
  let previousSelect = ''

  function begin(event: PointerEvent): void {
    if (event.button !== 0) {
      return
    }
    const handle = event.currentTarget as HTMLElement
    handle.setPointerCapture(event.pointerId)
    startX = event.clientX
    startWidth = value
    latest = value
    dragging = true
    previousSelect = document.body.style.userSelect
    document.body.style.userSelect = 'none'
    document.body.classList.add('panel-resizing')
    event.preventDefault()
  }

  function move(event: PointerEvent): void {
    if (!dragging) {
      return
    }
    latest = dragWidth(startWidth, startX, event.clientX, side, min, max)
    onlive(latest)
  }

  function end(event: PointerEvent): void {
    if (!dragging) {
      return
    }
    dragging = false
    document.body.style.userSelect = previousSelect
    document.body.classList.remove('panel-resizing')
    const handle = event.currentTarget as HTMLElement
    if (handle.hasPointerCapture(event.pointerId)) {
      handle.releasePointerCapture(event.pointerId)
    }
    oncommit(latest)
  }

  function key(event: KeyboardEvent): void {
    if (event.altKey || event.ctrlKey || event.metaKey) {
      return
    }
    const next = keyboardWidth(event.key, event.shiftKey, value, side, min, max)
    if (next === null) {
      return
    }
    event.preventDefault()
    if (next !== value) {
      oncommit(next)
    }
  }
</script>

<!-- A focusable separator is the WAI-ARIA window splitter pattern; the a11y lint reads the role as
     non-interactive, so it is silenced here and the key/pointer handlers are the whole contract. -->
<!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
<div
  class="resizer {side}"
  class:dragging
  role="separator"
  aria-orientation="vertical"
  aria-label={label}
  aria-valuenow={value}
  aria-valuemin={min}
  aria-valuemax={max}
  aria-controls={controls}
  tabindex="0"
  title="Drag to resize, double-click to reset"
  onpointerdown={begin}
  onpointermove={move}
  onpointerup={end}
  onpointercancel={end}
  onlostpointercapture={end}
  ondblclick={() => oncommit(fallback)}
  onkeydown={key}
  data-testid="resizer-{side}"
></div>

<style>
  /* An 8px hit area centred on the panel's edge; the visible line is the pseudo-element. */
  .resizer {
    position: relative;
    z-index: 2;
    width: 0.5rem;
    cursor: col-resize;
    touch-action: none;
    outline: none;
  }

  /* `.shell` places the handle in the panel's grid area, on the edge it resizes. */
  .resizer.left {
    justify-self: end;
    margin-right: -0.25rem;
  }

  .resizer.right {
    justify-self: start;
    margin-left: -0.25rem;
  }

  .resizer::after {
    content: '';
    position: absolute;
    inset-block: 0;
    left: 50%;
    width: 1px;
    transform: translateX(-50%);
    background: var(--outline-variant);
    transition:
      width 120ms ease,
      background-color 120ms ease;
  }

  .resizer:hover::after,
  .resizer.dragging::after {
    width: 3px;
    background: var(--primary);
  }

  .resizer:focus-visible::after {
    width: 3px;
    background: var(--primary);
  }

  .resizer:focus-visible {
    outline: 2px solid var(--primary);
    outline-offset: -2px;
    border-radius: var(--shape-xs, 2px);
  }

  :global(body.panel-resizing) {
    cursor: col-resize;
  }

  @media (prefers-reduced-motion: reduce) {
    .resizer::after {
      transition: none;
    }
  }
</style>
