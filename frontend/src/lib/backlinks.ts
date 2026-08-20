/**
 * KAN-568's backlinks rail, reduced to the two decisions that can be wrong — as pure functions.
 *
 * `lib/editor.ts` is the shape this file copies, and for the same reason: the guards are the part
 * most worth testing and the part a jsdom render could most easily obscure, so they live here as
 * values and are tested in vitest's default `node` environment. Nothing here imports a component,
 * a `fetch`, or `@codemirror/*`.
 *
 * ## Why the panel's state is a closed union rather than four booleans
 *
 * The bug this card is most likely to ship is **"nothing links here" and "the request failed"
 * rendering the same sentence**. `Sidebar.svelte` already met the milder version of it and got it
 * right — `No notes yet.` versus `No notes match "…"` — because the two states have different
 * *causes* and a reader who cannot tell them apart cannot decide whether to retry.
 *
 * Written as `{loading, failure, notes}` and read in a template, that bug is one `{:else}` away and
 * it looks like tidying up. Written as {@link PanelState}, the two are different **constructors**:
 * rendering them identically takes two template arms that say the same thing, which is a thing a
 * reviewer can see. The precedence between them stops being a chain of `{#if}`s in markup — where
 * it is invisible and untestable in the `node` layer — and becomes {@link panelState}, which has a
 * test naming each of the five.
 *
 * That is the same trade `lib/tree.ts` made by putting `path: ''` in a **named `unpathed` field**
 * rather than in a folder called `''`: give the awkward case a name and forgetting it becomes a
 * type error instead of a rendering.
 */

import type { Note } from './types'

/**
 * What the rail is showing, as one value.
 *
 * Five states, and `closed` is genuinely distinct from `empty`: "there is no note open" is not an
 * answer about a note, so it must not be able to render as one. `App.svelte` also refuses to mount
 * the panel off a note route at all, so `closed` is the *in-flight* window — the route says `note`
 * and `getNote` has not answered yet — which is exactly the moment a panel that said "nothing links
 * to this note" would be lying.
 *
 * `ref` rides along on the three states that have one, because a zero state that does not name the
 * note it is about cannot be told from the previous note's zero state left on screen. That is not a
 * hypothetical: the fetch is asynchronous and the ref changes first.
 */
export type PanelState =
  | { kind: 'closed' }
  | { kind: 'loading' }
  | { kind: 'failed'; ref: string; message: string }
  | { kind: 'empty'; ref: string }
  | { kind: 'listed'; ref: string; notes: Note[] }

/** What the component knows, before it has decided what that means. */
export interface PanelInputs {
  /** The open note's ref, or `null` when there is no note (yet). */
  ref: string | null
  /** Whether a request is in flight right now. */
  loading: boolean
  /** The last failure's message, or `null`. Cleared when a request starts. */
  failure: string | null
  /** The rows the last successful request returned. */
  notes: Note[]
}

/**
 * The one place the rail's precedence lives.
 *
 * **`loading` beats `failed`, `failed` beats the rows, and `closed` beats everything.** Each of
 * those is a decision:
 *
 * - `closed` first, because a note that has not arrived cannot have an answer *about* it. Ordering
 *   it below `loading` would be the same value with a worse name; ordering it below `empty` would
 *   put "nothing links to this note" on screen for a note the app is not sure exists.
 * - `loading` above `failed` so a retry shows that it is retrying rather than the error it is
 *   retrying past. The cost is that **a refresh blanks the list for one round trip** rather than
 *   dimming it in place, and that is the intended trade: rows held over from the previous request
 *   while a new one is in flight are rows a reader will take as current, and this panel's whole
 *   purpose is telling a reader what currently points here.
 * - `failed` above the rows for the same reason in the other direction. A list under a "could not
 *   load" line is a list somebody will read, and it is the *previous* answer. Since `notes` is
 *   cleared whenever `ref` changes, the rows that would show here are the same note's — stale by a
 *   refresh, not wrong about which note — which is exactly the kind of nearly-right that gets
 *   believed.
 *
 * A pure function of four fields, so all five states are reachable in a `node` test without a DOM,
 * a fetch or a clock.
 */
export function panelState({ ref, loading, failure, notes }: PanelInputs): PanelState {
  if (ref === null) {
    return { kind: 'closed' }
  }
  if (loading) {
    return { kind: 'loading' }
  }
  if (failure !== null) {
    return { kind: 'failed', ref, message: failure }
  }
  return notes.length === 0 ? { kind: 'empty', ref } : { kind: 'listed', ref, notes }
}

/**
 * Whether the rail has to ask the API again, rather than keep the answer it has.
 *
 * **The identity guard, and it is `lib/editor.ts`'s `needsRemount` one component over.** Reading the
 * `note` prop in an effect registers the *whole* prop, so a parent handing down a new object — for
 * any reason, including one this card cannot see — re-runs that effect whichever field is read;
 * `note.ref` and `note.body` are one signal. So "depend on identity" cannot mean "read only the
 * ref". It means **compare** the incoming ref against the ref the panel already asked about, and
 * that comparison has to be somewhere a test can reach without mounting anything.
 *
 * What this function deliberately cannot see is the **body**: there is no parameter for it, so no
 * amount of typing can reach this decision. That is the property, not the comparison — the same
 * argument `needsRemount` makes about its own missing parameter and `attach_summary` makes about
 * taking exactly one.
 *
 * `requestedFor` is the ref the last request was *issued* for, set before the request rather than
 * after it, so a failed request does not re-issue itself forever: a panel that recorded the ref only
 * on success would see `requestedFor !== ref` on the effect run the failure itself provokes.
 *
 * `null` on either side is a real value — "no note" — and `null !== null` is `false`, so the closed
 * state does not thrash.
 */
export function needsFetch(requestedFor: string | null, incomingRef: string | null): boolean {
  return requestedFor !== incomingRef
}

/**
 * The label for one backlink row.
 *
 * `''` is a legal title server-side (`String(255)`, no minimum), so a row keyed on the title alone
 * is a blank line that reads as a rendering bug. `Sidebar.svelte`'s `label()` makes the same call
 * for the same reason; it is duplicated rather than shared because the two components disagree about
 * everything else on the row and a shared one-line helper would be the first thing to grow a
 * parameter.
 */
export function backlinkLabel(note: Note): string {
  return note.title === '' ? note.ref : note.title
}
