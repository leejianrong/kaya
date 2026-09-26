// @vitest-environment jsdom
/**
 * `lib/identity.ts`'s own seam: kaya's cookie-session identity, GitHub login, and PAT self-service
 * (ADR 0012, KAN-1739). Mirrors `tests/meta.test.ts`'s shape — an injected `fetchImpl`, no ambient
 * mocking — since this module offers exactly that seam, unlike `lib/api.ts`.
 */

import { describe, expect, it, vi } from 'vitest'

import {
  approveDeviceAuthorization,
  createToken,
  denyDeviceAuthorization,
  fetchCurrentUser,
  getDeviceAuthorization,
  githubLoginUrl,
  IdentityError,
  listTokens,
  logout,
  revokeToken,
} from '../src/lib/identity'

function jsonResponse(status: number, body: unknown): Response {
  return new Response(body === null ? null : JSON.stringify(body), {
    status,
    headers: body === null ? {} : { 'Content-Type': 'application/json' },
  })
}

function fakeFetch(response: Response) {
  return vi.fn(async () => response) as unknown as typeof fetch
}

describe('fetchCurrentUser', () => {
  it('returns the session when one exists', async () => {
    const fetchImpl = fakeFetch(jsonResponse(200, { id: 'abc-123', email: 'alice@example.com' }))

    const user = await fetchCurrentUser({ fetchImpl })

    expect(user).toEqual({ id: 'abc-123', email: 'alice@example.com' })
    const [url, init] = vi.mocked(fetchImpl).mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/users/me')
    expect(init.credentials).toBe('same-origin')
  })

  it('resolves null, not a rejection, when there is no session', async () => {
    const fetchImpl = fakeFetch(jsonResponse(401, { error: { code: 'unauthorized', message: 'no' } }))

    await expect(fetchCurrentUser({ fetchImpl })).resolves.toBeNull()
  })

  it('still rejects on a genuine failure other than 401', async () => {
    const fetchImpl = fakeFetch(jsonResponse(500, { error: { code: 'boom', message: 'kaboom' } }))

    await expect(fetchCurrentUser({ fetchImpl })).rejects.toBeInstanceOf(IdentityError)
  })
})

describe('githubLoginUrl', () => {
  it('returns the authorization_url rather than navigating itself', async () => {
    const fetchImpl = fakeFetch(
      jsonResponse(200, { authorization_url: 'https://github.com/login/oauth/authorize?x=1' }),
    )

    const url = await githubLoginUrl({ fetchImpl })

    expect(url).toBe('https://github.com/login/oauth/authorize?x=1')
    const [requested] = vi.mocked(fetchImpl).mock.calls[0] as [string]
    expect(requested).toBe('/auth/github/authorize')
  })
})

describe('logout', () => {
  it('posts to /auth/logout', async () => {
    const fetchImpl = fakeFetch(jsonResponse(204, null))

    await logout({ fetchImpl })

    const [url, init] = vi.mocked(fetchImpl).mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/auth/logout')
    expect(init.method).toBe('POST')
  })
})

