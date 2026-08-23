/**
 * Wait for KAN-836's markdown chunk, which is the one thing about `PreviewPane` that is no longer
 * synchronous.
 *
 * `@lezer/markdown` is ~20 KB gzip behind a dynamic `import()`, so `mount()` + `flushSync()` no longer
 * leaves rendered markup in the preview: the render effect returns early until the module lands, then
 * runs again. `tests/editor-arrival.ts` is the same helper for the editor's chunk and has the longer
 * version of the argument — most of it applies verbatim, including the important half:
 *
 * **It is a poll and not a fixed number of microtask ticks.** The first `import()` in a worker really
 * loads and transforms the module; later ones resolve from the registry. A test awaiting a hard-coded
 * number of ticks passes in whichever position it happens to run in and fails when a file is
 * reordered. The `flushSync()` inside the poll is load-bearing: setting the `renderer` rune only
 * *schedules* the render effect.
 *
 * **One await per mounted preview, and it goes at the first point a non-empty document has reached
 * one.** Waiting on "there is content" is what makes the poll independent of any tick count, and it is
 * why it cannot be used to wait for an empty render — a preview showing nothing and a preview that has
 * not loaded yet are the same DOM. That costs nothing in practice, because **after the chunk arrives
 * the render effect is synchronous again**: it only reads a rune, so a keystroke renders inside its own
 * `flushSync`. `tests/preview-lazy-render.test.ts` asserts that property directly rather than leaving
 * it as an assumption these tests lean on.
 *
 * It asserts on the way out rather than returning a boolean, so a test that forgets to await it fails
 * on the missing markup instead of quietly asserting nothing.
 */

import { flushSync } from 'svelte'
import { expect, vi } from 'vitest'

/** The preview's own element — never `[class*="preview"]`, which also matches the Preview *button*. */
const PREVIEW = '[data-testid="preview"]'

/**
 * Resolve once a preview under `root` has rendered something.
 *
 * **KAN-967**: same fix as `tests/editor-arrival.ts`, for the same reason — this docstring already
 * says the two share the argument, and the reproduction that found the editor's flake caught this
 * helper's identical failure shape too (`preview-arrival.ts:40`, `expect(...).toBeGreaterThan(0)`,
 * under three concurrent full `npm test` runs). See that file's comment for the full reasoning: the
 * timeout below hands the only deadline to vitest's own per-test timeout rather than guessing a bigger
 * fixed number that just asks to be doubled again next time the machine is busier.
 */
export async function previewRendered(root: ParentNode): Promise<void> {
  await vi.waitFor(
    () => {
      flushSync()
      const element = root.querySelector(PREVIEW)
      expect(element).not.toBeNull()
      expect(element!.childNodes.length).toBeGreaterThan(0)
    },
    { timeout: 20_000 },
  )
}
