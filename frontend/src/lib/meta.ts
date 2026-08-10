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
