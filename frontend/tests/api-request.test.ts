// @vitest-environment jsdom
/**
 * The fetch layer: where the bearer goes, where it must never go, and what a refusal becomes.
 *
 * `fetch` is faked throughout — a test that reached a network would be a test that passes on a
 * machine with `make up` running and fails everywhere else.
 *
 * The interesting assertion is the negative one. A credential in a query parameter works perfectly,
 * so nothing fails when somebody adds one: it reaches the browser history, the referrer, a proxy
 * access log and the backend's own request line, and kaya's observability rules (Q41/Q42) exist
 * because a log line is the cheapest way to give a credential away.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, apiRequest, MissingCredential, NetworkError } from '../src/lib/api'
import * as auth from '../src/lib/auth'

const FAKE_TOKEN = 'kanban_pat_9QxZ4mR7vT2LbWc8NsHdKfJgYpAeUiOn3XzVrQtE5w'

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

/** A `fetch` that records its calls and answers with whatever it is given. */
function fakeFetch(response: Response | Error) {
  return vi.fn(async (...args: Parameters<typeof fetch>) => {
    void args
    if (response instanceof Error) {
      throw response
    }
    return response
  }) as unknown as typeof fetch
}

beforeEach(() => {
  auth.setToken(FAKE_TOKEN)
})

afterEach(() => {
  auth.clearToken()
})

describe('apiRequest', () => {
  it('sends the bearer from the credential seam', async () => {
    const fetchImpl = fakeFetch(jsonResponse(200, { notes: [] }))
    await apiRequest('notes', { fetchImpl })

    const [, init] = vi.mocked(fetchImpl).mock.calls[0] as [string, RequestInit]
    expect((init.headers as Record<string, string>).Authorization).toBe(`Bearer ${FAKE_TOKEN}`)
  })

  it('never puts the token in the URL', async () => {
    const fetchImpl = fakeFetch(jsonResponse(200, { notes: [] }))
    await apiRequest('notes', { fetchImpl })

    const [url] = vi.mocked(fetchImpl).mock.calls[0] as [string]
    expect(url).toBe('/api/v1/notes')
    for (let start = 0; start + 4 <= FAKE_TOKEN.length; start += 1) {
      expect(url).not.toContain(FAKE_TOKEN.slice(start, start + 4))
    }
  })

  it('stays same-origin and relative, so the dev proxy and the single-origin deploy both work', async () => {
    const fetchImpl = fakeFetch(jsonResponse(200, { notes: [] }))
    await apiRequest('notes', { fetchImpl })

    const [url, init] = vi.mocked(fetchImpl).mock.calls[0] as [string, RequestInit]
    expect(url.startsWith('/api/v1/')).toBe(true)
    expect(init.credentials).toBe('same-origin')
  })

  it('refuses before the request when there is no credential', async () => {
    auth.clearToken()
    const fetchImpl = fakeFetch(jsonResponse(200, {}))

    await expect(apiRequest('notes', { fetchImpl })).rejects.toBeInstanceOf(MissingCredential)
    // Not a 401 after a round trip: an unauthenticated app must not hammer the backend, and the
    // landing state (KAN-555) is reachable without one.
    expect(vi.mocked(fetchImpl)).not.toHaveBeenCalled()
  })

  it('sends a JSON body with a content type, and no body without one', async () => {
    const fetchImpl = fakeFetch(jsonResponse(201, { ref: 'NOTE-1' }))
    await apiRequest('notes', { method: 'POST', body: { title: 'x' }, fetchImpl })

    const [, init] = vi.mocked(fetchImpl).mock.calls[0] as [string, RequestInit]
    expect(init.body).toBe('{"title":"x"}')
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json')

    const bare = fakeFetch(jsonResponse(200, { notes: [] }))
    await apiRequest('notes', { fetchImpl: bare })
    const [, getInit] = vi.mocked(bare).mock.calls[0] as [string, RequestInit]
    expect(getInit.body).toBeUndefined()
    expect((getInit.headers as Record<string, string>)['Content-Type']).toBeUndefined()
  })

  it('returns the parsed body on success', async () => {
    const note = { ref: 'NOTE-3', id: 3, title: 'T', body: 'b', path: '' }
    const fetchImpl = fakeFetch(jsonResponse(200, note))
    await expect(apiRequest('notes/NOTE-3', { fetchImpl })).resolves.toEqual(note)
  })

  it('returns null for a 204, which is what DELETE answers', async () => {
    const fetchImpl = fakeFetch(new Response(null, { status: 204 }))
    await expect(apiRequest('notes/NOTE-3', { method: 'DELETE', fetchImpl })).resolves.toBeNull()
  })
})

