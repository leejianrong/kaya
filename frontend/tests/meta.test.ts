// @vitest-environment jsdom
/**
 * `GET /api/v1/meta`, and the one property that makes it a *public* read rather than an
 * authenticated one that happens to work: it sends no credential (KAN-555).
 *
 * The interesting assertion is again the negative one. A `publicRequest` that helpfully attached the
 * bearer would pass every test about the origin it returns — while sending a live pandan PAT on a
 * request the caller did not authorise, including on the `401` recovery path where the token in the
 * tab is precisely the one the API has just refused.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { publicRequest } from '../src/lib/api'
import * as auth from '../src/lib/auth'
import { fetchMeta, pandanHref } from '../src/lib/meta'
import { FAKE_TOKEN, fragments } from './token'

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function fakeFetch(response: Response) {
  return vi.fn(async (...args: Parameters<typeof fetch>) => {
    void args
    return response
  }) as unknown as typeof fetch
}

beforeEach(() => {
  // A credential *is* present throughout, because "there was nothing to leak" is not the property
  // under test.
  auth.setToken(FAKE_TOKEN)
})

afterEach(() => {
  auth.clearToken()
})

describe('fetchMeta', () => {
  it('reads /api/v1/meta and returns the origin the backend is configured with', async () => {
    const fetchImpl = fakeFetch(jsonResponse(200, { pandan_url: 'https://pandan.example.test' }))

    const meta = await fetchMeta({ fetchImpl })

    expect(meta.pandan_url).toBe('https://pandan.example.test')
    const [url] = vi.mocked(fetchImpl).mock.calls[0] as [string]
    expect(url).toBe('/api/v1/meta')
  })

  it('sends no Authorization header, and no fragment of the token anywhere in the request', async () => {
    const fetchImpl = fakeFetch(jsonResponse(200, { pandan_url: 'https://pandan.example.test' }))
    await fetchMeta({ fetchImpl })

    const [url, init] = vi.mocked(fetchImpl).mock.calls[0] as [string, RequestInit]
    const headers = init.headers as Record<string, string>
    expect(Object.keys(headers)).toEqual(['Accept'])
    expect('Authorization' in headers).toBe(false)

    const whole = `${url}|${JSON.stringify(init)}`
    for (const fragment of fragments(FAKE_TOKEN)) {
      expect(whole).not.toContain(fragment)
    }
  })

  it('stays relative, so the dev proxy and the single-origin deploy both reach it', async () => {
    const fetchImpl = fakeFetch(jsonResponse(200, { pandan_url: 'https://pandan.example.test' }))
    await publicRequest('meta', { fetchImpl })

    const [url] = vi.mocked(fetchImpl).mock.calls[0] as [string]
    expect(url.startsWith('/api/v1/')).toBe(true)
  })
})

describe('pandanHref', () => {
  it('passes an http or https origin through', () => {
    expect(pandanHref('https://simple-kanban-jian.fly.dev')).toBe(
      'https://simple-kanban-jian.fly.dev/',
    )
    expect(pandanHref('  http://localhost:8000  ')).toBe('http://localhost:8000/')
  })

  it('refuses anything that is not http(s), so a misconfigured origin cannot become script', () => {
    // Not a defence against an attacker — the value is the operator's own env var — but an `href`
    // is one of the few places a Svelte template *interprets* a string instead of escaping it, and
    // this origin holds the credential in `sessionStorage`. A missing link beats a live one.
    expect(pandanHref('javascript:alert(1)')).toBeNull()
    expect(pandanHref('data:text/html,<script>1</script>')).toBeNull()
    expect(pandanHref('file:///etc/passwd')).toBeNull()
  })

  it('refuses an empty or unparseable value rather than rendering a dead link', () => {
    expect(pandanHref('')).toBeNull()
    expect(pandanHref('   ')).toBeNull()
    expect(pandanHref('not a url')).toBeNull()
    expect(pandanHref(null)).toBeNull()
    expect(pandanHref(undefined)).toBeNull()
  })
})
