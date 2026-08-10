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
