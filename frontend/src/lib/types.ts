/**
 * The wire shapes, mirroring `backend/app/api/schemas.py`.
 *
 * These are **complete records**, and that is deliberate rather than lazy. ADR 0004 §Decision:
 * "The API does not use `render` — it returns full records, because HTTP has content negotiation
 * and a browser client that wants everything." So the SPA is a sanctioned direct consumer of the
 * whole object; see `api.ts`'s header for what that does and does not license.
 *
 * Timestamps arrive as ISO 8601 strings with an offset and stay strings all the way through. ADR
 * 0009's precondition is exact to the microsecond, and `new Date(s).toISOString()` rounds to
 * milliseconds — a token parsed and re-emitted here would refuse every correct write. `kaya-client`
 * calls this "an opaque string" and forwards it untouched; so do we.
 */

/** One note. Every identifier in here is one the backend's ref resolver accepts back verbatim. */
export interface Note {
  ref: string
  id: number
  title: string
  body: string
  /** Mutable metadata, not identity (ADR 0008). Legitimately `''` — two seeded notes have one. */
  path: string
  created_at: string
  /** ADR 0009's concurrency token. Opaque: never parsed, never reformatted. */
  updated_at: string
}

/** `GET /api/v1/notes`. A named envelope so `summary` and `next_cursor` can be added later. */
export interface NoteList {
  notes: Note[]
}

/** `POST /api/v1/notes`. `body` and `path` default to `''` server-side. */
export interface NoteCreate {
  title: string
  body?: string
  path?: string
}

/**
 * `PATCH /api/v1/notes/{ref}`. Every field optional; **omitted means unchanged**.
 *
 * `?` rather than `| null` on purpose: the backend refuses a literal `null` with a `422`, because
 * the way a client produces one is a template that always emits the key with the value missing.
 * "Clear this field" is spelled `''`.
 */
export interface NoteUpdate {
  title?: string
  body?: string
  path?: string
  /** The `updated_at` you read, echoed back verbatim. Omitting it is a plain overwrite. */
  if_updated_at?: string
}

/**
 * `{"error": {"code", "message", …}}` — flat, all-strings for the two named keys, and identical for
 * every failure including Starlette's own 404/405 and body validation.
 *
 * The extras are `unknown` because the vocabulary grows without this file's knowledge: a `422`
 * carries `field`, a bad identifier carries `ref`, and ADR 0009's `409` carries two whole notes.
 */
export interface ApiErrorBody {
  error: {
    code: string
    message: string
    [extra: string]: unknown
  }
}

export function isApiErrorBody(value: unknown): value is ApiErrorBody {
  if (typeof value !== 'object' || value === null || !('error' in value)) {
    return false
  }
  const error = (value as { error: unknown }).error
  return (
    typeof error === 'object' &&
    error !== null &&
    typeof (error as { code?: unknown }).code === 'string' &&
    typeof (error as { message?: unknown }).message === 'string'
  )
}
