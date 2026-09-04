// @vitest-environment jsdom
/**
 * The window KAN-836 opened: **`PreviewPane` is mounted, and the markdown renderer has not arrived
 * yet** — and the property that closes it again, which is that *after* it arrives nothing is
 * asynchronous any more.
 *
 * `tests/editor-lazy-mount.test.ts` is this file's sibling one layer up, and the two failure modes are
 * **not the same**, which is the thing worth being exact about. The editor builds a stateful object
 * into a host and owns a teardown, so an `await` at the top of its mount effect risks two views in one
 * container or an orphan whose `destroy()` is never called. This component builds nothing and tears
 * nothing down: `replaceChildren` is total and idempotent, so a second run cannot leak the first and
 * there is no orphan to leave behind. What an `await` in the render effect costs here is different, and
 * worse for being quieter:
 *
 * - **The subscription.** Svelte registers an effect's dependencies during its *synchronous* pass only.
 *   `await import(…)` before the `source` read means `source` is never registered, so the preview
 *   renders the document it was mounted with and then **never moves again** — no error, no leak,
 *   nothing in the DOM to look at. `keeps rendering every later document` below is the assertion that
 *   goes red for it; that was measured by building the naive version, not reasoned out.
 * - **Ordering.** Two awaited runs resolve in whatever order their promises settle, so a stale document
 *   can land on top of a fresh one. `renders the document that is current when the module lands` covers
 *   the shape of that.
 *
 * The design that avoids both is KAN-767's, unchanged: the `import()` lives in the effect that **reads
 * nothing**, so it runs exactly once per component, and the render effect only *reads* the resulting
 * rune with all three of its dependencies read above the guard.
 */

import { flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import PreviewPane from '../src/components/PreviewPane.svelte'
import type { Note } from '../src/lib/types'
import { previewRendered } from './preview-arrival'
import { box, type Box } from './reactive.svelte'

const NOTE: Note = {
  ref: 'NOTE-6',
  id: 6,
  title: 'Weekly review',
  body: '# Week of 2026-08-03\n',
  path: 'journal/weekly.md',
  created_at: '2026-08-09T09:00:00+00:00',
  updated_at: '2026-08-09T10:00:00.123456+00:00',
  team_id: null,
}

let host: HTMLDivElement
const mounted: unknown[] = []

/**
 * Mount the pane and return **without waiting for the chunk** — which is the whole instrument here.
 *
 * `flushSync()` runs the effects, so the loader has started its `import()` and the element exists; the
 * element being *empty* at that moment is asserted below as the positive control, because a test acting
 * "before the module lands" is worth nothing if the module already landed.
 */
function mountUnsettled(initial: string): { source: Box<string>; element: HTMLElement } {
  const source = box(initial)
  mounted.push(
    mount(PreviewPane, {
      target: host,
      props: {
        note: NOTE,
        get source() {
          return source.value
        },
      },
    }),
  )
  flushSync()
  return { source, element: host.querySelector('[data-testid="preview"]')! }
}

/** Long enough for a resolved dynamic import and any effect it schedules. */
async function settle(): Promise<void> {
  for (let turn = 0; turn < 10; turn += 1) {
    await new Promise((resolve) => setTimeout(resolve, 5))
    flushSync()
  }
}

beforeEach(() => {
  host = document.createElement('div')
  document.body.append(host)
})

afterEach(() => {
  for (const instance of mounted.splice(0)) {
    unmount(instance as never)
  }
  host.remove()
})

describe('before the markdown chunk arrives', () => {
  it('shows an empty element, and Svelte has put nothing in it', () => {
    // The positive control for every test in this file, and a guard in its own right: `.rendered`'s
    // children belong to `replaceChildren`, so a Svelte-owned "loading…" placed in there — the obvious
    // thing to reach for in exactly this state — is a node Svelte will later try to update after the
    // renderer has thrown it away. `childNodes` and not `children`, because the risk is a text node.
    const { element } = mountUnsettled('# Something to render')

    expect(element.childNodes).toHaveLength(0)
  })

  it('renders the document that is current when the module lands', async () => {
    // A document changing inside the gap. The render effect reads `source` at the moment it runs, so
    // there is only ever one render and it is of the current value — an implementation that captured
    // the source before an `await` would paint the first one and, worse, could paint it *after* a
    // later run had already painted the second.
    const { source, element } = mountUnsettled('# First')
    expect(element.childNodes).toHaveLength(0)

    source.value = '# Second'
    flushSync()

    await previewRendered(host)
    await settle()

    expect(element.querySelectorAll('h1')).toHaveLength(1)
    expect(element.querySelector('h1')!.textContent).toBe('Second')
    expect(element.textContent).not.toContain('First')
  })

  it('never renders into an element the app has already discarded', async () => {
    // The preview's version of the editor's orphan test. Nothing here leaks a listener or an object, so
    // this is the weaker of the two — but the element is captured before the unmount and asserted
    // after, which is the only way to see a write into a detached node at all.
    const { element } = mountUnsettled('# Something')
    expect(element.childNodes).toHaveLength(0)

    unmount(mounted.pop() as never)
    flushSync()
    await settle()

    expect(element.childNodes).toHaveLength(0)
  })
})

describe('after the markdown chunk arrives', () => {
  it('keeps rendering every later document', async () => {
    // **The assertion the naive `await import()` at the top of the render effect fails**, and it fails
    // silently: `source` read after an `await` is not a dependency, so the first render is correct and
    // every one after it never happens. Three turns rather than one, because a single later render
    // could pass on a coincidence.
    const { source } = mountUnsettled('*one*')
    await previewRendered(host)
    const element = host.querySelector('[data-testid="preview"]')!

    for (const [text, expected] of [
      ['**two**', 'two'],
      ['`three`', 'three'],
      ['# four', 'four'],
    ] as const) {
      source.value = text
      flushSync()
      expect(element.textContent).toBe(expected)
    }
  })

  it('renders inside the same flush, with nothing left to await', async () => {
    // The property `tests/preview-arrival.ts` leans on, asserted rather than assumed: once the module
    // is in, the render effect only *reads* a rune, so a document change is painted by the `flushSync`
    // that delivered it. An implementation that awaited per render would leave this element stale here
    // and would make every preview assertion in the suite a race.
    const { source } = mountUnsettled('# Before')
    await previewRendered(host)
    const element = host.querySelector('[data-testid="preview"]')!

    source.value = '# After'
    flushSync()

    expect(element.querySelector('h1')!.textContent).toBe('After')
  })
})
