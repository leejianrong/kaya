/**
 * KAN-1827: keyboard handling for the ARIA tabs pattern (horizontal, automatic activation). Pure, so
 * it is unit-tested without a browser; `RightRail.svelte` moves focus and selection to the index
 * this returns.
 */

/** The index a key moves to, or `null` when the key is not a tab-navigation key. */
export function nextTabIndex(key: string, current: number, count: number): number | null {
  if (count <= 0) {
    return null
  }
  switch (key) {
    case 'ArrowRight':
      return (current + 1) % count
    case 'ArrowLeft':
      return (current - 1 + count) % count
    case 'Home':
      return 0
    case 'End':
      return count - 1
    default:
      return null
  }
}