describe('device-flow consent (ADR 0013, KAN-1743)', () => {
  it('getDeviceAuthorization reads /auth/device/{userCode}', async () => {
    const fetchImpl = fakeFetch(
      jsonResponse(200, {
        user_code: 'WDJB-MJHT',
        status: 'pending',
        requested_scope: 'write',
        expires_at: '2026-09-26T12:00:00Z',
      }),
    )

    const found = await getDeviceAuthorization('WDJB-MJHT', { fetchImpl })

    expect(found.status).toBe('pending')
    const [url, init] = vi.mocked(fetchImpl).mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/auth/device/WDJB-MJHT')
    expect(init.method).toBe('GET')
  })

  it('getDeviceAuthorization encodes the code as one path segment', async () => {
    const fetchImpl = fakeFetch(
      jsonResponse(200, {
        user_code: 'a/b',
        status: 'pending',
        requested_scope: 'write',
        expires_at: '2026-09-26T12:00:00Z',
      }),
    )

    await getDeviceAuthorization('a/b', { fetchImpl })

    const [url] = vi.mocked(fetchImpl).mock.calls[0] as [string]
    expect(url).toBe('/auth/device/a%2Fb')
  })

  it('a code the API does not recognise rejects with a 404 IdentityError, never null', async () => {
    const fetchImpl = fakeFetch(
      jsonResponse(404, { error: { code: 'device_code_not_found', message: 'code not found' } }),
    )

    await expect(getDeviceAuthorization('NOPE-CODE', { fetchImpl })).rejects.toMatchObject({
      status: 404,
    })
  })

  it('approveDeviceAuthorization posts to the approve sub-path', async () => {
    const fetchImpl = fakeFetch(
      jsonResponse(200, {
        user_code: 'WDJB-MJHT',
        status: 'approved',
        requested_scope: 'write',
        expires_at: '2026-09-26T12:00:00Z',
      }),
    )

    const approved = await approveDeviceAuthorization('WDJB-MJHT', { fetchImpl })

    expect(approved.status).toBe('approved')
    const [url, init] = vi.mocked(fetchImpl).mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/auth/device/WDJB-MJHT/approve')
    expect(init.method).toBe('POST')
  })

  it('denyDeviceAuthorization posts to the deny sub-path', async () => {
    const fetchImpl = fakeFetch(
      jsonResponse(200, {
        user_code: 'WDJB-MJHT',
        status: 'denied',
        requested_scope: 'write',
        expires_at: '2026-09-26T12:00:00Z',
      }),
    )

    const denied = await denyDeviceAuthorization('WDJB-MJHT', { fetchImpl })

    expect(denied.status).toBe('denied')
    const [url, init] = vi.mocked(fetchImpl).mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/auth/device/WDJB-MJHT/deny')
    expect(init.method).toBe('POST')
  })
})

describe('tokens CRUD', () => {
  it('lists tokens with no secret field anywhere in the payload', async () => {
    const fetchImpl = fakeFetch(
      jsonResponse(200, [
        {
          id: 1,
          name: 'laptop',
          token_prefix: 'kaya_pat_ab12',
          scope: 'write',
          created_at: '2026-09-25T00:00:00Z',
          last_used_at: null,
          expires_at: null,
        },
      ]),
    )

    const tokens = await listTokens({ fetchImpl })

    expect(tokens).toHaveLength(1)
    expect(tokens[0]?.name).toBe('laptop')
    expect('token' in (tokens[0] as object)).toBe(false)
  })

  it('creates a token and returns the one-time secret', async () => {
    const fetchImpl = fakeFetch(
      jsonResponse(201, {
        id: 2,
        name: 'ci-bot',
        token_prefix: 'kaya_pat_cd34',
        scope: 'read',
        created_at: '2026-09-25T00:00:00Z',
        last_used_at: null,
        expires_at: null,
        token: 'kaya_pat_cd34fake-secret',
      }),
    )

    const created = await createToken({ name: 'ci-bot', scope: 'read' }, { fetchImpl })

    expect(created.token).toBe('kaya_pat_cd34fake-secret')
    const [url, init] = vi.mocked(fetchImpl).mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/v1/tokens')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toEqual({ name: 'ci-bot', scope: 'read' })
  })

  it('revokes a token by id', async () => {
    const fetchImpl = fakeFetch(jsonResponse(204, null))

    await revokeToken(7, { fetchImpl })

    const [url, init] = vi.mocked(fetchImpl).mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/v1/tokens/7')
    expect(init.method).toBe('DELETE')
  })

  it('surfaces the API error message on a refusal', async () => {
    const fetchImpl = fakeFetch(jsonResponse(404, { error: { code: 'not_found', message: 'token not found' } }))

    await expect(revokeToken(999, { fetchImpl })).rejects.toThrow('token not found')
  })
})
