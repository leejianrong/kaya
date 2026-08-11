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
 */
export async function editorArrived(root: ParentNode): Promise<void> {
  await vi.waitFor(() => {
    flushSync()
    expect(root.querySelector(MOUNTED)).not.toBeNull()
  })
}
