// @vitest-environment jsdom
/**
 * `lib/attachments.ts`'s two calls — R14, KAN-1067/1068.
 *
 * `uploadAttachment` behaves like every other authenticated call in `notes.ts` (a credential is
 * required, a refusal is typed) except for its body, which is `FormData` rather than JSON —
 * asserted here the way `embeds.test.ts` asserts `fetchBoardEmbed`'s query shape.
 * `fetchAttachmentBlobUrl` behaves like `fetchBoardEmbed`: it never rejects, whatever went wrong,
 * because an attachment image is a decoration inside a note preview and not the note.
 *
 * `jsdom`, not the default `node` environment — `lib/auth.ts` reads `globalThis.sessionStorage`,
 * same reason `notes.test.ts`/`embeds.test.ts` opt in.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, NetworkError } from '../src/lib/api'
import * as auth from '../src/lib/auth'
import { fetchAttachmentBlobUrl, uploadAttachment } from '../src/lib/attachments'
import { FAKE_TOKEN } from './token'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

beforeEach(() => auth.setToken(FAKE_TOKEN))
afterEach(() => auth.clearToken())

describe('uploadAttachment', () => {
  it('sends the file as multipart form data, never as JSON', async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse(
        { id: 1, content_type: 'image/png', size_bytes: 3, created_at: 'x', markdown: 'x' },
        201,
      ),
    ) as unknown as typeof fetch

    const file = new File(['abc'], 'photo.png', { type: 'image/png' })
    await uploadAttachment('NOTE-1', file, { fetchImpl })

    const [, init] = vi.mocked(fetchImpl).mock.calls[0] as [string, RequestInit]
    expect(init.body).toBeInstanceOf(FormData)
    expect((init.body as FormData).get('file')).toBe(file)
    // No `Content-Type` set by hand — the browser derives `multipart/form-data; boundary=...` from
    // the `FormData` body, and setting it here would drop that boundary.
    const headers = init.headers as Record<string, string>
    expect(headers['Content-Type']).toBeUndefined()
  })

  it('sends the bearer as an Authorization header, never in the URL', async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse(
        { id: 1, content_type: 'image/png', size_bytes: 3, created_at: 'x', markdown: 'x' },
        201,
      ),
    ) as unknown as typeof fetch

    await uploadAttachment('NOTE-1', new File(['x'], 'f.png'), { fetchImpl })

    const [url, init] = vi.mocked(fetchImpl).mock.calls[0] as [string, RequestInit]
    expect(url).not.toContain(FAKE_TOKEN)
    expect((init.headers as Record<string, string>).Authorization).toBe(`Bearer ${FAKE_TOKEN}`)
  })

  it('percent-encodes the note ref as one path segment', async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse(
        { id: 1, content_type: 'image/png', size_bytes: 3, created_at: 'x', markdown: 'x' },
        201,
      ),
    ) as unknown as typeof fetch

    await uploadAttachment('weird/ref', new File(['x'], 'f.png'), { fetchImpl })

    const [url] = vi.mocked(fetchImpl).mock.calls[0] as [string]
    expect(url).toBe('/api/v1/notes/weird%2Fref/attachments')
  })

  it('returns the created AttachmentRead on a 201', async () => {
    const body = {
      id: 42,
      content_type: 'image/png',
      size_bytes: 3,
      created_at: '2026-09-01T00:00:00Z',
      markdown: '![f.png](/api/v1/notes/NOTE-1/attachments/42)',
    }
    const fetchImpl = vi.fn(async () => jsonResponse(body, 201)) as unknown as typeof fetch

    const result = await uploadAttachment('NOTE-1', new File(['x'], 'f.png'), { fetchImpl })

    expect(result).toEqual(body)
  })

  it('throws an ApiError carrying the code and message on a refusal', async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse({ error: { code: 'attachment_too_large', message: 'too big' } }, 413),
    ) as unknown as typeof fetch

    await expect(uploadAttachment('NOTE-1', new File(['x'], 'f.png'), { fetchImpl })).rejects.toMatchObject(
      { status: 413, code: 'attachment_too_large', message: 'too big' },
    )
  })

  it('throws a NetworkError on a transport failure', async () => {
    const fetchImpl = vi.fn(async () => {
      throw new TypeError('network down')
    }) as unknown as typeof fetch

    await expect(
      uploadAttachment('NOTE-1', new File(['x'], 'f.png'), { fetchImpl }),
    ).rejects.toBeInstanceOf(NetworkError)
  })

  it('throws before any request when there is no credential in the tab', async () => {
    auth.clearToken()
    const fetchImpl = vi.fn() as unknown as typeof fetch

    await expect(
      uploadAttachment('NOTE-1', new File(['x'], 'f.png'), { fetchImpl }),
    ).rejects.toMatchObject({ status: 401, code: 'no_credential' })
    expect(fetchImpl).not.toHaveBeenCalled()
  })

  it('throws ApiError for an unparsable non-JSON refusal rather than crashing', async () => {
    const fetchImpl = vi.fn(
      async () => new Response('<html>not json</html>', { status: 502 }),
    ) as unknown as typeof fetch

    await expect(
      uploadAttachment('NOTE-1', new File(['x'], 'f.png'), { fetchImpl }),
    ).rejects.toBeInstanceOf(ApiError)
  })
})

describe('fetchAttachmentBlobUrl: never rejects, whatever went wrong', () => {
  it('returns a blob: URL on a 200', async () => {
    const fetchImpl = vi.fn(
      async () => new Response(new Blob(['bytes']), { status: 200 }),
    ) as unknown as typeof fetch

    const url = await fetchAttachmentBlobUrl('NOTE-1', 42, { fetchImpl })

    expect(url).toMatch(/^blob:/)
  })

  it('sends the bearer as a header and encodes the ref as one path segment', async () => {
    const fetchImpl = vi.fn(
      async () => new Response(new Blob(['bytes']), { status: 200 }),
    ) as unknown as typeof fetch

    await fetchAttachmentBlobUrl('weird/ref', 7, { fetchImpl })

    const [url, init] = vi.mocked(fetchImpl).mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/v1/notes/weird%2Fref/attachments/7')
    expect((init.headers as Record<string, string>).Authorization).toBe(`Bearer ${FAKE_TOKEN}`)
  })

  it.each([401, 403, 404, 500, 503])('returns null rather than throwing on a %i', async (status) => {
    const fetchImpl = vi.fn(
      async () => new Response('{}', { status }),
    ) as unknown as typeof fetch

    await expect(fetchAttachmentBlobUrl('NOTE-1', 1, { fetchImpl })).resolves.toBeNull()
  })

  it('returns null rather than throwing on a transport failure', async () => {
    const fetchImpl = vi.fn(async () => {
      throw new TypeError('network down')
    }) as unknown as typeof fetch

    await expect(fetchAttachmentBlobUrl('NOTE-1', 1, { fetchImpl })).resolves.toBeNull()
  })

  it('returns null when there is no credential in the tab at all', async () => {
    auth.clearToken()
    const fetchImpl = vi.fn() as unknown as typeof fetch

    await expect(fetchAttachmentBlobUrl('NOTE-1', 1, { fetchImpl })).resolves.toBeNull()
    expect(fetchImpl).not.toHaveBeenCalled()
  })
})
