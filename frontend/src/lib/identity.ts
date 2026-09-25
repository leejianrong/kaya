/**
 * Kaya's own cookie-session identity (ADR 0012, KAN-1739) — GitHub login, logout, and PAT
 * self-service. **Deliberately separate from `lib/api.ts`/`lib/auth.ts`.**
 *
 * `lib/auth.ts`'s whole argument is "one module owns the bearer", and that module's bearer is a
 * pasted `kaya_pat_…` (or, until KAN-1740, a pandan PAT) sent as an `Authorization` header. This
 * module authenticates a **different** way — a same-origin, httpOnly session cookie kaya's own
 * backend sets on GitHub login (`app/identity/`) — and exists specifically so a caller can mint
 * their *first* PAT without already holding one. Reusing `apiRequest` here would be wrong twice
 * over: it throws before the request when no bearer is set (exactly the state a first-time visitor
 * is in), and it would attach a bearer this seam has no business sending.
 *
 * No credential ever passes through this module's own code — the cookie is attached by the browser
 * automatically (`credentials: 'same-origin'`, harmless here since the SPA and the API already
 * share an origin, ADR 0010) and read only by the backend. There is nothing here for
 * `tests/auth.test.ts`-style fragment-sweeping to check, because there is no string to leak.
 */

const IDENTITY_ERROR_CODE = 'identity_error'

/** A refusal from `/auth/*`, `/users/*` or `/api/v1/tokens` — kaya's error shape, same as `ApiError`
 * but kept as its own class: this seam has no bearer to be "missing", so `ApiError.isUnauthenticated`
 * meaning "no credential in this tab" would be the wrong claim for a caller who is simply logged
 * out. */
export class IdentityError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'IdentityError'
    this.status = status
  }

  get isUnauthenticated(): boolean {
    return this.status === 401
  }
}

export interface CurrentUser {
  id: string
  email: string
}

export type TokenScope = 'read' | 'write'

export interface TokenSummary {
  id: number
  name: string
  token_prefix: string
  scope: TokenScope
  created_at: string
  last_used_at: string | null
  expires_at: string | null
}

/** Only ever present on the response to {@link createToken} — see that function's own note. */
export interface CreatedToken extends TokenSummary {
  token: string
}

export interface IdentityRequestOptions {
  /** Injectable for tests. Defaults to the ambient `fetch`. */
  fetchImpl?: typeof fetch
  signal?: AbortSignal
}

async function identityRequest<T>(
  path: string,
  init: RequestInit,
  options: IdentityRequestOptions = {},
): Promise<T> {
  const doFetch = options.fetchImpl ?? globalThis.fetch
  const response = await doFetch(path, {
    ...init,
    headers: { Accept: 'application/json', ...init.headers },
    signal: options.signal,
    // Same-origin by construction (ADR 0010): this is what lets the browser attach the session
    // cookie kaya's own `/auth/github/callback` set, with no CORS surface to configure.
    credentials: 'same-origin',
  })

  if (response.status === 204) {
    return null as T
  }

  const text = await response.text()
  const payload: unknown = text === '' ? null : safeParse(text)

  if (!response.ok) {
    const message = errorMessage(payload) ?? `${IDENTITY_ERROR_CODE}: ${response.status}`
    throw new IdentityError(response.status, message)
  }

  return payload as T
}

function safeParse(text: string): unknown {
  try {
    return JSON.parse(text) as unknown
  } catch {
    return null
  }
}

function errorMessage(payload: unknown): string | null {
  if (
    payload !== null &&
    typeof payload === 'object' &&
    'error' in payload &&
    typeof (payload as { error: unknown }).error === 'object' &&
    (payload as { error: { message?: unknown } }).error !== null
  ) {
    const message = (payload as { error: { message?: unknown } }).error.message
    return typeof message === 'string' ? message : null
  }
  return null
}

/**
 * Who the current cookie session is, or `null` if there isn't one.
 *
 * `null` rather than a thrown `401` for the one call site (`Tokens.svelte`'s mount check) that asks
 * this precisely to decide *whether* to show a sign-in prompt — the same shape KAN-555's landing
 * state gave `credentialState()` for the bearer seam, so a logged-out visitor is an expected state
 * to render rather than a caught exception to recover from.
 */
export async function fetchCurrentUser(options: IdentityRequestOptions = {}): Promise<CurrentUser | null> {
  try {
    return await identityRequest<CurrentUser>('/users/me', { method: 'GET' }, options)
  } catch (error) {
    if (error instanceof IdentityError && error.isUnauthenticated) {
      return null
    }
    throw error
  }
}

/**
 * The GitHub OAuth authorization URL to send the browser to.
 *
 * Returns the URL rather than navigating itself — pandan's own build (ADR 0011's "build-revealed
 * detail") found the same shape necessary: `GET /auth/github/authorize` answers `{
 * "authorization_url": … }`, JSON, not a redirect, so the caller does the
 * `window.location.assign(...)` explicitly. Kept as two steps here for the same reason: a bare
 * `<a href="/auth/github/authorize">` would GET the JSON, not the redirect a person expects.
 */
export async function githubLoginUrl(options: IdentityRequestOptions = {}): Promise<string> {
  const { authorization_url: url } = await identityRequest<{ authorization_url: string }>(
    '/auth/github/authorize',
    { method: 'GET' },
    options,
  )
  return url
}

/** Ends the cookie session — a `kaya_session` row delete on the backend, i.e. instant revocation. */
export async function logout(options: IdentityRequestOptions = {}): Promise<void> {
  await identityRequest<null>('/auth/logout', { method: 'POST' }, options)
}

export async function listTokens(options: IdentityRequestOptions = {}): Promise<TokenSummary[]> {
  return identityRequest<TokenSummary[]>('/api/v1/tokens', { method: 'GET' }, options)
}

export interface CreateTokenInput {
  name: string
  scope?: TokenScope
}

/** The raw secret is on **this** response only (`CreatedToken.token`) — never again, not even on a
 * subsequent {@link listTokens} read. The caller must show and let the user copy it now. */
export async function createToken(
  input: CreateTokenInput,
  options: IdentityRequestOptions = {},
): Promise<CreatedToken> {
  return identityRequest<CreatedToken>(
    '/api/v1/tokens',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    },
    options,
  )
}

export async function revokeToken(id: number, options: IdentityRequestOptions = {}): Promise<void> {
  await identityRequest<null>(`/api/v1/tokens/${id}`, { method: 'DELETE' }, options)
}
