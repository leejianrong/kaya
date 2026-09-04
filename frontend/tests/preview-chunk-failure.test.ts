// @vitest-environment jsdom
/**
 * The chunk that does not arrive (KAN-836) — `tests/editor-chunk-failure.test.ts` for the preview.
 *
 * A lazily-loaded module is one more request, so it is one more thing that can fail: offline, a cache
 * miss against a deploy that replaced the asset while this tab was open, a proxy in the way. The bytes
 * moved out of the entry chunk in exchange for that risk, and the price of taking it is saying
 * something when it happens. Unhandled, the symptom is an empty bordered rectangle beside an editor
 * that works — which reads as *this note is empty*, and is the worst answer available, because the one
 * thing a preview is for is telling you what your note says.
 *
 * **Its own file, because the mock has to be hoisted.** `vi.mock` runs before the module graph is
 * built, which is the only way a *dynamic* import made later by a component resolves to it;
 * `vi.doMock` plus `vi.resetModules()` in a shared file gives the re-imported component a second copy
 * of the Svelte runtime and throws `effect_orphan` from inside `$effect` rather than testing anything.
 * The editor's twin records the same finding. So this file never loads the real `lib/markdown` at all.
 */

import { flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import PreviewPane from '../src/components/PreviewPane.svelte'
import type { Note } from '../src/lib/types'

// A factory that throws is a chunk that 404s: the `import()` in the loader effect rejects, which is
// exactly the shape of the real failure.
vi.mock('../src/lib/markdown', () => {
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
  team_id: null,
}

let host: HTMLDivElement
const mounted: unknown[] = []

function mountPreview(): void {
  mounted.push(
    mount(PreviewPane, { target: host, props: { note: NOTE, source: '# A heading\n' } }),
  )
}

async function noticeAppeared(): Promise<HTMLElement> {
  await vi.waitFor(() => {
    flushSync()
    expect(host.querySelector('[data-testid="preview-unavailable"]')).not.toBeNull()
  })
  return host.querySelector<HTMLElement>('[data-testid="preview-unavailable"]')!
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

describe('the markdown chunk failing to load', () => {
  it('says so in words, instead of leaving an empty box', async () => {
    mountPreview()

    expect((await noticeAppeared()).textContent).toContain('could not be loaded')
  })

  it('keeps the notice out of the element `replaceChildren` owns', async () => {
    // The same rule as `EditorPane`'s notice and PLAN §S9's container: the element whose children
    // belong to the renderer cannot hold the sentence explaining why the renderer never ran. This is
    // the one state in which putting it in there looks like the obvious thing to do.
    mountPreview()
    const notice = await noticeAppeared()
    const element = host.querySelector('[data-testid="preview"]')!

    expect(element.childNodes).toHaveLength(0)
    expect(element.contains(notice)).toBe(false)
  })

  it('does not take the editor down with it', async () => {
    // The two chunks fail independently, which is most of the reason this is a separate notice rather
    // than a shared one: a preview that cannot load must not claim the editor is broken, because the
    // editor still saves. `EditorPane`'s own notice is `[data-testid="editor-unavailable"]`.
    mountPreview()
    await noticeAppeared()

    expect(host.querySelector('[data-testid="editor-unavailable"]')).toBeNull()
  })
})
