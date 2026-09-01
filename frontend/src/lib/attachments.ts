/**
 * `POST`/`GET /api/v1/notes/{ref}/attachments` — R14, KAN-1067/1068.
 *
 * A module of its own rather than two more functions in `notes.ts`, for the reason `lib/embeds.ts`
 * gives for its one function: neither call fits `api.ts`'s `apiRequest`, which always sends and
 * receives JSON. An upload is a `multipart/form-data` body (`FormData`, never JSON-stringified —
 * `Content-Type` with its boundary is the browser's to set, so it must never be set by hand
 * alongside a `FormData` body); a fetch is a binary response, read as a `Blob` rather than parsed
 * as JSON. So both go through their own `fetch` here, reusing `auth.ts`'s `authorization()` for
 * the bearer and `api.ts`'s `apiPath`/error types for everything else, rather than forcing either
 * shape through `send()`.
 *
 * **Never a direct R2 URL.** `fetchAttachmentBlobUrl` is the one function in this SPA that turns a
 * kaya attachment route into something an `<img>` can show, and it does that by fetching the bytes
 * *with the caller's own bearer* and handing back a `blob:` URL — same reasoning as `auth.ts`'s
 * `sessionStorage`-only bearer: nothing that identifies a private resource sits in a URL bar, a
 * cached HTML response, or a `<img src>` a browser could request without a credential attached.
 */

import { ApiError, apiPath, MissingCredential, NetworkError } from './api'
import { authorization } from './auth'
import { isApiErrorBody } from './types'

/** `POST /api/v1/notes/{ref}/attachments`'s body, mirroring `backend/app/api/schemas.py`'s
 *  `AttachmentRead` field for field. */
export interface AttachmentRead {
  id: number
  content_type: string
  size_bytes: number
  created_at: string
  /** `![<filename>](/api/v1/notes/{ref}/attachments/{id})` — insert this verbatim at the cursor.
   *  A relative, same-origin path, never a direct R2 URL (see the module header). */
  markdown: string
}

export interface UploadAttachmentOptions {
  signal?: AbortSignal
  /** Injectable for tests, same convention as every call in `notes.ts`/`api.ts`. Defaults to the
   *  ambient `fetch`. */
  fetchImpl?: typeof fetch
}

/**
 * Upload `file`, attached to the note addressed by `noteRef`, and return the markdown reference to
 * insert into the note body.
 *
 * Throws `MissingCredential` (no bearer in the seam — the same refusal `apiRequest` gives, before
 * any request is made) or `ApiError`/`NetworkError` for a refused or unreachable request, so a
 * caller's `.catch()` handles every failure the same way it already does for `notes.ts`'s calls.
 * `lib/codemirror.ts`'s drop/paste handler is the one caller today.
 */
export async function uploadAttachment(
  noteRef: string,
  file: File,
  options: UploadAttachmentOptions = {},
): Promise<AttachmentRead> {
  const bearer = authorization()
  if (bearer === null) {
    throw new MissingCredential()
  }

  const body = new FormData()
  body.append('file', file)

  const doFetch = options.fetchImpl ?? globalThis.fetch
  const path = `notes/${encodeURIComponent(noteRef)}/attachments`
  let response: Response
  try {
    response = await doFetch(apiPath(path), {
      method: 'POST',
      // No `Content-Type` here — the browser sets `multipart/form-data; boundary=...` for a
      // `FormData` body, and overriding it drops the boundary the server needs to parse the part.
      headers: { Authorization: bearer, Accept: 'application/json' },
      body,
      signal: options.signal,
      credentials: 'same-origin',
    })
  } catch {
    throw new NetworkError(`Could not reach the kaya API to upload the attachment`)
  }

  const payload = await readJson(response)
  if (!response.ok) {
    if (isApiErrorBody(payload)) {
      const { code, message, ...details } = payload.error
      throw new ApiError(response.status, code, message, details)
    }
    throw new ApiError(
      response.status,
      'unexpected_response',
      `The API answered ${response.status} without kaya's error shape while uploading an attachment.`,
    )
  }
  return payload as AttachmentRead
}

export interface FetchAttachmentOptions {
  signal?: AbortSignal
  fetchImpl?: typeof fetch
}

/**
 * The bytes at `GET /api/v1/notes/{noteRef}/attachments/{attachmentId}`, as a `blob:` URL — or
 * `null` for any failure at all (no credential, the note or attachment refused, a transport
 * failure, an abort).
 *
 * **Never throws**, the same contract `lib/embeds.ts`'s `fetchBoardEmbed` keeps and for the
 * identical reason stated there: an attachment image is a decoration inside a note preview, not
 * the note, and a reader cannot act differently on "unauthorized", "gone" or "the network dropped"
 * — `PreviewPane.svelte` renders all four the same way a board embed's `unavailable` already is.
 *
 * The caller owns the returned URL's lifetime: `URL.revokeObjectURL` it once the `<img>` that used
 * it is gone, the same discipline any other `createObjectURL` caller in a long-lived page needs.
 */
export async function fetchAttachmentBlobUrl(
  noteRef: string,
  attachmentId: number,
  options: FetchAttachmentOptions = {},
): Promise<string | null> {
  const bearer = authorization()
  if (bearer === null) {
    return null
  }

  const doFetch = options.fetchImpl ?? globalThis.fetch
  const path = `notes/${encodeURIComponent(noteRef)}/attachments/${attachmentId}`
  try {
    const response = await doFetch(apiPath(path), {
      headers: { Authorization: bearer },
      signal: options.signal,
      credentials: 'same-origin',
    })
    if (!response.ok) {
      return null
    }
    const blob = await response.blob()
    return URL.createObjectURL(blob)
  } catch {
    return null
  }
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
