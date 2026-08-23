/**
 * Wait for KAN-767's CodeMirror chunk, which is the one thing about `EditorPane` that is no longer
 * synchronous.
 *
 * CM6 is ~80 KB gzip behind a dynamic `import()`, so `mount()` + `flushSync()` no longer leaves an
 * `EditorView` in the container: the mount effect returns early until the module lands, then runs
 * again. Every DOM test that reaches for `.cm-editor`, `.cm-content` or `EditorView.findFromDOM` has
 * to await this first, and there are four such files — so the wait lives here once rather than being
 * re-derived (differently) in each.
 *
 * **Why it is a poll and not a fixed number of microtask ticks.** The first `import()` in a worker
 * really loads and transforms the module, so it is not one tick; later ones resolve from the registry,
 * so they are. A test that awaited a hard-coded number of ticks would pass in whichever position it
 * happened to be run in and fail when a file was reordered, which is the flake that costs an
 * afternoon.
 *
 * The `flushSync()` inside the poll is load-bearing: setting the `kit` rune only *schedules* the mount
 * effect, and this file's whole job is not to leave that scheduled.
 *
 * It asserts on the way out rather than returning a boolean, so a test that forgets to await it fails
 * on the missing editor instead of quietly asserting nothing.
 */

import { flushSync } from 'svelte'
import { expect, vi } from 'vitest'

/** PLAN §S9's container, and CM6's own root inside it — the pair that says the editor exists. */
const MOUNTED = '.editor-host > .cm-editor'

/**
 * Resolve once an `EditorView` is mounted somewhere under `root`.
 *
 * `root` is the test's own host element, so a file mounting two panes (or a whole `App`) can wait on
 * the subtree it means rather than on the document.
 *
 * **KAN-967: the `timeout` below is not a bigger guess, it is a way to stop guessing.** `vi.waitFor`'s
 * own default deadline is a hardcoded 1000ms, independent of anything in `vite.config.ts` — and this
 * file's own docstring already predicted that the *first* `import()` in a worker is a genuine module
 * load rather than a tick, so a fixed budget for it is a bet on how loaded the machine happens to be.
 * Reproduced directly (three concurrent full `npm test` runs on one checkout, 16 cores): under
 * contention that load pushes past 1000ms and this poll's own `expect(...).not.toBeNull()` fails while
 * the chunk is still genuinely in flight — `tests/shell.test.ts` and `tests/backlinks-rail.test.ts`
 * both did, verbatim, on `editor-arrival.ts:39`.
 *
 * Raising the fixed number is the fix that comes back asking to be doubled again the next time
 * something loads the machine harder — it never stops being a guess, just a bigger one. So instead
 * this hands the *only* deadline to vitest's own per-test timeout (5000ms by default here, and already
 * the bound every other timing-sensitive assertion in this suite lives under): 20000ms is comfortably
 * below Node's ~24.8-day `setTimeout` ceiling — past which a delay silently clamps to firing almost
 * immediately, which would make "unbounded" backfire — and comfortably above any per-test timeout in
 * this repo, so this inner deadline is never the one that fires. A chunk that genuinely never arrives
 * (an actual regression, not contention) still fails the test: vitest's own timeout catches it, it just
 * reports "Test timed out in Nms" at the `it()` block rather than this file's more specific assertion.
 * That is the trade for having only one number to keep honest instead of two drifting apart — see
 * CLAUDE.md's KAN-967 section for the fuller argument, including why a resolved-module cache primed
 * once per file was rejected (several of these tests, e.g. `editor-lazy-mount.test.ts`, exist
 * specifically to exercise a mount *while* the import is still in flight, and priming it away would
 * delete the race under test) and why literal `Infinity` is not the same as "unbounded" here.
 */
export async function editorArrived(root: ParentNode): Promise<void> {
  await vi.waitFor(
    () => {
      flushSync()
      expect(root.querySelector(MOUNTED)).not.toBeNull()
    },
    { timeout: 20_000 },
  )
}