describe('turning a refusal into a typed failure', () => {
  it("reads the API's flat {error: {code, message}} shape", async () => {
    const fetchImpl = fakeFetch(
      jsonResponse(404, { error: { code: 'not_found', message: 'No note NOTE-9999' } }),
    )

    const failure = await apiRequest('notes/NOTE-9999', { fetchImpl }).catch(
      (error: unknown) => error,
    )
    expect(failure).toBeInstanceOf(ApiError)
    expect(failure).toMatchObject({ status: 404, code: 'not_found', message: 'No note NOTE-9999' })
  })

  it('keeps the status and the code apart', async () => {
    // `kaya-cli` keys its exit table on the *status*, not the code string, because the backend's
    // code vocabulary grows without the client's knowledge. Same reasoning, same seam.
    const fetchImpl = fakeFetch(
      jsonResponse(401, { error: { code: 'invalid_credentials', message: 'nope' } }),
    )
    const failure = (await apiRequest('notes', { fetchImpl }).catch((e: unknown) => e)) as ApiError

    expect(failure.status).toBe(401)
    expect(failure.isUnauthenticated).toBe(true)
    expect(failure.isConflict).toBe(false)
  })

  it("carries ADR 0009's 409 extras through, both whole notes", async () => {
    const attempted = { ref: 'NOTE-3', body: 'mine' }
    const stored = { ref: 'NOTE-3', body: 'theirs' }
    const fetchImpl = fakeFetch(
      jsonResponse(409, {
        error: { code: 'stale_precondition', message: 'moved on', attempted, stored },
      }),
    )

    const failure = (await apiRequest('notes/NOTE-3', {
      method: 'PATCH',
      body: { body: 'mine', if_updated_at: 'x' },
      fetchImpl,
    }).catch((e: unknown) => e)) as ApiError

    expect(failure.isConflict).toBe(true)
    // KAN-556's banner needs both versions, and it gets them without this layer knowing what a
    // conflict looks like.
    expect(failure.details).toEqual({ attempted, stored })
  })

  it('names the likely cause when the answer is not kaya at all', async () => {
    // What a dev proxy that stopped forwarding actually produces: the SPA's own index.html with a
    // status on it. "Unexpected token < in JSON" is the debugging session this branch skips.
    const fetchImpl = fakeFetch(new Response('<!doctype html>', { status: 502 }))
    const failure = (await apiRequest('notes', { fetchImpl }).catch((e: unknown) => e)) as ApiError

    expect(failure.status).toBe(502)
    expect(failure.code).toBe('unexpected_response')
    expect(failure.message).toContain('/api/v1/notes')
  })

  it('reports a transport failure as its own type, with no cause chained on', async () => {
    const fetchImpl = fakeFetch(new TypeError('Failed to fetch'))
    const failure = (await apiRequest('notes', { fetchImpl }).catch(
      (e: unknown) => e,
    )) as NetworkError

    expect(failure).toBeInstanceOf(NetworkError)
    // The failing call had the header object as an argument, and a chained cause is what a console
    // logger prints in full.
    expect(failure.cause).toBeUndefined()
    for (let start = 0; start + 4 <= FAKE_TOKEN.length; start += 1) {
      expect(failure.message).not.toContain(FAKE_TOKEN.slice(start, start + 4))
    }
  })
})
