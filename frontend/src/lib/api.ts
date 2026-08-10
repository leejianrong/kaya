/**
 * How the SPA addresses the API, and the one place a request is made.
 *
 * Same-origin, always relative. In production one artifact serves both the SPA and `/api/v1`
 * (ADR 0001); in development Vite's proxy forwards `/api` to the backend on :8000. Both only
 * work if the SPA never builds an absolute URL — an origin baked in at build time is how a
 * frontend ends up needing a per-environment build and a CORS policy to go with it.
 *
 * ## Where this sits relative to ADR 0004, because the obvious reading is wrong
 *
 * The SPA is **not** a `render()` adapter and cannot be one: `kaya-client` is Python. ADR 0004
 * §Decision already anticipated exactly this consumer — *"The API does not use `render` — it
 * returns full records, because HTTP has content negotiation and a browser client that wants
 * everything."* So a browser reading complete records is the sanctioned path, not a gap in the
 * rule. Two consequences, and they are the reason this paragraph is in a source file rather than
 * only in an ADR:
 *
 * - **The SPA must never implement a shaping concern.** No `--fields`-style projection, no
 *   truncation-with-a-hint, no `{"count": n}` aggregate. Those exist because an *agent* pays per
 *   token for a payload it cannot scroll; a browser scrolls, and its user has already downloaded
 *   the bytes. A copy of any of them here would be the second implementation ADR 0004 exists to
 *   prevent — the one that drifts, and the one pandan paid 44,902 tokens for.
 * - **Rendering markdown to HTML for preview is presentation, not payload shaping**, and belongs
 *   in the SPA. The line is: shaping decides *which bytes a caller receives*; presentation decides
 *   *what a person sees of the bytes they already have*. KAN-554's preview is squarely the second,
 *   and does not need permission from ADR 0004 to exist.
 *
 * If a future card wants fewer fields over the wire for a browser reason (a list of 10,000 notes),
 * that is a change to the *API* — a documented query parameter with a schema — and not a client-side
 * projection wearing the same name as `--fields`.
 */

import { authorization } from './auth'
import { isApiErrorBody } from './types'

export const API_BASE = '/api/v1'

/** Join a path onto the API base, tolerating a leading slash or its absence. */
export function apiPath(path: string): string {
  if (/^[a-z][a-z0-9+.-]*:/i.test(path) || path.startsWith('//')) {
    throw new Error(`apiPath expects a relative path, got an absolute URL: ${path}`)
  }
  const trimmed = path.replace(/^\/+/, '')
  return trimmed === '' ? API_BASE : `${API_BASE}/${trimmed}`
}

/**
 * A refusal from the API, typed.
 *
 * Carries the `status` **and** the `code`, because they answer different questions and the client
 * must not derive one from the other: `kaya-cli` keys its exit table on the *status* precisely
 * because the backend's code vocabulary grows without the client's knowledge. A UI branch on
 * "should I show the sign-in prompt" is a status question (401); a branch on "is this ADR 0009's
 * conflict" is a 409 question; a branch on which field a 422 named is a `details` question.
 *
 * `message` is the API's own prose, shown as-is. It never contains a credential — the backend's
 * redaction sits at log serialization and no refusal echoes an `Authorization` header — and nothing
 * on this class builds a message out of a request header either.
 */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  /** Everything beyond `code`/`message`: `field` on a 422, two whole notes on ADR 0009's 409. */
  readonly details: Record<string, unknown>

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }

  /** ADR 0009's optimistic-concurrency refusal. KAN-556's banner branches on this. */
  get isConflict(): boolean {
    return this.status === 409
  }

  /** No usable credential. KAN-555's landing state branches on this. */
  get isUnauthenticated(): boolean {
    return this.status === 401
  }
}

/** The transport failed, so there is no status and no code to report. */
export class NetworkError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'NetworkError'
  }
}

/** No credential in the seam, so no request was made. Same shape as the API's own 401. */
export class MissingCredential extends ApiError {
  constructor() {
    super(401, 'no_credential', 'No pandan token in this tab. Paste one to continue.')
    this.name = 'MissingCredential'
  }
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE'
  /** Serialized as JSON. Absent means no body and no `Content-Type`. */
  body?: unknown
  signal?: AbortSignal
  /** Injectable for tests. Defaults to the ambient `fetch`. */
  fetchImpl?: typeof fetch
}

/**
 * One request against `/api/v1`, authenticated from the credential seam.
 *
 * The bearer comes from `auth.authorization()` and goes into a **header** — never a query
 * parameter, never a path segment. That is not a style preference: a URL reaches the browser
 * history, the referrer, a proxy access log and the backend's own request line, and kaya's
 * observability rules (Q41/Q42) exist because a log line is the cheapest way to give a credential
 * away. `tests/api.test.ts` asserts the token appears in no URL this module builds.
 *
 * Returns `null` for a `204`, which is what `DELETE /notes/{ref}` answers.
 */
export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, signal, fetchImpl } = options
  const url = apiPath(path)

  const bearer = authorization()
  if (bearer === null) {
    // Refused before the request rather than after a 401, so an unauthenticated app does not
    // hammer the backend — and so the landing state is reached without a round trip.
    throw new MissingCredential()
  }

  const headers: Record<string, string> = {
    Accept: 'application/json',
    Authorization: bearer,
  }
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
  }

  const doFetch = fetchImpl ?? globalThis.fetch
  let response: Response
  try {
    response = await doFetch(url, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
      // Same-origin by construction, so no credentials mode games and no preflight.
      credentials: 'same-origin',
    })
  } catch {
    // The original error is deliberately **not** chained on as `{ cause }`: the failing call had
    // the header object as an argument, and a chained cause is what a console logger prints in
    // full. What is lost is a DNS-vs-refused distinction the browser devtools already show.
    throw new NetworkError(`Could not reach the kaya API at ${url}`)
  }

  if (response.status === 204) {
    return null as T
  }

  const payload = await readJson(response)

  if (!response.ok) {
    if (isApiErrorBody(payload)) {
      const { code, message, ...details } = payload.error
      throw new ApiError(response.status, code, message, details)
    }
    // The one shape the backend does not produce — a proxy's own error page, or the SPA's
    // index.html coming back because the dev proxy stopped forwarding. Say which, because
    // "unexpected token < in JSON" is the debugging session this branch exists to skip.
    throw new ApiError(
      response.status,
      'unexpected_response',
      `The API answered ${response.status} without kaya's error shape. ` +
        `Is something other than the kaya backend serving ${url}?`,
    )
  }

  return payload as T
}

async function readJson(response: Response): Promise<unknown> {
  const text = await response.text()
  if (text === '') {
    return null
  }
  try {
    return JSON.parse(text) as unknown
  } catch {
    return null
  }
}
