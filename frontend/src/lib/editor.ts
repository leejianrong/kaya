/**
 * The three decisions `EditorPane.svelte` makes, extracted so they can be tested without a DOM.
 *
 * Two of them are the guards ADR 0001 §2 and PLAN §Open risks are about, and they guard **opposite
 * directions** through the same seam. They are easy to confuse and they are not interchangeable, so
 * they are named here rather than left as two inline `!==` comparisons in an `$effect`:
 *
 * - {@link needsRemount} — **the identity guard**, on the way *in*. A note's document is swapped by
 *   `dispatch`, never by building a second `EditorView`. Without it, a parent handing down a new
 *   `Note` object per keystroke rebuilds the view on every character: the cursor jumps to the start,
 *   the undo history is gone, and the next keystroke fights the rebuild.
 * - {@link needsDispatch} — **the echo guard**, on the way *back in* after having gone out. CM6's
 *   `updateListener` fires for every transaction, including the ones our own code dispatched, so
 *   `updateListener → set rune → effect → dispatch → updateListener` is a live cycle. Comparing the
 *   incoming string against the editor's current document breaks it at the one point where the two
 *   are provably the same value.
 *
 * The third, {@link conflictVersions}, is ADR 0009's `409` read out of `ApiError.details`.
 *
 * Nothing here imports CodeMirror at **runtime**. The `EditorView` reference below is an
 * `import type`, which `verbatimModuleSyntax` erases entirely — so this module loads in vitest's
 * default `node` environment, where `@codemirror/view`'s module-level browser sniffing would not.
 * The guards are the part most worth testing and the part jsdom's missing measurement APIs could
 * most easily obscure; keeping them reachable from a plain `node` test is deliberate (dev-playbook
 * §2).
 */

import type { Annotation } from '@codemirror/state'
import type { EditorView } from '@codemirror/view'

import type { Note } from './types'

/**
 * Whether the `EditorView` has to be built again, rather than handed a new document.
 *
 * **The identity guard.** ADR 0008: a note's identity is its `NOTE-n` ref and nothing else, so the
 * ref is the only thing a remount may depend on. `null` is a legitimate value on both sides — it is
 * "no note open", which gets its own read-only view — and `null !== null` is `false`, so the
 * no-note state does not thrash either.
 *
 * `hasView` is a separate parameter instead of being folded into a nullable ref because "no view
 * yet" and "a view showing no note" are different states that must not be spelled the same way. The
 * first has to build; the second must not.
 *
 * Note what this function deliberately cannot see: the body. There is no parameter for it, so no
 * amount of content change can reach this decision — the same shape as `attach_summary` taking one
 * argument in `kaya-client`, where "it cannot describe the corpus" is a fact about what is in scope
 * rather than a rule someone follows.
 */
export function needsRemount(
  hasView: boolean,
  mountedRef: string | null,
  incomingRef: string | null,
): boolean {
  return !hasView || mountedRef !== incomingRef
}

/**
 * Whether `incoming` differs from what the editor already holds.
 *
 * **The echo guard.** One comparison, and the reason it is a named function is that it is the whole
 * of ADR 0001 §2's "the write-back needs a guard comparing against the editor's current document".
 * An exact string comparison rather than a normalising one: CM6's document is the authority on its
 * own text, so any normalisation here would make the two sides disagree about equality and the
 * cycle would resume on whatever the normaliser changed.
 */
export function needsDispatch(incoming: string, current: string): boolean {
  return incoming !== current
}

/**
 * Put `incoming` into the view as a **transaction**, unless the echo guard says it is already there.
 *
 * Returns whether a transaction was dispatched, so a caller — or a test — can assert the negative
 * case without reaching into CM6's internals.
 *
 * A single change spanning the whole document rather than a diff. CM6 maps the selection through the
 * change, so a replace-all does move the caret; that is acceptable *because of* the guard, which
 * means this only ever runs for a document the editor did not already have (an external update to a
 * note that is still open). The keystroke path never reaches here, which is the point.
 *
 * `annotations` is KAN-556's addition and it is **passed in rather than chosen here**, because the
 * only annotation anyone wants on this transaction is `isolateHistory` and that lives in
 * `@codemirror/commands` — a *runtime* CodeMirror import, which this module deliberately has none of
 * (see the header: it keeps the guards reachable from a plain `node` test). The `Annotation` types
 * below are `import type`, so `verbatimModuleSyntax` erases them and nothing changes about what this
 * file loads. "Keep theirs" is why: a discard has to be exactly **one** undo, and without isolation
 * CM6 merges it into the typing group it interrupted, so undo would revert the user's own text too.
 *
 * Typed against `EditorView` through an erased `import type`, so a test can hand it a stub and the
 * integration test can hand it the real thing.
 */
export function syncDocument(
  view: EditorView,
  incoming: string,
  annotations: readonly Annotation<unknown>[] = [],
): boolean {
  if (!needsDispatch(incoming, view.state.doc.toString())) {
    return false
  }
  view.dispatch({
    changes: { from: 0, to: view.state.doc.length, insert: incoming },
    ...(annotations.length === 0 ? {} : { annotations: [...annotations] }),
  })
  return true
}

/**
 * ADR 0009's two versions, out of an `ApiError`'s extras, or `null` if they are not both there.
 *
 * `backend/app/api/concurrency.py` puts `attempted` and `stored` on the `409` body as two **whole**
 * notes, because "your write was refused" is not actionable and a side-by-side of two prose bodies
 * needs both bodies whole. `api.ts` spreads everything past `code`/`message` into `details`, so this
 * is the read that turns those extras back into something typed.
 *
 * It returns `null` rather than throwing or half-filling, and the caller must show the refusal
 * anyway on `null` — a conflict that fails to parse is still a conflict, and a `409` that reaches a
 * user as silence is the exact failure ADR 0009 exists to prevent.
 *
 * This is **not** the conflict banner. KAN-556 owns the side-by-side and keep-mine/keep-theirs, and
 * it needs these two records intact; this function exists so that card reads `details` in one place
 * instead of re-deriving the shape.
 */
export function conflictVersions(
  details: Record<string, unknown>,
): { attempted: Note; stored: Note } | null {
  const attempted = details.attempted
  const stored = details.stored
  return isNote(attempted) && isNote(stored) ? { attempted, stored } : null
}

/**
 * A note-shaped object off the wire.
 *
 * Checks the three fields a conflict is *about* — the ref that identifies it, the `updated_at` the
 * two versions differ in, and the body a diff needs — rather than every key in `Note`. A stricter
 * check would turn one added optional field on the API side into a swallowed conflict.
 */
function isNote(value: unknown): value is Note {
  if (typeof value !== 'object' || value === null) {
    return false
  }
  const candidate = value as Partial<Note>
  return (
    typeof candidate.ref === 'string' &&
    typeof candidate.updated_at === 'string' &&
    typeof candidate.body === 'string'
  )
}
