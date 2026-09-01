// @vitest-environment jsdom
/**
 * `Sidebar.svelte` — the folder tree and the flat list, as rendered.
 *
 * `tests/tree.test.ts` owns the grouping; this owns what reaches the screen. The split matters
 * because CLAUDE.md's rule about structural guards cuts both ways: `countNotes` proves the *tree
 * value* holds every note, and it stays green while a component renders only half of it. The
 * on-screen count of note links is a different assertion and it needs its own test.
 */

import { flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import Sidebar from '../src/components/Sidebar.svelte'
import type { Route } from '../src/lib/router'
import type { Note } from '../src/lib/types'
import { box } from './reactive.svelte'

function note(ref: string, path: string, title = `Title ${ref}`): Note {
  return {
    ref,
    id: Number.parseInt(ref.replace(/\D/g, ''), 10),
    title,
    body: '',
    path,
    created_at: '2026-08-09T10:00:00+00:00',
    updated_at: '2026-08-09T10:00:00.123456+00:00',
  }
}

/** The ten seeded notes' shape, plus the awkward paths this card had to decide about. */
const NOTES: Note[] = [
  note('NOTE-1', 'journal/2026/08/weekly-review.md'),
  note('NOTE-2', 'design/deploy/k3d.md'),
  note('NOTE-3', 'scratch.md'),
  note('NOTE-4', '', 'No path at all'),
  note('NOTE-5', '', 'Also no path'),
  note('NOTE-6', 'design/adr.md'),
  note('NOTE-7', 'a/b/c/d/e/f/g/h/i/j/k/l/deep.md'),
]

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

function render(notes: Note[], route: Route = { name: 'home' }, loading = false): HTMLDivElement {
  mounted.push(mount(Sidebar, { target: host, props: { notes, route, loading } }))
  flushSync()
  return host
}

/** Every note link in the sidebar, by the ref its href addresses. */
function links(): string[] {
  return Array.from(host.querySelectorAll<HTMLAnchorElement>('a[href^="/notes/"]')).map((anchor) =>
    anchor.getAttribute('href')!.replace('/notes/', ''),
  )
}

/** The folder row named `name`. Matched on its `.title` span, not on the row's whole text, because
 *  the row also holds the twist glyph. */
function folder(name: string): HTMLButtonElement {
  const found = Array.from(host.querySelectorAll<HTMLButtonElement>('button.folder')).find(
    (button) => button.querySelector('.title')?.textContent?.trim() === name,
  )
  expect(found, `no folder row named ${name}`).not.toBeUndefined()
  return found!
}

function switchTo(view: 'Tree' | 'List'): void {
  const button = Array.from(host.querySelectorAll('button')).find(
    (candidate) => candidate.textContent?.trim() === view,
  )
  expect(button).not.toBeUndefined()
  button!.click()
  flushSync()
}

describe('the note list', () => {
  it('shows every note the API returned, in that order', () => {
    render(NOTES)
    switchTo('List')

    // The list is the corpus, unsorted and ungrouped, which is exactly why it exists beside the tree:
    // "the tree is hiding a note" is one click from being disproved.
    expect(host.querySelector('[data-testid="note-list"]')).not.toBeNull()
    expect(links()).toEqual(NOTES.map((found) => found.ref))
  })

  it('shows an em dash rather than a blank line for a note with no path', () => {
    render([note('NOTE-4', '', 'No path at all')])
    switchTo('List')

    expect(host.textContent).toContain('No path at all')
    expect(host.textContent).toContain('—')
  })

  it('marks the open note as the current page', () => {
    render(NOTES, { name: 'note', ref: 'NOTE-3' })
    switchTo('List')

    const current = host.querySelectorAll('a[aria-current="page"]')
    expect(current).toHaveLength(1)
    expect(current[0].getAttribute('href')).toBe('/notes/NOTE-3')
  })

  it('says so while loading and when there is nothing', () => {
    render([], { name: 'home' }, true)
    expect(host.textContent).toContain('Loading')

    for (const instance of mounted.splice(0)) {
      unmount(instance as never)
    }
    render([])
    expect(host.textContent).toContain('No notes yet')
  })
})

describe('the folder tree', () => {
  it('is the default view', () => {
    render(NOTES)
    expect(host.querySelector('[data-testid="note-tree"]')).not.toBeNull()
    expect(host.querySelector('[data-testid="note-list"]')).toBeNull()
  })

  it('shows every note exactly once, tree rows and unpathed rows together', () => {
    render(NOTES)

    // The rendered twin of `countNotes`. A note reachable in the tree *value* but not on the screen —
    // a collapsed group rendered as nothing, a snippet that forgot a branch — is invisible to
    // `tests/tree.test.ts` and would land as "my note disappeared".
    expect(links().sort()).toEqual(NOTES.map((found) => found.ref).sort())
  })

  it('nests real folders and labels a leaf with its filename', () => {
    render(NOTES)

    // `journal` → `2026` → `08` → the note. Three nested lists, not three sibling rows.
    const branch = folder('journal').closest('li')!
    expect(branch.querySelector('ul li ul li a[href="/notes/NOTE-1"]')).not.toBeNull()
    expect(branch.textContent).toContain('weekly-review.md')
  })

  it('puts a note with no path under a group labelled as the absence of one', () => {
    // ADR 0008: `path` is mutable metadata and identity is the ref, so `path: ''` is a legitimate
    // note — two of the ten seeded ones are. The two failures available were dropping them and
    // inventing a folder named `''`; this asserts against both, and that the group *says* what it is.
    render(NOTES)
    const group = host.querySelector('[data-testid="unpathed"]')

    expect(group).not.toBeNull()
    expect(group!.textContent).toContain('no path')
    expect(group!.textContent).toContain('2')
    expect(group!.querySelectorAll('a[href^="/notes/"]')).toHaveLength(2)
    expect(group!.textContent).toContain('No path at all')
    // The ref stands in for the filename it has none of, rather than a blank or a made-up name.
    expect(group!.textContent).toContain('NOTE-4')

    // And no folder row is an empty or whitespace-only name.
    for (const button of host.querySelectorAll('[data-testid="note-tree"] button')) {
      expect(button.textContent?.replace(/[▸▾]/g, '').trim()).not.toBe('')
    }
  })

  it('omits the unpathed group entirely when every note has a path', () => {
    render([note('NOTE-1', 'a/b.md')])
    expect(host.querySelector('[data-testid="unpathed"]')).toBeNull()
  })

  it('puts a path with no slash at the top level, distinct from having no path', () => {
    render(NOTES)
    const tree = host.querySelector('[data-testid="note-tree"]')!

    // `scratch.md` is a direct child of the tree's root list; the unpathed group is a sibling of the
    // whole tree, so the two states are visibly different places.
    expect(tree.querySelector(':scope > li > a[href="/notes/NOTE-3"]')).not.toBeNull()
    expect(tree.querySelector('a[href="/notes/NOTE-4"]')).toBeNull()
  })

  it('collapses and expands a folder, and starts expanded', () => {
    render(NOTES)
    const design = folder('design')

    // Expanded by default: a tree that starts collapsed makes a loaded sidebar look empty.
    expect(design.getAttribute('aria-expanded')).toBe('true')
    expect(links()).toContain('NOTE-6')

    design.click()
    flushSync()
    expect(design.getAttribute('aria-expanded')).toBe('false')
    expect(links()).not.toContain('NOTE-6')
    // Collapsing one folder hides only its own notes.
    expect(links()).toContain('NOTE-1')

    design.click()
    flushSync()
    expect(links()).toContain('NOTE-6')
  })

  it('stops indenting before a deep path runs off the pane', () => {
    render(NOTES)
    const insets = Array.from(host.querySelectorAll<HTMLElement>('.row')).map((row) =>
      Number.parseFloat(row.style.paddingLeft),
    )

    // `path` is `String(1024)` in migration `0001`, so nesting is unbounded and the indent is not.
    // The clamp is at eight levels: `0.5 + 8 * 0.7`.
    expect(Math.max(...insets)).toBeLessThanOrEqual(0.5 + 8 * 0.7)
    // …but it does indent: a flat tree would be a bug of the opposite kind.
    expect(Math.max(...insets)).toBeGreaterThan(0.5)
  })

  it('keeps two notes that share a path side by side', () => {
    render([note('NOTE-1', 'design/deploy/k3d.md'), note('NOTE-2', 'design/deploy/k3d.md')])
    expect(links().sort()).toEqual(['NOTE-1', 'NOTE-2'])
  })

  it('falls back to the ref when a note has no title', () => {
    // `title` is `String(255)` and the API accepts `''`, so a row must never be a blank line.
    render([note('NOTE-9', 'a/b.md', '')])
    expect(host.querySelector('a[href="/notes/NOTE-9"]')?.textContent).toContain('NOTE-9')
  })
})

describe('"+ New note" (KAN-1040)', () => {
  function renderWithCreate(oncreate: (title: string) => void) {
    mounted.push(
      mount(Sidebar, {
        target: host,
        props: { notes: NOTES, route: { name: 'home' }, loading: false, oncreate },
      }),
    )
    flushSync()
    return host
  }

  function button(testid: string): HTMLButtonElement {
    return host.querySelector<HTMLButtonElement>(`[data-testid="${testid}"]`)!
  }

  function titleInput(): HTMLInputElement {
    return host.querySelector<HTMLInputElement>('[data-testid="create-title-input"]')!
  }

  it('shows the button and no prompt to start with', () => {
    renderWithCreate(vi.fn())

    expect(button('new-note-button')).not.toBeNull()
    expect(host.querySelector('[data-testid="create-form"]')).toBeNull()
  })

  it('opens an inline title prompt in place of the button on click', () => {
    renderWithCreate(vi.fn())

    button('new-note-button').click()
    flushSync()

    expect(host.querySelector('[data-testid="create-form"]')).not.toBeNull()
    expect(host.querySelector('[data-testid="new-note-button"]')).toBeNull()
  })

  it('fires oncreate with the trimmed title on submit, and closes the prompt', () => {
    const oncreate = vi.fn()
    renderWithCreate(oncreate)

    button('new-note-button').click()
    flushSync()
    titleInput().value = '  A fresh note  '
    titleInput().dispatchEvent(new Event('input'))
    host.querySelector('form[data-testid="create-form"]')!.dispatchEvent(
      new Event('submit', { cancelable: true }),
    )
    flushSync()

    expect(oncreate).toHaveBeenCalledTimes(1)
    expect(oncreate).toHaveBeenCalledWith('A fresh note')
    expect(host.querySelector('[data-testid="create-form"]')).toBeNull()
    expect(host.querySelector('[data-testid="new-note-button"]')).not.toBeNull()
  })

  it('refuses a blank title — no call, prompt stays open', () => {
    const oncreate = vi.fn()
    renderWithCreate(oncreate)

    button('new-note-button').click()
    flushSync()
    titleInput().value = '   '
    titleInput().dispatchEvent(new Event('input'))
    host.querySelector('form[data-testid="create-form"]')!.dispatchEvent(
      new Event('submit', { cancelable: true }),
    )
    flushSync()

    expect(oncreate).not.toHaveBeenCalled()
    expect(host.querySelector('[data-testid="create-form"]')).not.toBeNull()
  })

  it('Cancel closes the prompt without calling oncreate', () => {
    const oncreate = vi.fn()
    renderWithCreate(oncreate)

    button('new-note-button').click()
    flushSync()
    titleInput().value = 'Discarded'
    titleInput().dispatchEvent(new Event('input'))
    button('create-cancel').click()
    flushSync()

    expect(oncreate).not.toHaveBeenCalled()
    expect(host.querySelector('[data-testid="create-form"]')).toBeNull()
  })

  it('starts a fresh prompt empty even after a previous title was typed', () => {
    renderWithCreate(vi.fn())

    button('new-note-button').click()
    flushSync()
    titleInput().value = 'Leftover'
    titleInput().dispatchEvent(new Event('input'))
    button('create-cancel').click()
    flushSync()

    button('new-note-button').click()
    flushSync()
    expect(titleInput().value).toBe('')
  })
})

describe('the search box (KAN-559)', () => {
  function renderWithSearch(query: string, onsearch: (term: string) => void) {
    mounted.push(
      mount(Sidebar, {
        target: host,
        props: { notes: NOTES, route: { name: 'home' }, loading: false, query, onsearch },
      }),
    )
    flushSync()
    return host
  }

  function input(): HTMLInputElement {
    return host.querySelector<HTMLInputElement>('[data-testid="search-input"]')!
  }

  function type(term: string): void {
    input().value = term
    input().dispatchEvent(new Event('input'))
    flushSync()
  }

  it('does not fetch on every keystroke — typing changes no committed query', () => {
    // `Sidebar` has no client of its own to fetch with; what this proves is that typing alone
    // leaves `onsearch` uncalled, so App's effect (which depends on the *committed* query) does
    // not refire per character.
    const onsearch = vi.fn()
    renderWithSearch('', onsearch)

    type('reading')
    expect(onsearch).not.toHaveBeenCalled()
  })

  it('submits the trimmed term on submit', () => {
    const onsearch = vi.fn()
    renderWithSearch('', onsearch)

    type('  reading list  ')
    host.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
    flushSync()

    expect(onsearch).toHaveBeenCalledTimes(1)
    expect(onsearch).toHaveBeenCalledWith('reading list')
  })

  it('shows a Clear button only once a search is committed, and clearing sends the empty term', () => {
    // `query` is wired the way `App.svelte` wires it — a reactive prop that `onsearch` writes back
    // into — because the Clear button's *disappearance* is a consequence of the parent reacting to
    // the callback, not of anything `Sidebar` decides on its own.
    const committed = box('reading list')
    const onsearch = vi.fn((term: string) => (committed.value = term))
    mounted.push(
      mount(Sidebar, {
        target: host,
        props: {
          notes: NOTES,
          route: { name: 'home' },
          loading: false,
          get query() {
            return committed.value
          },
          onsearch,
        },
      }),
    )
    flushSync()

    const clear = host.querySelector<HTMLButtonElement>('[data-testid="clear-search"]')
    expect(clear).not.toBeNull()
    clear!.click()
    flushSync()

    expect(onsearch).toHaveBeenCalledTimes(1)
    expect(onsearch).toHaveBeenCalledWith('')
    expect(host.querySelector('[data-testid="clear-search"]')).toBeNull()
  })

  it('has no Clear button when there is no committed search', () => {
    renderWithSearch('', vi.fn())
    expect(host.querySelector('[data-testid="clear-search"]')).toBeNull()
  })

  it('distinguishes "no notes at all" from "no notes match this search"', () => {
    mounted.push(
      mount(Sidebar, {
        target: host,
        props: {
          notes: [],
          route: { name: 'home' },
          loading: false,
          query: 'nothing-matches-this',
          onsearch: vi.fn(),
        },
      }),
    )
    flushSync()

    expect(host.textContent).toContain('No notes match')
    expect(host.textContent).toContain('nothing-matches-this')
    expect(host.textContent).not.toContain('No notes yet.')
  })
})

describe('a search renders flat, and the toggle stops saying otherwise (KAN-962)', () => {
  /**
   * The card's measured case, reproduced: `GET /api/v1/notes?q=reading list` came back
   * `NOTE-9, NOTE-2, NOTE-6` and the tree rendered `NOTE-6, NOTE-9, NOTE-2`.
   *
   * The paths are what make those two sequences differ, and they have to: `NOTE-6` is under a
   * folder, `NOTE-9` is a root-level leaf, and `NOTE-2` has no path at all, so the tree's own rules
   * (folders before leaves, unpathed in a group below the whole tree) put them in an order the
   * server's ranking has no say in. Two of these tie at 0.9910 on that query against the live
   * corpus, which is why KAN-558 has a tie-break at all.
   */
  const MATCHED: Note[] = [
    note('NOTE-9', 'reading.md', 'A reading list'),
    note('NOTE-2', '', 'Reading list'),
    note('NOTE-6', 'journal/2026/08/weekly-review.md', 'Weekly review'),
  ]

  /** What the API returned: `ts_rank DESC, note.id DESC`. */
  const RANKED = ['NOTE-9', 'NOTE-2', 'NOTE-6']

  /** What grouping by `path` produces out of the same three notes. */
  const GROUPED = ['NOTE-6', 'NOTE-9', 'NOTE-2']

  /** Mounted the way `App.svelte` mounts it: `query` is a prop the callback writes back into. */
  function renderLive(initial = ''): { value: string } {
    const committed = box(initial)
    mounted.push(
      mount(Sidebar, {
        target: host,
        props: {
          notes: MATCHED,
          route: { name: 'home' },
          loading: false,
          get query() {
            return committed.value
          },
          onsearch: (term: string) => (committed.value = term),
        },
      }),
    )
    flushSync()
    return committed
  }

  /** Type a term and submit the form, which is the only thing that commits a search (KAN-559). */
  function commit(term: string): void {
    const input = host.querySelector<HTMLInputElement>('[data-testid="search-input"]')!
    input.value = term
    input.dispatchEvent(new Event('input'))
    host.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
    flushSync()
  }

  function clearSearch(): void {
    host.querySelector<HTMLButtonElement>('[data-testid="clear-search"]')!.click()
    flushSync()
  }

  function toggleGroup(): Element | null {
    return host.querySelector('[role="group"][aria-label="Sidebar view"]')
  }

  it('positive control: these three notes really do render in a different order in the tree', () => {
    // Without this, every assertion below could be passing against a corpus whose folder order
    // happens to equal its rank order, and the whole block would be vacuous. Unsearched, in the
    // default view, the tree puts them in folder order — a sequence the API did not choose.
    renderLive()

    expect(host.querySelector('[data-testid="note-tree"]')).not.toBeNull()
    expect(links()).toEqual(GROUPED)
    expect(GROUPED).not.toEqual(RANKED)
  })

  it("keeps the API's relevance order for a search made in the default Tree view", () => {
    // The defect the card measured: TREE is the default, so this was the default rendering of a
    // search, and it discarded `ts_rank DESC, note.id DESC` at the last layer.
    renderLive()
    commit('reading list')

    expect(links()).toEqual(RANKED)
    expect(host.querySelector('[data-testid="note-list"]')).not.toBeNull()
    expect(host.querySelector('[data-testid="note-tree"]')).toBeNull()
  })

  it("keeps the API's relevance order for a search made in List view too", () => {
    renderLive()
    switchTo('List')
    commit('reading list')

    expect(links()).toEqual(RANKED)
  })

  it('shows every matched note exactly once, including the one with no path', () => {
    // The rendered twin of `countNotes`, for the search rendering: a flat list has no unpathed
    // group and no collapsed folder, so a note going missing here would be a different bug from the
    // one `tests/tree.test.ts` guards, and it needs its own assertion.
    renderLive()
    commit('reading list')

    expect(links()).toHaveLength(MATCHED.length)
    expect(host.querySelector('[data-testid="unpathed"]')).toBeNull()
    expect(host.querySelectorAll('button.folder')).toHaveLength(0)
  })

  it('takes the view toggle off the screen while a search is active', () => {
    // Not disabled and not merely ignored. A control reading `Tree` above a flat list is the card's
    // option (a) arriving through the back door — the setting silently overridden, with the toggle
    // still claiming it holds.
    const committed = renderLive()

    expect(toggleGroup()).not.toBeNull()
    commit('reading list')
    expect(committed.value).toBe('reading list')
    expect(toggleGroup()).toBeNull()

    clearSearch()
    expect(toggleGroup()).not.toBeNull()
  })

  it('says why the notes are not grouped, in place of the toggle', () => {
    renderLive()
    expect(host.querySelector('[data-testid="search-ordering"]')).toBeNull()

    commit('reading list')
    const notice = host.querySelector('[data-testid="search-ordering"]')

    expect(notice).not.toBeNull()
    expect(notice!.textContent).toContain('Ordered by relevance')
    expect(notice!.textContent).toContain('not grouped by folder')
    // And it says where the toggle went, because it is the toggle that vanished.
    expect(notice!.textContent).toContain('clear the search')

    clearSearch()
    expect(host.querySelector('[data-testid="search-ordering"]')).toBeNull()
  })

  it('restores the Tree view when the search is cleared', () => {
    // The half that option (a) cannot have: nothing writes the chosen view, so clearing a search
    // puts a person back where they were rather than leaving them in a flat list they never picked.
    renderLive()
    commit('reading list')
    expect(host.querySelector('[data-testid="note-tree"]')).toBeNull()

    clearSearch()

    expect(
      host.querySelector('[data-testid="note-tree"]'),
      'the chosen Tree view did not come back when the search was cleared',
    ).not.toBeNull()
    expect(links()).toEqual(GROUPED)
  })

  it('leaves a chosen List view alone when the search is cleared', () => {
    renderLive()
    switchTo('List')
    commit('reading list')
    clearSearch()

    expect(host.querySelector('[data-testid="note-list"]')).not.toBeNull()
    expect(host.querySelector('[data-testid="note-tree"]')).toBeNull()
  })
})
