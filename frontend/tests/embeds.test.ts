// @vitest-environment jsdom
/**
 * `lib/embeds.ts`'s one call. What is worth asserting here, beyond the query it builds: the
 * "never reject" contract — every other fetch in `notes.ts` lets a failure propagate, and this one
 * is deliberately the opposite (see `fetchBoardEmbed`'s own docstring).
 *
 * `jsdom`, not the default `node` environment, because `lib/auth.ts` reads `globalThis.sessionStorage`
 * — same reason `notes.test.ts` opts in.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as auth from '../src/lib/auth'
import { fetchBoardEmbed } from '../src/lib/embeds'
import { FAKE_TOKEN } from './token'

function recorder(body: unknown, status = 200) {
  return vi.fn(async () => {
    return new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })
  }) as unknown as typeof fetch
}

beforeEach(() => auth.setToken(FAKE_TOKEN))
afterEach(() => auth.clearToken())

describe('the request it builds', () => {
  it('sends board and column, in that order, for a column query', async () => {
    const fetchImpl = recorder({ unavailable: false, cards: [] })
    await fetchBoardEmbed({ board: 18, column: 'todo', fetchImpl })

    const [url] = vi.mocked(fetchImpl).mock.calls[0] as [string]
    expect(url).toBe('/api/v1/embeds/board?board=18&column=todo')
  })

  it('sends board and view, in that order, for a view query', async () => {
    const fetchImpl = recorder({ unavailable: false, cards: [] })
    await fetchBoardEmbed({ board: 18, view: 3, fetchImpl })

    const [url] = vi.mocked(fetchImpl).mock.calls[0] as [string]
    expect(url).toBe('/api/v1/embeds/board?board=18&view=3')
  })

  it('percent-encodes a column name with special characters', async () => {
    const fetchImpl = recorder({ unavailable: false, cards: [] })
    await fetchBoardEmbed({ board: 18, column: 'in progress', fetchImpl })

    const [url] = vi.mocked(fetchImpl).mock.calls[0] as [string]
    expect(url).toBe('/api/v1/embeds/board?board=18&column=in+progress')
  })
})

describe('the response', () => {
  it('returns the body verbatim on a 200', async () => {
    const fetchImpl = recorder({
      unavailable: false,
      cards: [{ ref: 'KAN-1', title: 'x', column: 'todo' }],
    })
    const result = await fetchBoardEmbed({ board: 18, column: 'todo', fetchImpl })

    expect(result).toEqual({ unavailable: false, cards: [{ ref: 'KAN-1', title: 'x', column: 'todo' }] })
  })

  it('returns an unavailable body as-is — no special-casing needed by the caller', async () => {
    const fetchImpl = recorder({ unavailable: true, cards: [] })
    const result = await fetchBoardEmbed({ board: 18, column: 'todo', fetchImpl })

    expect(result).toEqual({ unavailable: true, cards: [] })
  })
})

describe('never rejects, whatever went wrong', () => {
  it('returns null rather than throwing on a transport failure', async () => {
    const fetchImpl = vi.fn(async () => {
      throw new TypeError('network down')
    }) as unknown as typeof fetch

    await expect(fetchBoardEmbed({ board: 18, column: 'todo', fetchImpl })).resolves.toBeNull()
  })

  it.each([401, 403, 404, 422, 500, 503])(
    'returns null rather than throwing on a %i from the API',
    async (status) => {
      const fetchImpl = recorder({ error: { code: 'whatever', message: 'nope' } }, status)
      await expect(fetchBoardEmbed({ board: 18, column: 'todo', fetchImpl })).resolves.toBeNull()
    },
  )

  it('returns null rather than throwing when the body kaya cannot parse comes back', async () => {
    const fetchImpl = vi.fn(async () => new Response('not json', { status: 200 })) as unknown as typeof fetch

    // A 200 with an unparsable body still round-trips through `apiRequest` as `null`, which this
    // function then hands straight back — not a crash, and indistinguishable from "pandan is down"
    // from `PreviewPane.svelte`'s side, which is exactly the point (Q26, ADR 0003).
    await expect(fetchBoardEmbed({ board: 18, column: 'todo', fetchImpl })).resolves.toBeNull()
  })

  it('returns null when there is no credential in the tab at all', async () => {
    // No `fetchImpl` call happens here — `apiRequest` throws `MissingCredential` before ever
    // reaching `fetch` — so there is nothing to inject; the assertion is just that this doesn't
    // reject either.
    auth.clearToken()
    await expect(fetchBoardEmbed({ board: 18, column: 'todo' })).resolves.toBeNull()
  })
})
