/**
 * The five note calls, one function each, and nothing else.
 *
 * This module holds no state and makes no decisions about what a caller sees — it is the typed
 * surface of `/api/v1/notes` and the place a component looks instead of assembling a path. Every
 * function returns a **complete record** (see `api.ts` on ADR 0004); none of them filters fields,
 * cuts prose or counts anything.
 */

import { apiRequest, type RequestOptions } from './api'
import type {
  Link,
  LinkList,
  Note,
  NoteCreate,
  NoteList,
  NoteUpdate,
  NoteVersion,
  NoteVersionList,
} from './types'

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

/**
 * Every note the caller owns, newest first — or, with `q`, the ones that match it (KAN-559).
 *
 * `q` is forwarded to `GET /api/v1/notes?q=` exactly as it arrived: `undefined` adds no query
 * parameter at all, which is the same request this function always made, and a defined value is
 * sent verbatim, blank or not. `app/api/search.py` is the one place that decides what a blank `q`
 * means — a present-but-empty term is a `400 empty_search_query` — and this module has no second
 * opinion to disagree with it. **Whether to send `q` at all for an empty search box is one branch
 * the caller makes**, not this function: a cleared box must send no `q`, never `q=`.
 *
 * The response is the same `NoteList` shape a plain list gets, so this stays one function rather
 * than a second one for the search case.
 */
export async function listNotes(options: Options & { q?: string } = {}): Promise<Note[]> {
  const { q, ...rest } = options
  const path = q === undefined ? 'notes' : `notes?q=${encodeURIComponent(q)}`
  const payload = await apiRequest<NoteList>(path, rest)
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

/**
 * Every note of the caller's whose body links to this one — `GET /notes/{ref}/backlinks` (KAN-568).
 *
 * **It returns `Note[]` because the API returns the same `NoteList` a plain list does**, so this is
 * `listNotes` at a different URL and there is no second type, no second envelope and no `Backlink`
 * interface anywhere in `frontend/`. `backend/app/api/links.py` argues that end of it: a backlink
 * *is* a note, and a link-shaped record would publish a second spelling of something the caller can
 * already read. `kaya-client` reached the same conclusion from the other side — its `backlinks()`
 * returns the note noun and the note columns, so `--fields` and `--full` arrived with no code
 * written for them.
 *
 * Two properties worth knowing before building on it, both `app.auth.notes_linking_to`'s rather than
 * this function's:
 *
 * - **It makes no upstream call.** "Which notes mention this one" is a join over two of kaya's own
 *   tables, so this request is answerable with pandan stopped and a cold cache (ADR 0003, SLICES
 *   §V5's R5.1). Every other read in this module needs pandan for authentication and this one does
 *   too — what it does not need is pandan for its *content*, which `/links` does.
 * - **The match key is `resolved_id`, never the title**, so renaming a note does not break the
 *   backlinks to it, and an edge whose `resolved_id` is still `NULL` is deliberately not a backlink
 *   to anything.
 *
 * Order is `updated_at DESC, id DESC` — the list order and not a relevance one, because nothing was
 * searched for. Nothing here re-sorts it.
 *
 * The ref goes through `notePath`, so it is one percent-encoded segment exactly as it is for every
 * other ref-taking call, and the suffix is appended outside the encoding.
 */
export async function listBacklinks(ref: string, options: Options = {}): Promise<Note[]> {
  const payload = await apiRequest<NoteList>(`${notePath(ref)}/backlinks`, options)
  return payload.notes
}

/**
 * Every wikilink this note's body currently contains, resolved as far as `/links` managed —
 * `GET /notes/{ref}/links` (KAN-566), read by KAN-567's editor pill.
 *
 * Unlike {@link listBacklinks}, this one is **not** the note noun: `/links` answers with `LinkRead`
 * rows, because a pill needs `target_kind`/`target_ref`/`resolved_ref`/`title`/`column` and a note
 * record has none of the first two. So `lib/types.ts` gained a `Link` interface for this call alone.
 *
 * May reach pandan for the pandan-shaped rows (`backend/app/api/links.py`) and never fails for that
 * reason — an unreachable pandan degrades every pandan-kind row to unresolved rather than refusing
 * the request (ADR 0003, Q26). A note-to-note edge never depends on pandan at all.
 */
export async function listLinks(ref: string, options: Options = {}): Promise<Link[]> {
  const payload = await apiRequest<LinkList>(`${notePath(ref)}/links`, options)
  return payload.links
}

/**
 * Every version of this note's body, newest first — `GET /notes/{ref}/versions` (R13/KAN-1064),
 * read by KAN-1065's History tab.
 *
 * **Full records, same as everything else this module returns.** The backend's design call
 * (`backend/app/api/schemas.py`'s `NoteVersionRead`) is that a version's whole `body` rides along
 * in the list response — a note body is small prose, and a preview is a selection over rows
 * already in hand, not a second request. `restoreVersion` below is what turns that selection into
 * a write.
 */
export async function listVersions(ref: string, options: Options = {}): Promise<NoteVersion[]> {
  const payload = await apiRequest<NoteVersionList>(`${notePath(ref)}/versions`, options)
  return payload.versions
}

/**
 * Restore a version: sugar over {@link updateNote}, and it must stay sugar (ADR 0008's `moveNote`
 * is the precedent — a restore is not a route, it is a `PATCH` whose `body` came from history).
 *
 * `ifUpdatedAt` is **required** here, unlike `updateNote`'s own optional precondition: a restore
 * is a write a person did not just type, aimed from a rail beside the editor rather than from
 * inside it, and BREADBOARD.md's R13 is explicit that it "goes through the same 409 precondition
 * as any other edit" — the caller (`HistoryPanel.svelte`) always has the open note's `updated_at`
 * in hand, so there is no honest reason for this one call site to spell the unguarded write.
 */
export function restoreVersion(
  ref: string,
  body: string,
  ifUpdatedAt: string,
  options: Options = {},
): Promise<Note> {
  return updateNote(ref, { body, if_updated_at: ifUpdatedAt }, options)
}

/** Delete the note. `204`, no body. The ref is never reused (ADR 0008). */
export async function deleteNote(ref: string, options: Options = {}): Promise<void> {
  await apiRequest<null>(notePath(ref), { ...options, method: 'DELETE' })
}
