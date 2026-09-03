// @vitest-environment jsdom
/**
 * The window KAN-767 opened: **`EditorPane` is mounted, and CodeMirror has not arrived yet.**
 *
 * Every other editor test awaits `editorArrived()` and then asserts on a settled pane. This file is
 * the opposite — it acts *inside* the gap, because that gap is the only thing the lazy chunk changed
 * about this component's behaviour and both of its failure modes are invisible from a green suite:
 *
 * - **Two views in one container.** The note changes while the module is in flight. If the mount path
 *   can be in flight twice, both attempts build into the same `.editor-host` and the second view sits
 *   on top of the first, which still holds a document, a history and an update listener.
 * - **An orphan.** The pane is unmounted while the module is in flight. If a build happens afterwards
 *   it goes into a detached container that no cleanup will ever visit again, so `view.destroy()` is
 *   never called — a leaked `EditorView` in a container the app has already thrown away.
 *
 * **The design is what prevents both, rather than a check bolted on after the fact**, and stating that
 * precisely is the point of this docstring. The `import()` lives in the effect that *reads nothing* —
 * the same effect that owns the per-component teardown — so it runs exactly once per component, and
 * the mount effect only ever *reads* the resulting rune. That leaves the mount effect synchronous,
 * which is what keeps KAN-553's whole argument intact: two runs of it cannot interleave, a cleanup
 * cannot fire between an `await` and the build it was going to reverse, and there is nothing to
 * cancel.
 *
 * The tempting alternative is to `await import()` at the top of the mount effect. It reads better and
 * it is wrong, and **which of the tests below catches it was measured rather than assumed** — worth
 * writing down, because the answer is not the one the reasoning above suggests.
 *
 * Building the naive version and running this file: the **orphan** test goes red, decisively — an
 * `EditorView` holding `first note body` sits in the detached container after unmount, with a live
 * update listener nothing will ever destroy. The two navigation tests stay **green**, and the reason is
 * specific: in the naive form every run awaits the *same* pending module promise, so the runs resolve
 * in queue order and each one's `view?.destroy()` in the effect body happens to tidy up the one before
 * it. Two views in one container needs a `view` captured across the `await`, which that shape does not
 * do. So the navigation tests are not the discriminator here; they are the coverage for a state PLAN
 * §S9's other guards never see (an unsettled container), and their positive control — the container
 * being empty before the chunk lands — did catch a Svelte interpolation put inside `.editor-host`
 * during this card's mutation run.
 */

import { EditorView } from '@codemirror/view'
import { flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import EditorPane from '../src/components/EditorPane.svelte'
import type { Note } from '../src/lib/types'
import { editorArrived } from './editor-arrival'
import { box, type Box } from './reactive.svelte'

function note(overrides: Partial<Note> = {}): Note {
  return {
    ref: 'NOTE-6',
    id: 6,
    title: 'Weekly review',
    body: 'first note body\n',
    path: 'journal/weekly.md',
    created_at: '2026-08-09T09:00:00+00:00',
    updated_at: '2026-08-09T10:00:00.123456+00:00',
    team_id: null,
    ...overrides,
  }
}

let host: HTMLDivElement
const mounted: unknown[] = []

/**
 * Mount the pane and return **without waiting for the chunk** — which is the whole instrument here.
 *
 * `flushSync()` runs the effects, so the loader has started its `import()` and the container element
 * exists; the container being *empty* at that moment is asserted below as the positive control,
 * because a test acting "before the module lands" is worth nothing if the module already landed.
 */
function mountUnsettled(initial: Note | null = note()): {
  opened: Box<Note | null>
  container: HTMLElement
  instance: unknown
} {
  const opened = box<Note | null>(initial)
  const instance = mount(EditorPane, {
    target: host,
    props: {
      get note() {
        return opened.value
      },
      error: null,
    },
  })
  mounted.push(instance)
  flushSync()
  return { opened, container: host.querySelector('.editor-host')!, instance }
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
  vi.restoreAllMocks()
})

describe('a note change while the editor chunk is still in flight', () => {
  it('builds one view, for the note that is open when the module lands', async () => {
    const { opened, container } = mountUnsettled(note())

    // The positive control. If this is non-empty the chunk was already resolved and the "before it
    // lands" premise of everything below is false — which is exactly how a race test quietly stops
    // testing a race.
    expect(container.childNodes).toHaveLength(0)

    // Navigation, arriving in the gap.
    opened.value = note({ ref: 'NOTE-7', id: 7, body: 'second note body\n' })
    flushSync()

    await editorArrived(host)
    await settle()

    // One view, and it is the second note's. Two is the leak; one showing `first note body` would mean
    // the build used a note that had already been navigated away from.
    expect(container.querySelectorAll('.cm-editor')).toHaveLength(1)
    expect(container.querySelector('.cm-content')!.textContent).toContain('second note body')
    expect(container.querySelector('.cm-content')!.textContent).not.toContain('first note body')
    // And nothing Svelte made got in either, in a state PLAN §S9's other guards never see.
    expect(Array.from(container.childNodes).map((child) => child.nodeName)).toEqual(['DIV'])
  })

  it('survives a burst of navigation inside the gap, with one view at the end', async () => {
    // Four refs handed down before the module has arrived. An implementation whose mount path can be
    // in flight more than once produces a view per ref that got a run, all of them in this container.
    const { opened, container } = mountUnsettled(note())
    expect(container.childNodes).toHaveLength(0)

    for (const ref of ['NOTE-7', 'NOTE-8', 'NOTE-9', 'NOTE-10']) {
      opened.value = note({ ref, body: `body of ${ref}\n` })
      flushSync()
    }

    await editorArrived(host)
    await settle()

    expect(container.querySelectorAll('.cm-editor')).toHaveLength(1)
    expect(container.querySelector('.cm-content')!.textContent).toContain('body of NOTE-10')
  })
})

describe('an unmount while the editor chunk is still in flight', () => {
  it('never builds a view, so there is no orphan in the discarded container', async () => {
    // **The container is captured before the unmount and asserted after**, and that is the only way to
    // see this failure: `unmount` detaches `.editor-host` from `host`, so a view built afterwards goes
    // into an element `host.querySelector` can no longer reach. Checking the live document would come
    // back clean while an `EditorView` with a live update listener sat in the detached node forever.
    const { container, instance } = mountUnsettled()
    expect(container.childNodes).toHaveLength(0)

    unmount(instance as never)
    mounted.length = 0
    flushSync()

    await settle()

    expect(container.querySelector('.cm-editor')).toBeNull()
    expect(container.childNodes).toHaveLength(0)
    expect(host.querySelector('.cm-editor')).toBeNull()
  })

  it('does not destroy a view it never built', async () => {
    // The other direction, and it is worth an assertion of its own: a teardown that "cleaned up" a
    // view that does not exist would be a `TypeError` on an unmount nobody was watching.
    const destroy = vi.spyOn(EditorView.prototype, 'destroy')
    const { instance } = mountUnsettled()

    unmount(instance as never)
    mounted.length = 0
    await settle()

    expect(destroy).not.toHaveBeenCalled()
  })
})
