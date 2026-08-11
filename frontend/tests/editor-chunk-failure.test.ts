// @vitest-environment jsdom
/**
 * The chunk that does not arrive (KAN-767).
 *
 * A lazily-loaded module is one more network request, so it is one more thing that can fail — offline,
 * a cache miss against a deploy that replaced the asset while this tab was open, a proxy in the way.
 * The bytes moved out of the entry chunk in exchange for that risk, and the price of taking it is
 * saying something when it happens: unhandled, the symptom is an empty bordered rectangle with no
 * explanation, which is a worse page than the slow one this card was written to fix.
 *
 * **Its own file, because the mock has to be hoisted.** `vi.mock` runs before the module graph is
 * built, which is the only way a *dynamic* import made later by a component resolves to it —
 * `vi.doMock` plus `vi.resetModules()` in a shared file does not work here, and the way it fails is
 * worth writing down: re-importing the component after a module reset gives it a second copy of the
 * Svelte runtime, and mounting it throws `effect_orphan` from inside `$effect` rather than testing
 * anything. So this file never loads the real `lib/codemirror` at all.
 */

import { flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import EditorPane from '../src/components/EditorPane.svelte'
import type { Note } from '../src/lib/types'

// A factory that throws is a chunk that 404s: the `import()` in the loader effect rejects, which is
// exactly the shape of the real failure.
vi.mock('../src/lib/codemirror', () => {
  throw new Error('Failed to fetch dynamically imported module')
})

const NOTE: Note = {
  ref: 'NOTE-6',
  id: 6,
  title: 'Weekly review',
  body: '# Week of 2026-08-03\n',
  path: 'journal/weekly.md',
  created_at: '2026-08-09T09:00:00+00:00',
  updated_at: '2026-08-09T10:00:00.123456+00:00',
}

let host: HTMLDivElement
const mounted: unknown[] = []

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

describe('the editor chunk failing to load', () => {
  it('says so in words, instead of leaving an empty box', async () => {
    mounted.push(mount(EditorPane, { target: host, props: { note: NOTE, error: null } }))

    await vi.waitFor(() => {
      flushSync()
      expect(host.querySelector('[data-testid="editor-unavailable"]')).not.toBeNull()
    })

    expect(host.querySelector('[data-testid="editor-unavailable"]')!.textContent).toContain(
      'could not be loaded',
    )
  })

  it('holds PLAN §S9 in the failure state too', async () => {
    // The notice that explains why S9's occupant is missing must not itself be a Svelte node inside
    // S9's element. An empty container is the honest rendering of "there is no editor", and this is the
    // one state in which putting a word of text in there would look like the obvious thing to do.
    mounted.push(mount(EditorPane, { target: host, props: { note: NOTE, error: null } }))
    await vi.waitFor(() => {
      flushSync()
      expect(host.querySelector('[data-testid="editor-unavailable"]')).not.toBeNull()
    })

    const container = host.querySelector('.editor-host')!
    const notice = host.querySelector('[data-testid="editor-unavailable"]')!

    expect(container.childNodes).toHaveLength(0)
    expect(container.contains(notice)).toBe(false)
  })

  it('is not reported as a refused save, because it is not one', async () => {
    // `refusal` means "the server refused a write". Folding a load failure into it would put a network
    // error in the slot a `409` uses and make a bug report ambiguous about which half broke.
    mounted.push(mount(EditorPane, { target: host, props: { note: NOTE, error: null } }))
    await vi.waitFor(() => {
      flushSync()
      expect(host.querySelector('[data-testid="editor-unavailable"]')).not.toBeNull()
    })

    expect(host.querySelector('[data-testid="save-error"]')).toBeNull()
  })
})
