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
  /**
   * The team this note defaults to team-wide access for (ADR 0011, R16.7) — `null` for the
   * overwhelming majority of notes, which stay personal. A plain id: kaya never fetches a team's
   * name (`app/models/team.py`'s mirror carries only an id, on purpose), so that is all a badge
   * can ever show.
   */
  team_id: number | null
}

/** `GET /api/v1/notes`. A named envelope so `summary` and `next_cursor` can be added later. */
export interface NoteList {
  notes: Note[]
}

/**
 * One outbound wikilink of a note, resolved as far as it can be — `GET /notes/{ref}/links`
 * (KAN-566), mirroring `backend/app/api/schemas.py`'s `LinkRead` field for field.
 *
 * Every resolved-side field is nullable and `null` is the honest value rather than a missing key
 * (Q26): a `[[...]]` pandan does not have, a `[[...]]` this caller cannot see, a network failure
 * reaching pandan, and a `[[Title]]` naming no note the caller owns all collapse into the same
 * `null` — a caller cannot and should not act differently on any of the four.
 */
export interface Link {
  /** `"KAN"`, `"EPIC"` or `"NOTE"`. A plain string, not a union of those three literals, for the
   *  same reason the backend keeps it a plain column: a kind this build has never heard of is
   *  possible and must render as unresolved rather than fail to parse. */
  target_kind: string
  /** What the body actually said between the brackets — never rewritten by a rename or a move. */
  target_ref: string
  /** The canonical identifier this link resolves to, or `null` when unresolved. */
  resolved_ref: string | null
  /** The resolved thing's *current* title, or `null` when unresolved. */
  title: string | null
  /** Pandan's column name for a resolved card, `null` for an epic, a note, or anything unresolved. */
  column: string | null
}

/** `GET /notes/{ref}/links`'s envelope — named, like `NoteList`, for the same reason. */
export interface LinkList {
  links: Link[]
}

/**
 * One node in the note graph — `GET /api/v1/graph` (KAN-1050), mirroring
 * `backend/app/api/schemas.py`'s `GraphNode` field for field.
 *
 * `ref` rather than `id` (ADR 0008 — a note's identity is its ref) — `navigate()`/`routeHref()`
 * already take refs everywhere else in this app, and a graph node is a note like any other row.
 */
export interface GraphNode {
  ref: string
  title: string
  path: string
}

/**
 * One resolved note-to-note wikilink, as the two refs it connects.
 *
 * Both `NOTE-n`, never an internal id — see `GraphNode`. There is no `target_kind` here: this
 * graph is note-to-note edges only, a cross-repo `[[KAN-501]]`/`[[EPIC-3]]` reference is out of
 * scope for it (`backend/app/api/schemas.py`'s `GraphEdge`).
 */
export interface GraphEdge {
  source: string
  target: string
}

/** `GET /api/v1/graph`'s envelope — bare, not a named-array wrapper, because it already carries
 *  two arrays and is rendered as one diagram rather than a page of rows. */
export interface GraphRead {
  nodes: GraphNode[]
  edges: GraphEdge[]
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
 * One snapshot of a note's body — `GET /notes/{ref}/versions` (R13/KAN-1064), mirroring
 * `backend/app/api/schemas.py`'s `NoteVersionRead` field for field.
 *
 * `body` is the **whole** body, not a snippet: the backend's preview-endpoint design call
 * (`NoteVersionRead`'s own docstring) is that a note body is small prose, same as `Note.body`
 * itself, so a version list carries every row's full text and a preview is a client-side
 * selection rather than a second request per click.
 */
export interface NoteVersion {
  /** `note_version`'s own surrogate key — a row key for `{#each}`, nothing more. Unlike every
   *  identifier on {@link Note}, this names no independently addressable resource: there is no
   *  `GET .../versions/{id}`, by the design call above. */
  id: number
  body: string
  created_at: string
}

/** `GET /notes/{ref}/versions`'s envelope — named, like `NoteList`/`LinkList`, for the same
 *  reason. */
export interface NoteVersionList {
  versions: NoteVersion[]
}

/**
 * One card in a `pandan-board` embed — `GET /api/v1/embeds/board` (KAN-1049), mirroring
 * `backend/app/api/schemas.py`'s `EmbedCard`.
 *
 * `ref` is pandan's own `ticket_number` (`"KAN-12"`), never a kaya `NOTE-n` — a different ref
 * system entirely (ADR 0008). This interface is deliberately not near `Note`/`Link` for that
 * reason.
 */
export interface EmbedCard {
  ref: string
  title: string
  column: string
}

/**
 * `GET /api/v1/embeds/board`'s body. Always a `200` from the backend, `unavailable: true` covering
 * every reason pandan could not answer (down, the board/view does not exist, or the caller cannot
 * see it) — a caller cannot and should not act differently on any of them (ADR 0003).
 */
export interface BoardEmbedResponse {
  unavailable: boolean
  cards: EmbedCard[]
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
