/**
 * What the shell renders for a window class and a route (KAN-1818) — pure, so it is unit-tested
 * without a browser. `App.svelte` is the only consumer.
 *
 * - **compact**: the list and the note are separate screens (`home` is the list; every other
 *   route is `main` alone). The backlinks/history rail is `on-demand`, behind a control.
 * - **medium**: list beside the note, the rail below the note.
 * - **expanded**: the original four regions.
 */

import type { Route } from './router'
import type { WindowClass } from './windowClass'

export interface Regions {
  /** The primary navigation (a bottom bar on compact, a rail otherwise). */
  nav: boolean
  /** The note list (`Sidebar`). */
  list: boolean
  /** `main`: the document, or graph/settings/etc. */
  main: boolean
  /** The backlinks/history rail: beside the note, below it, behind a control, or absent. */
  detail: 'none' | 'beside' | 'below' | 'on-demand'
}

export function shellRegions(windowClass: WindowClass, route: Route, authed: boolean): Regions {
  if (!authed) {
    // `tokens`/`device` are reachable with no credential and render in `main` alone (KAN-1739).
    return { nav: false, list: false, main: true, detail: 'none' }
  }
  const compact = windowClass === 'compact'
  const listRoute = route.name !== 'tokens' && route.name !== 'device'
  const list = listRoute && (!compact || route.name === 'home')
  const main = !(compact && route.name === 'home')
  let detail: Regions['detail'] = 'none'
  if (route.name === 'note') {
    detail = compact ? 'on-demand' : windowClass === 'medium' ? 'below' : 'beside'
  }
  return { nav: true, list, main, detail }
}

export interface NavDestination {
  label: string
  href: string
  isActive: (route: Route) => boolean
}

/** The three primary destinations. Tokens and the pandan link live under Settings. */
export const NAV_DESTINATIONS: readonly NavDestination[] = [
  { label: 'Notes', href: '/', isActive: (r) => r.name === 'home' || r.name === 'note' },
  { label: 'Graph', href: '/graph', isActive: (r) => r.name === 'graph' },
  {
    label: 'Settings',
    href: '/settings',
    isActive: (r) => r.name === 'settings' || r.name === 'tokens' || r.name === 'pandan',
  },
]

export function navActive(destination: NavDestination, route: Route): boolean {
  return destination.isActive(route)
}
