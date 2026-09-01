/**
 * `GET /api/v1/embeds/board` — KAN-1049's one call, for a note's `pandan-board` embed.
 *
 * A single function rather than a fifth entry in `notes.ts`: this is not a note noun (it answers
 * with pandan's own `EmbedCard` rows, unrelated to `Note`/`Link`), and it is the one fetch in this
 * repo whose contract is "never reject" rather than "reject with something typed" — see
 * {@link fetchBoardEmbed}'s own docstring for why.
 */

import { apiRequest, type RequestOptions } from './api'
import type { BoardEmbedResponse } from './types'

export interface BoardEmbedQuery {
  board: number
  /** Exactly one of `view`/`column` is expected — `lib/markdown.ts` already refused the block at
   *  parse time otherwise, so this function does not re-validate the pair. */
  view?: number
  column?: string
  signal?: AbortSignal
  /** Injectable for tests, same as every call in `notes.ts`. Defaults to the ambient `fetch`. */
  fetchImpl?: RequestOptions['fetchImpl']
}

/**
 * The live cards for one `pandan-board` embed, or `null` for a transport-level failure.
 *
 * **Never throws and never returns a rejected promise.** Every other fetch in this repo
 * (`notes.ts`) lets `ApiError`/`NetworkError` propagate, because a note read failing is something a
 * caller must notice. This one is different for the same reason `app/api/embeds.py` degrades
 * server-side rather than raising: a board embed is a decoration inside a note preview, not the
 * note, and ADR 0003's "nothing in kaya may block on pandan" reads the same way one layer up in the
 * client that renders it. `PreviewPane.svelte` treats `null` exactly like `{ unavailable: true,
 * cards: [] }` — both are "could not show this", and there is no reason for its hydration code to
 * carry two branches for one outcome.
 *
 * A **caller-visible** `ApiError` still surfaces here in one case worth naming: a missing bearer
 * (`MissingCredential`, itself an `ApiError`) is swallowed the same as everything else, because an
 * unauthenticated tab has no business retrying a board fetch either — the preview already shows
 * nothing useful without a session, and a board embed failing quietly is consistent with every
 * other decoration in that state.
 */
export async function fetchBoardEmbed(query: BoardEmbedQuery): Promise<BoardEmbedResponse | null> {
  const { board, view, column, signal, fetchImpl } = query
  const params = new URLSearchParams({ board: String(board) })
  if (view !== undefined) {
    params.set('view', String(view))
  }
  if (column !== undefined) {
    params.set('column', column)
  }

  const options: RequestOptions = { signal, fetchImpl }
  try {
    return await apiRequest<BoardEmbedResponse>(`embeds/board?${params.toString()}`, options)
  } catch {
    // Every failure reason collapses to the same answer — a `NetworkError`, an aborted fetch (a
    // stale hydration pass, `PreviewPane.svelte`'s re-render guard), or an `ApiError` of any status
    // including a 401/422 this function's own caller could never have caused (the query was already
    // validated at parse time in `lib/markdown.ts`). See the docstring above for why nothing here is
    // worth telling apart from the caller's side.
    return null
  }
}
