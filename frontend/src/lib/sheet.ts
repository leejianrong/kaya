/**
 * KAN-1827: the pure parts of the bottom sheet (`components/BottomSheet.svelte`), unit-tested without
 * a browser.
 */

/** A downward drag of the handle at least this far (CSS px) closes the sheet. */
export const DISMISS_DRAG_PX = 80

export function shouldDismissDrag(deltaY: number): boolean {
  return deltaY >= DISMISS_DRAG_PX
}

/**
 * Where Tab should land to keep focus inside a modal: the index to focus when the browser would
 * leave the list (forward off the last, backward off the first), else `null` to let it move
 * normally. A `current` of `-1` is focus outside the list, which counts as being before the start.
 */
export function wrapFocusIndex(current: number, count: number, backwards: boolean): number | null {
  if (count <= 0) {
    return null
  }
  if (current < 0) {
    return backwards ? count - 1 : 0
  }
  if (backwards && current === 0) {
    return count - 1
  }
  if (!backwards && current === count - 1) {
    return 0
  }
  return null
}
