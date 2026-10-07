/**
 * `/api/v1/pandan-link` (ADR 0012's amendment, KAN-1741) — connecting a kaya account to a pandan
 * PAT so the board-embed preview has something of pandan's own to forward.
 *
 * Plain `apiRequest` calls, not `lib/identity.ts`'s cookie-only `identityRequest` — unlike minting
 * kaya's *first* PAT (`Tokens.svelte`'s chicken-and-egg reasoning), connecting a pandan account has
 * no bootstrap problem: a caller reaching this page is already inside the authenticated shell,
 * holding the same `kaya_pat_…` bearer (`lib/auth.ts`) every other note-API call already sends, and
 * the backend's `get_principal` accepts that bearer here exactly as it does everywhere else
 * (`app/api/pandan_link.py`'s module docstring).
 *
 * **Never handles the pandan token as anything but a short-lived local value.** It is typed into a
 * form, sent once as a request body, and never stored anywhere in this tab — kaya's backend is what
 * persists it (encrypted), and this module has no reason to remember it any longer than the one
 * `fetch` call needs.
 */

import { apiRequest, type RequestOptions } from './api'

type Options = Pick<RequestOptions, 'signal' | 'fetchImpl'>

export interface PandanLinkStatus {
  connected: boolean
}

/** Whether the caller has a linked pandan account right now. */
export function fetchPandanLinkStatus(options: Options = {}): Promise<PandanLinkStatus> {
  return apiRequest<PandanLinkStatus>('pandan-link', options)
}

/**
 * Connect (or replace) the caller's linked pandan account. The backend verifies `token` against
 * pandan's own `GET /api/v1/me` before storing anything — a rejected token surfaces as an
 * `ApiError` with `code: "invalid_pandan_token"` (`status: 422`), and pandan being unreachable as
 * `code: "pandan_unavailable"` (`status: 503`); this function does not distinguish them, the same
 * "let the caller read the message" posture every other `ApiError`-throwing call in this repo
 * takes.
 */
export function connectPandanLink(
  token: string,
  options: Options = {},
): Promise<PandanLinkStatus> {
  return apiRequest<PandanLinkStatus>('pandan-link', {
    ...options,
    method: 'POST',
    body: { token },
  })
}

/** Disconnect. Idempotent on the wire (`app/api/pandan_link.py`'s own docstring) — calling this
 * with nothing connected still resolves to `{ connected: false }` rather than rejecting. */
export function disconnectPandanLink(options: Options = {}): Promise<PandanLinkStatus> {
  return apiRequest<PandanLinkStatus>('pandan-link', { ...options, method: 'DELETE' })
}
