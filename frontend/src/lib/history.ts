/**
 * KAN-1064/1065/1066's History tab, reduced to the decisions that can be wrong — as pure functions.
 *
 * `lib/backlinks.ts` is the shape this file copies, component for component and for the identical
 * reason: the guards are the part most worth testing and the part a jsdom render could most easily
 * obscure, so they live here as values, tested in vitest's default `node` environment. Nothing here
 * imports a component, a `fetch`, or `@codemirror/*`.
 *
 * ## Why the panel's state is a closed union rather than four booleans
 *
 * `BacklinksPanel`'s docstring already makes this argument in full and it applies here verbatim:
 * "nothing links here" and "the request failed" must not be able to render the same sentence, and
 * neither must "no history yet" and "the request failed" here — a note with no versions is not a
 * state this panel can actually be in (`create_note` cuts one too, per `app/note_versions.py`), but
 * the type still has to keep the two apart so a future relaxation of that guarantee cannot make them
 * drift into one sentence unnoticed.
 */

import type { NoteVersion } from './types'

/**
 * What the tab is showing, as one value. Five states, matching `BacklinksPanel`'s `PanelState` verb
 * for verb — see its docstring for why `closed` is genuinely distinct from `empty`, and why `ref`
 * rides along on every state that has one.
 */
export type PanelState =
  | { kind: 'closed' }
  | { kind: 'loading' }
  | { kind: 'failed'; ref: string; message: string }
  | { kind: 'empty'; ref: string }
  | { kind: 'listed'; ref: string; versions: NoteVersion[] }

/** What the component knows, before it has decided what that means. */
export interface PanelInputs {
  /** The open note's ref, or `null` when there is no note (yet). */
  ref: string | null
  /** Whether a request is in flight right now. */
  loading: boolean
  /** The last failure's message, or `null`. Cleared when a request starts. */
  failure: string | null
  /** The rows the last successful request returned. */
  versions: NoteVersion[]
}

/**
 * The one place the tab's precedence lives — `BacklinksPanel`'s `panelState`, one field renamed.
 * See that function's docstring for the full argument behind `closed` > `loading` > `failed` >
 * the rows; nothing about the order changes for a version list instead of a note list.
 */
export function panelState({ ref, loading, failure, versions }: PanelInputs): PanelState {
  if (ref === null) {
    return { kind: 'closed' }
  }
  if (loading) {
    return { kind: 'loading' }
  }
  if (failure !== null) {
    return { kind: 'failed', ref, message: failure }
  }
  return versions.length === 0 ? { kind: 'empty', ref } : { kind: 'listed', ref, versions }
}

/**
 * Whether the tab has to ask the API again, rather than keep the answer it has.
 *
 * Byte-identical to `lib/backlinks.ts`'s `needsFetch` and duplicated rather than imported: the two
 * components disagree about everything else they fetch, and a shared one-line comparison would be
 * the first thing either of them grows a parameter onto. See that function's docstring for the full
 * argument — the identity guard, one component over.
 */
export function needsFetch(requestedFor: string | null, incomingRef: string | null): boolean {
  return requestedFor !== incomingRef
}

/**
 * Whether `version` is the one the panel is currently previewing.
 *
 * A plain id comparison, named so the component's markup reads as a decision rather than as
 * `selected === version.id` repeated at every call site. `selected` is `null` for "nothing chosen",
 * which is a real, renderable state (`BacklinksPanel`-style history's default) and not an absence
 * this function has to special-case — `null === version.id` is simply always `false`.
 */
export function isSelected(selected: number | null, version: NoteVersion): boolean {
  return selected === version.id
}
