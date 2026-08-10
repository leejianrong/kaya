/**
 * The credential seam. **This is the only module in the SPA that knows what a bearer is.**
 *
 * Every request gets its `Authorization` from `authorization()` here, so the day a browser session
 * cookie becomes possible, one module changes and no `fetch` call site does. That is the whole
 * reason this file exists as a file rather than as two lines inside `api.ts`.
 *
 * ## Why a pasted PAT and not SSO
 *
 * Kaya mints nothing (ADR 0002): identity is a *pandan* PAT, forwarded to pandan's
 * `GET /api/v1/me`. Browser SSO is deferred on a hard fact rather than on effort — `fly.dev` is on
 * the Public Suffix List, so two `*.fly.dev` origins cannot share a cookie at all (Q7). There is
 * therefore deliberately no cookie scaffolding here to "grow into"; KAN-555 adds the paste form
 * against this seam and nothing else.
 *
 * ## Why `sessionStorage`
 *
 * Not `localStorage`, not a module-level variable, and the reasoning is specific to this token:
 *
 * - It is a pandan PAT, so exfiltrating it hands over the kanban board too. The blast radius is a
 *   sibling product, not this one.
 * - KAN-554's live preview renders **user markdown to HTML in this same origin**. That is a real
 *   injection surface with a date on it, not a hypothetical one.
 * - `sessionStorage` dies with the tab. `localStorage` would outlive the browser, so one bad
 *   preview render months later still reaches a live credential.
 * - In-memory would survive neither a reload nor `/notes/NOTE-4` being pasted into the address bar,
 *   which makes the app unusable and teaches the user to keep the PAT on the clipboard instead.
 *
 * ## The rule that has no exceptions
 *
 * **The token never enters a URL, a log line, an error message, or the DOM.** `kaya-cli`'s
 * `config show` is the reference for how seriously this repo takes that: it prints `set` or
 * `not set` and never a prefix, a suffix or a length, because four characters of a live credential
 * in a command documented as safe to paste is still four characters of a live credential. The
 * browser equivalent is worse, because a screenshot and a screen share are both one keystroke away.
 * So the only state this module will describe is {@link credentialState}, which returns
 * `'set' | 'not set'`, and `tests/auth.test.ts` sweeps every contiguous four-character fragment of
 * a fake token across everything this module exposes.
 */

/**
 * The `sessionStorage` key. Namespaced, because the SPA shares an origin with the API and could
 * one day share it with something else.
 */
const STORAGE_KEY = 'kaya.token'

/**
 * `sessionStorage`, or `null` where there isn't one.
 *
 * Looked up per call rather than captured at module load: a private-mode browser can throw on
 * access, and a node-environment test importing this module for its pure helpers must not explode
 * at import time.
 */
function store(): Storage | null {
  try {
    return globalThis.sessionStorage ?? null
  } catch {
    // Access itself throws under some privacy settings. A missing store is not an error here —
    // it means "no credential", which the landing state (KAN-555) already has to handle.
    return null
  }
}

/**
 * Any C0 control character, or `DEL`.
 *
 * A scan rather than a character class, because a class holding literal control characters is an
 * eslint error (`no-control-regex`) and an escaped one is a line nobody reviews properly.
 */
function hasControlCharacter(value: string): boolean {
  for (const character of value) {
    const code = character.codePointAt(0) ?? 0
    if (code < 0x20 || code === 0x7f) {
      return true
    }
  }
  return false
}

/**
 * A credential we are willing to put in a header, or `null`.
 *
 * Whitespace-only is `null` because a paste form will produce it. Control characters are refused
 * outright: a `\r\n` in a header value is request splitting, and `fetch` would throw a `TypeError`
 * whose message — in some engines — contains the offending value. Refusing here means the token
 * cannot reach a stack trace.
 */
function usable(raw: string | null | undefined): string | null {
  if (typeof raw !== 'string') {
    return null
  }
  const trimmed = raw.trim()
  if (trimmed === '' || hasControlCharacter(trimmed)) {
    return null
  }
  return trimmed
}

/** Whether this string could be stored as a credential. Cheap enough for a paste form to call. */
export function isUsableToken(raw: string | null | undefined): boolean {
  return usable(raw) !== null
}

/**
 * The stored bearer, or `null`.
 *
 * Exported because `authorization()` cannot be the only reader — KAN-555 needs to know whether to
 * show the landing state — but call {@link hasToken} for that, and treat this return value the way
 * you would treat the token itself: it goes into a header and nowhere else.
 */
export function getToken(): string | null {
  return usable(store()?.getItem(STORAGE_KEY))
}

/**
 * Store a credential for this tab. An unusable value **clears** rather than storing junk that would
 * come back as a `401` on every request with no way for the user to tell why.
 */
export function setToken(raw: string): void {
  const token = usable(raw)
  if (token === null) {
    clearToken()
    return
  }
  try {
    store()?.setItem(STORAGE_KEY, token)
  } catch {
    // A full or unavailable store is a "no credential" state, not a crash. Nothing is logged,
    // because the failing call had the token as an argument and some engines echo arguments.
  }
}

export function clearToken(): void {
  try {
    store()?.removeItem(STORAGE_KEY)
  } catch {
    // Nothing useful to do, and nothing safe to say.
  }
}

export function hasToken(): boolean {
  return getToken() !== null
}

/**
 * The only thing in this codebase allowed to *describe* the credential to a person.
 *
 * Two values, ever. Not a length, not a prefix, not a masked form — a mask is a fragment with
 * asterisks in front of it, and pandan shipped exactly that (`set (…c_DE)`) before KAN-551 took it
 * out.
 */
export function credentialState(): 'set' | 'not set' {
  return hasToken() ? 'set' : 'not set'
}

/**
 * The `Authorization` value for a request, or `null` when there is no credential.
 *
 * `api.ts` is the only caller. It returns `null` rather than an empty header so an unauthenticated
 * request is a deliberate one — an `Authorization: Bearer ` with nothing after it is a `401` that
 * looks like a bad token instead of a missing one.
 */
export function authorization(): string | null {
  const token = getToken()
  return token === null ? null : `Bearer ${token}`
}
