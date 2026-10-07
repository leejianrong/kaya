/**
 * Window size classes (KAN-1818), the M3 breakpoints, in one place.
 *
 * compact < 600 <= medium < 840 <= expanded. The CSS in `App.svelte`/`NavColumn.svelte`/
 * `Sidebar.svelte` mirrors these numbers in its media queries (CSS cannot import them);
 * `tests/window-class.test.ts` fails if a stylesheet uses a width that is not one of them.
 *
 * The class is the *structural* signal (which regions render at all); the media queries do the
 * pure styling. Both come from the same two numbers, so they cannot disagree about where a
 * class starts.
 */

export type WindowClass = 'compact' | 'medium' | 'expanded'

export const BREAKPOINTS = { medium: 600, expanded: 840 } as const

export const WINDOW_QUERIES = {
  medium: `(min-width: ${BREAKPOINTS.medium}px)`,
  expanded: `(min-width: ${BREAKPOINTS.expanded}px)`,
} as const

/** Pure: the class for a viewport width in CSS pixels. */
export function windowClassForWidth(width: number): WindowClass {
  if (width >= BREAKPOINTS.expanded) {
    return 'expanded'
  }
  return width >= BREAKPOINTS.medium ? 'medium' : 'compact'
}

interface Queries {
  medium: MediaQueryList
  expanded: MediaQueryList
}

function queries(): Queries | null {
  if (typeof globalThis.matchMedia !== 'function') {
    return null
  }
  return {
    medium: globalThis.matchMedia(WINDOW_QUERIES.medium),
    expanded: globalThis.matchMedia(WINDOW_QUERIES.expanded),
  }
}

function classOf(q: Queries): WindowClass {
  if (q.expanded.matches) {
    return 'expanded'
  }
  return q.medium.matches ? 'medium' : 'compact'
}

/**
 * The class right now. `expanded` where there is no `matchMedia` (node, jsdom): the full desktop
 * layout is the default, which is what every pre-KAN-1818 test was written against.
 */
export function currentWindowClass(): WindowClass {
  const q = queries()
  return q === null ? 'expanded' : classOf(q)
}

/** Call `listener` whenever the class changes; returns the unsubscribe. */
export function watchWindowClass(listener: (next: WindowClass) => void): () => void {
  const q = queries()
  if (q === null) {
    return () => {}
  }
  const handle = (): void => listener(classOf(q))
  q.medium.addEventListener('change', handle)
  q.expanded.addEventListener('change', handle)
  return () => {
    q.medium.removeEventListener('change', handle)
    q.expanded.removeEventListener('change', handle)
  }
}
