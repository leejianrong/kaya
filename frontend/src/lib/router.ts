/**
 * Two routes, forty lines, zero dependencies.
 *
 * `frontend/package.json` has only devDependencies today — Svelte compiles away, so the shipped
 * bundle carries no runtime code that isn't ours. A router library for `/` and `/notes/:ref` would
 * be the first crossing of that line, and it would buy nested layouts, route guards and loaders
 * that nothing in V3–V6 asks for. CodeMirror 6 is the first runtime dependency worth having and
 * that is KAN-553's deliberate crossing, measured in its own PR.
 *
 * **Parsing is a pure function and reactivity is not this module's business.** `parseRoute` takes a
 * string and returns a value, so it is testable in a node environment with no DOM, and `App.svelte`
 * holds the current route in a `$state` rune fed by {@link onNavigate}. A `$state` in here would
 * force this file to be `router.svelte.ts` and would put a reactive graph behind a pathname parser.
 *
 * The server side of this already works: `backend/app/spa.py` serves `index.html` for any
 * unreserved path, so `/notes/NOTE-4` pasted into the address bar loads the app and lands here.
 */

/** Where the app is. A closed union, so a new region has to be handled everywhere at once. */
export type Route =
  | { name: 'home' }
  | { name: 'note'; ref: string }
  | { name: 'unknown'; path: string }

/**
 * Which route a pathname names.
 *
 * `unknown` rather than a redirect to `/`: a mistyped or stale link should say so, and silently
 * rewriting the URL loses the evidence of what was actually clicked. KAN-555 decides what that
 * looks like on screen; this only has to name it.
 *
 * The ref is **not** validated against `NOTE-n` here. The backend's ref resolver is the single
 * place an identifier is parsed (`app/api/refs.py`), it accepts `NOTE-12`, `note-12` and `12`, and
 * it answers `#NOTE-12` with a `400`. A second, laxer copy of that grammar in the browser would
 * either reject something the API accepts or accept something it rejects, and both are bugs whose
 * fix is deleting the copy.
 */
export function parseRoute(pathname: string): Route {
  const path = normalize(pathname)

  if (path === '/') {
    return { name: 'home' }
  }

  const ref = path.startsWith('/notes/') ? decodeSegment(path.slice('/notes/'.length)) : null
  if (ref !== null && ref !== '' && !ref.includes('/')) {
    return { name: 'note', ref }
  }

  return { name: 'unknown', path }
}

/** The URL for a route. The inverse of {@link parseRoute} for the two real routes. */
export function routeHref(route: Route): string {
  switch (route.name) {
    case 'home':
      return '/'
    case 'note':
      return `/notes/${encodeURIComponent(route.ref)}`
    case 'unknown':
      return route.path
  }
}

/** The route the browser is on right now. `'/'` where there is no `location` (node tests). */
export function currentRoute(): Route {
  return parseRoute(globalThis.location?.pathname ?? '/')
}

type Listener = (route: Route) => void

const listeners = new Set<Listener>()

/**
 * A synchronous check consulted before every same-tab navigation this module drives, and the single
 * choke point KAN-969 asks for.
 *
 * `interceptClick` already funnels every link surface in the app through {@link navigate} — the
 * sidebar's flat list, its folder tree, and the backlinks rail all call it with the same two lines,
 * and the topbar's own brand link is a fourth — so this is where all of them, and any future caller,
 * get asked the same question once rather than being asked separately at each call site. Before this
 * card, none of them asked at all: a click discarded whatever the editor held, silently.
 *
 * `null` — the default — means "nothing to ask", which is the state before whatever registers a
 * guard has mounted, and the state again once it unmounts. There is a single slot rather than a set
 * of listeners like {@link onNavigate}'s: kaya has exactly one thing in the whole SPA that can be
 * unsaved right now (the open note's editor), and two independent guards firing in sequence for one
 * click would be a worse experience than either alone, not a more careful one.
 *
 * This module stays reactivity-free on purpose (see the file header), and the guard is how that
 * survives having to ask a person something: `navigate` only decides *whether* to consult it, never
 * *how* it decides or what it shows. Today's registered guard (`App.svelte`) answers with a native
 * `confirm()`; a future one could answer with something else entirely, and this file would not
 * change either way.
 */
type NavigationGuard = () => boolean

let guard: NavigationGuard | null = null

/** Register the check {@link navigate} consults before it moves, or clear it with `null`. */
export function setNavigationGuard(next: NavigationGuard | null): void {
  guard = next
}

/**
 * Subscribe to route changes, and get an unsubscribe back.
 *
 * `popstate` covers the back button; {@link navigate} notifies directly, because `pushState` does
 * **not** fire `popstate` — that asymmetry is the bug every hand-rolled router has once.
 */
export function onNavigate(listener: Listener): () => void {
  listeners.add(listener)
  globalThis.addEventListener?.('popstate', handlePopState)
  return () => {
    listeners.delete(listener)
    if (listeners.size === 0) {
      globalThis.removeEventListener?.('popstate', handlePopState)
    }
  }
}

function handlePopState(): void {
  announce(currentRoute())
}

function announce(route: Route): void {
  for (const listener of listeners) {
    listener(route)
  }
}

/**
 * Go to a path without a document load, and tell the app about it.
 *
 * Navigating to where we already are is a no-op rather than a duplicate history entry, so a
 * sidebar click on the open note does not make the back button appear to do nothing.
 */
export function navigate(path: string): void {
  const target = normalize(path)
  if (globalThis.location?.pathname === target) {
    return
  }
  if (guard !== null && !guard()) {
    // KAN-969: the registered guard vetoed this one (unsaved editor content, today). Neither the URL
    // nor the route changes, so the caller — `interceptClick`, which has already called
    // `preventDefault()` on the click that got here — is left exactly where it was, with whatever it
    // was about to lose still in front of it.
    return
  }
  globalThis.history?.pushState({}, '', target)
  announce(parseRoute(target))
}

/** An `<a>` handler: same-tab, unmodified left clicks are routed; everything else is the browser's. */
export function interceptClick(event: MouseEvent, path: string): void {
  if (event.defaultPrevented || event.button !== 0) {
    return
  }
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
    // Open-in-new-tab and friends. `spa.py` serves the app for these paths, so letting the browser
    // handle it produces a working page rather than a broken one.
    return
  }
  event.preventDefault()
  navigate(path)
}

/** Strip the query and fragment, collapse an empty path to `/`, and drop a trailing slash. */
function normalize(pathname: string): string {
  const withoutQuery = pathname.split(/[?#]/, 1)[0] ?? ''
  const rooted = withoutQuery.startsWith('/') ? withoutQuery : `/${withoutQuery}`
  if (rooted === '/') {
    return '/'
  }
  return rooted.endsWith('/') ? rooted.slice(0, -1) : rooted
}

/**
 * Percent-decode one path segment, tolerating a malformed escape.
 *
 * `decodeURIComponent('%')` throws, and a thrown parse turns a bad URL into a blank page. An
 * undecodable segment is passed through and becomes the backend's `404` or `400`, which is where an
 * identifier is judged anyway.
 */
function decodeSegment(segment: string): string {
  try {
    return decodeURIComponent(segment)
  } catch {
    return segment
  }
}
