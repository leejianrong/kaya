/**
 * The five note calls, one function each, and nothing else.
 *
 * This module holds no state and makes no decisions about what a caller sees — it is the typed
 * surface of `/api/v1/notes` and the place a component looks instead of assembling a path. Every
 * function returns a **complete record** (see `api.ts` on ADR 0004); none of them filters fields,
 * cuts prose or counts anything.
 */

import { apiRequest, type RequestOptions } from './api'
import type { Note, NoteCreate, NoteList, NoteUpdate } from './types'

type Options = Pick<RequestOptions, 'signal' | 'fetchImpl'>

/**
 * The path for one note, with the ref as a **single** percent-encoded segment.
 *
 * `encodeURIComponent` rather than `encodeURI`, and shared by every ref-taking call for the same
 * reason `kaya-client` shares `_note_path`: a ref is one segment, so a `/` inside a bad ref must
 * become `%2F` and address a 404 rather than silently becoming a different route. `#NOTE-12` is a
 * documented `400` from the backend (ADR 0008), and it only gets there if the `#` survives the trip
 * — unencoded it would be a fragment the request never carries.
 */
export function notePath(ref: string): string {
  return `notes/${encodeURIComponent(ref)}`
}

/** Every note the caller owns, newest first. */
export async function listNotes(options: Options = {}): Promise<Note[]> {
  const payload = await apiRequest<NoteList>('notes', options)
  return payload.notes
}

/** One note, addressed as `NOTE-12`, `note-12` or `12` — all three resolve identically. */
export function getNote(ref: string, options: Options = {}): Promise<Note> {
  return apiRequest<Note>(notePath(ref), options)
}

export function createNote(input: NoteCreate, options: Options = {}): Promise<Note> {
  return apiRequest<Note>('notes', { ...options, method: 'POST', body: input })
}

/**
 * Change `title`, `body` and/or `path`. Omitted fields are left alone.
 *
 * Pass `if_updated_at` and the write is guarded: a stale value is a `409` carrying both versions
 * (`ApiError.details`), and nothing is written. Omit it and the write is a plain overwrite, **by
 * specification** — so there is no `force` parameter here, exactly as `kaya note edit` has no
 * `--force`. The unguarded write is spelled by not passing something.
 */
export function updateNote(ref: string, patch: NoteUpdate, options: Options = {}): Promise<Note> {
  return apiRequest<Note>(notePath(ref), { ...options, method: 'PATCH', body: patch })
}

/**
 * Move a note between folders. Sugar over {@link updateNote}, and it must stay sugar.
 *
 * ADR 0008: moving a note *is* a `PATCH` to `path`, with no link rewriting and no move endpoint.
 * It takes no precondition because ADR 0009 guards only writes touching `body`, so one here would
 * be accepted and ignored — a parameter that silently does nothing is worse than one that does not
 * exist.
 */
export function moveNote(ref: string, path: string, options: Options = {}): Promise<Note> {
  return updateNote(ref, { path }, options)
}

/** Delete the note. `204`, no body. The ref is never reused (ADR 0008). */
export async function deleteNote(ref: string, options: Options = {}): Promise<void> {
  await apiRequest<null>(notePath(ref), { ...options, method: 'DELETE' })
}
