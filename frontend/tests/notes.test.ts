// @vitest-environment jsdom
/**
 * The five note calls. What is worth asserting here is the ref encoding and the fact that `move`
 * is sugar — both are places where a plausible "improvement" breaks a documented contract.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as auth from '../src/lib/auth'
import {
  deleteNote,
  listBacklinks,
  listNotes,
  moveNote,
  notePath,
  updateNote,
} from '../src/lib/notes'
import { FAKE_TOKEN } from './token'

function recorder(body: unknown, status = 200) {
  return vi.fn(async () => {
    if (status === 204) {
      return new Response(null, { status })
    }
    return new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })
  }) as unknown as typeof fetch
}

beforeEach(() => auth.setToken(FAKE_TOKEN))
afterEach(() => auth.clearToken())

describe('notePath', () => {
  it('makes the ref exactly one path segment', () => {
    expect(notePath('NOTE-12')).toBe('notes/NOTE-12')
    // A `/` inside a bad ref must become %2F and address a 404, not silently become another route.
    expect(notePath('a/b')).toBe('notes/a%2Fb')
    // `#NOTE-12` is a documented `400` (ADR 0008), and it only gets there if the `#` survives —
    // unencoded it becomes a fragment the request never carries.
    expect(notePath('#NOTE-12')).toBe('notes/%23NOTE-12')
  })
})

describe('listNotes', () => {
  it('unwraps the named envelope', async () => {
    const fetchImpl = recorder({ notes: [{ ref: 'NOTE-1' }, { ref: 'NOTE-2' }] })
    await expect(listNotes({ fetchImpl })).resolves.toHaveLength(2)
  })

  it('adds no query parameter when q is omitted (KAN-559)', async () => {
    const fetchImpl = recorder({ notes: [] })
    await listNotes({ fetchImpl })

    const [url] = vi.mocked(fetchImpl).mock.calls[0] as [string]
    expect(url).toBe('/api/v1/notes')
  })

  it('forwards q as a query parameter, percent-encoded', async () => {
    const fetchImpl = recorder({ notes: [] })
    await listNotes({ q: 'reading list', fetchImpl })

    const [url] = vi.mocked(fetchImpl).mock.calls[0] as [string]
    expect(url).toBe('/api/v1/notes?q=reading%20list')
  })

  it('forwards a blank q rather than omitting it — the backend decides what that means', async () => {
    // A search box that has been cleared must send no `q` at all; a `q` that is present but blank
    // is a different request and this module has no opinion about which one the caller meant.
    const fetchImpl = recorder({ notes: [] })
    await listNotes({ q: '', fetchImpl })

    const [url] = vi.mocked(fetchImpl).mock.calls[0] as [string]
    expect(url).toBe('/api/v1/notes?q=')
  })
})

describe('moveNote', () => {
  it('puts identical bytes on the wire as an updateNote of path alone', async () => {
    // ADR 0008: moving a note *is* a `PATCH` to `path`. `kaya-client` pins the same equivalence
    // (`kaya-client/tests/test_writes.py`), and the reason both do is to stop the next person
    // "backing it properly" with a `POST /notes/{ref}/move`.
    const viaMove = recorder({ ref: 'NOTE-1' })
    await moveNote('NOTE-1', 'a/b.md', { fetchImpl: viaMove })

    const viaUpdate = recorder({ ref: 'NOTE-1' })
    await updateNote('NOTE-1', { path: 'a/b.md' }, { fetchImpl: viaUpdate })

    expect(vi.mocked(viaMove).mock.calls[0]).toEqual(vi.mocked(viaUpdate).mock.calls[0])
  })

  it('carries no precondition, because ADR 0009 guards only writes touching body', async () => {
    const fetchImpl = recorder({ ref: 'NOTE-1' })
    await moveNote('NOTE-1', 'a/b.md', { fetchImpl })

    const [, init] = vi.mocked(fetchImpl).mock.calls[0] as [string, RequestInit]
    expect(JSON.parse(init.body as string)).toEqual({ path: 'a/b.md' })
  })
})

describe('updateNote', () => {
  it('forwards if_updated_at as an opaque string, byte for byte', async () => {
    // Exact to the microsecond. `new Date(s).toISOString()` rounds to milliseconds, and a token
    // that loses precision refuses *every* correct write with a permanent 409.
    const stamp = '2026-08-11T04:05:06.123456+00:00'
    const fetchImpl = recorder({ ref: 'NOTE-1' })
    await updateNote('NOTE-1', { body: 'new', if_updated_at: stamp }, { fetchImpl })

    const [, init] = vi.mocked(fetchImpl).mock.calls[0] as [string, RequestInit]
    expect(init.method).toBe('PATCH')
    expect(JSON.parse(init.body as string).if_updated_at).toBe(stamp)
  })

  it('sends only the fields it was given, because omitted means unchanged', async () => {
    const fetchImpl = recorder({ ref: 'NOTE-1' })
    await updateNote('NOTE-1', { title: 'renamed' }, { fetchImpl })

    const [, init] = vi.mocked(fetchImpl).mock.calls[0] as [string, RequestInit]
    // A PUT-shaped write that always sent `body` would silently blank 3,000 words.
    expect(JSON.parse(init.body as string)).toEqual({ title: 'renamed' })
  })
})

describe('deleteNote', () => {
  it('resolves on the 204 and asks for nothing back', async () => {
    const fetchImpl = recorder(null, 204)
    await expect(deleteNote('NOTE-1', { fetchImpl })).resolves.toBeUndefined()

    const [url, init] = vi.mocked(fetchImpl).mock.calls[0] as [string, RequestInit]
    expect(init.method).toBe('DELETE')
    expect(url).toBe('/api/v1/notes/NOTE-1')
  })
})

describe('listBacklinks (KAN-568)', () => {
  it('reads the same envelope a plain list does, from the /backlinks suffix', async () => {
    // The whole reason there is no `Backlink` type anywhere in `frontend/`: the API answers this
    // route with the very same `NoteList` (`backend/app/api/links.py`), so this is `listNotes` at a
    // different URL and the rows are notes.
    const fetchImpl = recorder({ notes: [{ ref: 'NOTE-2' }, { ref: 'NOTE-5' }] })

    await expect(listBacklinks('NOTE-1', { fetchImpl })).resolves.toHaveLength(2)

    const [url] = vi.mocked(fetchImpl).mock.calls[0] as [string]
    expect(url).toBe('/api/v1/notes/NOTE-1/backlinks')
  })

  it('encodes the ref as one segment and appends the suffix outside the encoding', async () => {
    // Both halves matter. `notePath` percent-encodes so a `#` reaches ADR 0008's documented `400`
    // rather than becoming a fragment; the suffix must stay a real path segment, because a
    // `%2Fbacklinks` would address a note whose ref ends in "/backlinks" and get a `404`.
    const fetchImpl = recorder({ notes: [] })
    await listBacklinks('#NOTE-1', { fetchImpl })

    const [url] = vi.mocked(fetchImpl).mock.calls[0] as [string]
    expect(url).toBe('/api/v1/notes/%23NOTE-1/backlinks')
  })

  it('is a GET and sends no body', async () => {
    const fetchImpl = recorder({ notes: [] })
    await listBacklinks('NOTE-1', { fetchImpl })

    const [, init] = vi.mocked(fetchImpl).mock.calls[0] as [string, RequestInit]
    expect(init.method).toBe('GET')
    expect(init.body).toBeUndefined()
  })
})
