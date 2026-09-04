/**
 * `GET /api/v1/meta` — where the landing state learns pandan's origin (KAN-555).
 *
 * The SPA cannot read `KAYA_PANDAN_URL`: it is backend configuration and this is a browser. It also
 * must not learn it any of the other two ways — a literal in the source duplicates configuration
 * that has one home and breaks a self-hosted pandan (which ADR 0002 supports), and a build-time
 * `VITE_PANDAN_URL` is the per-environment bundle `api.ts` refuses in its header and ADR 0001's
 * one-artifact promise forbids. So it comes over the wire, from a route with no credential in front
 * of it, which is the one shape that works for a visitor who has no credential yet.
 */

import { publicRequest, type PublicOptions } from './api'

/** The whole of `/api/v1/meta`. One key — see `backend/app/api/meta.py` on why it stays one. */
export interface Meta {
  pandan_url: string
}

export function fetchMeta(options: PublicOptions = {}): Promise<Meta> {
  return publicRequest<Meta>('meta', options)
}

/**
 * The origin as something safe to put in an `href`, or `null`.
 *
 * `http:` and `https:` only. The value comes from the operator's own environment rather than from a
 * caller, so this is not a defence against an attacker so much as against a **mistake**: an
 * `href` is one of the few places in a Svelte template where a string is not escaped into text but
 * interpreted, and `javascript:` in one is script execution in kaya's origin — the origin holding
 * the credential in `sessionStorage`. A misconfigured env var should produce a missing link, not a
 * live one pointing somewhere unexpected.
 *
 * Anything unparseable is `null` too, so the landing state can say "your operator has not
 * configured this" instead of rendering a dead link.
 */
export function pandanHref(origin: string | null | undefined): string | null {
  if (typeof origin !== 'string' || origin.trim() === '') {
    return null
  }
  let parsed: URL
  try {
    parsed = new URL(origin.trim())
  } catch {
    return null
  }
  return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.href : null
}

/**
 * `fetchMeta` and `pandanHref`, composed into the one call every mount site actually wants: the
 * resolved href, or `null` if the fetch failed, the origin is unset, or it is unsafe to link to.
 *
 * KAN-555's `Landing.svelte` was the only caller of `fetchMeta`/`pandanHref`, so the
 * `.then(...).catch(() => null)` shape lived inline there. KAN-1156 lifts it out because the
 * authenticated shell (`App.svelte`) is about to need the same resolved value (KAN-1157, a pandan
 * nav link) — a second component writing the same fetch-then-parse-then-swallow-the-error chain is
 * exactly the kind of duplication that drifts the day one call site's error handling changes and
 * the other's doesn't. `App.svelte` does not call this yet: KAN-1157 is the card that renders the
 * link and reads the value, and there is nothing else in the authenticated shell today that would
 * use a `$state` written but never read (`noUnusedLocals` in `tsconfig.json` rejects that).
 *
 * **Deliberately not cached.** Each caller already needs its own mount-scoped `$state` and
 * `AbortController` (a loading flag, an unmount before the response arrives), so this stays a plain
 * function rather than a module-level store — the reactive lifecycle is the caller's, same as
 * `lib/auth.ts`'s `getToken()` leaving `sessionStorage` itself un-cached and un-reactive. A second
 * request per page load for a small, unauthenticated, unversioned GET is cheaper than a cache with
 * abort-vs-failure semantics to get wrong.
 */
export function resolvePandanHref(options: PublicOptions = {}): Promise<string | null> {
  return fetchMeta(options)
    .then((meta) => pandanHref(meta.pandan_url))
    .catch(() => null)
}
