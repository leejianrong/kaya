/**
 * `GET /api/v1/graph` — the whole of `note_link`, node-and-edge shaped (KAN-1050).
 *
 * One function, following `lib/notes.ts`'s own convention rather than the `Promise<T | null>`
 * shape the card sketched: every existing note-fetch function here (`listNotes`, `getNote`,
 * `listBacklinks`, `listLinks`) returns the payload verbatim and **rejects** on failure —
 * `MissingCredential`, `ApiError` or `NetworkError`, from `lib/api.ts`. A component decides what a
 * failure means (`BacklinksPanel.svelte`'s `absorb`); this module does not swallow one into `null`,
 * which would erase the distinction between "no notes yet" and "the request failed" that the
 * caller needs to render two different states.
 */

import { apiRequest, type RequestOptions } from './api'
import type { GraphRead } from './types'

type Options = Pick<RequestOptions, 'signal' | 'fetchImpl'>

/** The caller's whole note graph: every note they own, and every resolved link between two of
 *  them. An owner with no notes gets `{nodes: [], edges: []}` — not an error. */
export function fetchGraph(options: Options = {}): Promise<GraphRead> {
  return apiRequest<GraphRead>('graph', options)
}
