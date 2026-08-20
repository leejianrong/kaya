// @vitest-environment jsdom
/**
 * `BacklinksPanel.svelte` as rendered — the behavioural twin of `tests/backlinks.test.ts`.
 *
 * The split is CLAUDE.md's rule about structural guards, met deliberately rather than met by
 * accident: `panelState` proves the five states are five *values*, and every one of those assertions
 * stays green while this component renders `failed` and `empty` with the same sentence, or renders a
 * count over rows it is not showing. So the wording, the request count and the escaping are asserted
 * here, over the DOM, and the precedence is asserted there, over the value.
 *
 * **Async, so every wait is a poll.** The panel fetches, so `mount()` + `flushSync()` does not leave
 * an answer in the rail — the same situation `tests/editor-arrival.ts` records for KAN-767's chunk,
 * and the same resolution: `vi.waitFor` with a `flushSync` inside it, never a counted number of
 * microtask ticks. A tick count passes in whichever position the file happens to run in and fails
 * when a file is reordered.
 *
 * No testing library — Svelte's own `mount`/`unmount`/`flushSync`, as everywhere else in this suite.
 */

import { flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import BacklinksPanel from '../src/components/BacklinksPanel.svelte'
import * as auth from '../src/lib/auth'
import type { Note } from '../src/lib/types'
import { box } from './reactive.svelte'
import { FAKE_TOKEN } from './token'

function note(ref: string, overrides: Partial<Note> = {}): Note {
  return {
    ref,
    id: Number.parseInt(ref.replace(/\D/g, ''), 10),
    title: `Title ${ref}`,
    body: '',
    path: 'design/adr.md',
    created_at: '2026-08-09T10:00:00+00:00',
    updated_at: '2026-08-09T10:00:00.123456+00:00',
    ...overrides,
  }
}

let host: HTMLDivElement
const mounted: unknown[] = []
const realFetch = globalThis.fetch

/** Every URL the panel asked for, in order. The request *count* is half of what this file asserts. */
let asked: string[]
/** What the next response should be, as a function so a test can change it mid-flight. */
let answer: () => Promise<Response>

function ok(notes: Note[]): () => Promise<Response> {
  return async () =>
    new Response(JSON.stringify({ notes }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
}

function refused(status: number, code: string, message: string): () => Promise<Response> {
  return async () =>
    new Response(JSON.stringify({ error: { code, message } }), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })
}

beforeEach(() => {
  host = document.createElement('div')
  document.body.append(host)
  auth.setToken(FAKE_TOKEN)
  asked = []
  answer = ok([])
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    asked.push(String(input))
    return answer()
  }) as unknown as typeof fetch
})

afterEach(() => {
  for (const instance of mounted.splice(0)) {
    unmount(instance as never)
  }
  host.remove()
  auth.clearToken()
  globalThis.fetch = realFetch
})

interface Handles {
  expired: string[]
  open: (next: Note | null) => void
}

/** Mount the panel over a reactive `note` prop, so a test can hand it a new object or a new ref. */
function render(initial: Note | null): Handles {
  const opened = box<Note | null>(initial)
  const expired: string[] = []
  mounted.push(
    mount(BacklinksPanel, {
      target: host,
      props: {
        get note() {
          return opened.value
        },
        onexpired: (reason: string) => expired.push(reason),
      },
    }),
  )
  flushSync()
  return {
    expired,
    open: (next) => {
      opened.value = next
      flushSync()
    },
  }
}

/** The rail element itself. Named by `data-testid`, never by a class fragment. */
function rail(): HTMLElement {
  const found = host.querySelector<HTMLElement>('aside.rail')
  expect(found, 'no backlinks rail in the host').not.toBeNull()
  return found!
}

/** Resolve once the rail has settled onto the state `testid` names. */
async function settledOn(testid: string): Promise<HTMLElement> {
  let element: HTMLElement | null = null
  await vi.waitFor(() => {
    flushSync()
    element = host.querySelector<HTMLElement>(`[data-testid="${testid}"]`)
    expect(element, `never settled on ${testid}; rail said ${JSON.stringify(rail().textContent)}`)
      .not.toBeNull()
  })
  return element!
}

/** Every backlink row's ref, by the href it addresses. */
function rows(): string[] {
  return Array.from(host.querySelectorAll<HTMLAnchorElement>('a[href^="/notes/"]')).map((anchor) =>
    anchor.getAttribute('href')!.replace('/notes/', ''),
  )
}

describe('the four states a note can be in, and they read differently', () => {
  it('says loading while the request is in flight, and only then', async () => {
    // Held open, so "loading" is a state this test can stand still inside rather than a frame it
    // has to catch. Without the pending promise the panel settles before any assertion runs.
    let release: (value: Response) => void = () => {}
    answer = () => new Promise<Response>((resolve) => (release = resolve))

    render(note('NOTE-1'))
    const loading = await settledOn('backlinks-loading')
    expect(loading.textContent).toContain('Loading')
    // Refresh is disabled while a request is in flight, so a click cannot queue a second one.
    expect(host.querySelector<HTMLButtonElement>('[data-testid="backlinks-refresh"]')!.disabled).toBe(
      true,
    )

    release(
      new Response(JSON.stringify({ notes: [] }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    await settledOn('backlinks-empty')
    expect(host.querySelector('[data-testid="backlinks-loading"]')).toBeNull()
  })

  it('names the note in the zero state, and does not say anything about a failure', async () => {
    render(note('NOTE-3'))
    const empty = await settledOn('backlinks-empty')

    expect(empty.textContent).toContain('NOTE-3')
    expect(empty.textContent).toContain('Nothing links to')
    // The mutation this is written for: an `{:else}` collapsing `failed` into `empty`. The zero
    // state must not carry the words a failure carries, in either direction.
    expect(rail().textContent).not.toContain('Could not load')
    expect(host.querySelector('[data-testid="backlinks-error"]')).toBeNull()
  })

  it('says the request failed, in words the zero state does not use, and offers a way back', async () => {
    answer = refused(503, 'upstream_unavailable', 'The board is unreachable right now.')
    render(note('NOTE-3'))
    const failed = await settledOn('backlinks-error')

    expect(failed.textContent).toContain('Could not load backlinks for NOTE-3')
    // The API's own prose, verbatim: it is written for a person and no refusal echoes a header.
    expect(failed.textContent).toContain('The board is unreachable right now.')
    // And it is emphatically not the zero state. This is the assertion that fires when the two
    // states are given one arm — `panelState`'s union stays correct while the markup lies.
    expect(rail().textContent).not.toContain('Nothing links to')
    expect(host.querySelector('[data-testid="backlinks-empty"]')).toBeNull()
    // Refresh is enabled, because a failure with no recovery is a dead panel.
    expect(host.querySelector<HTMLButtonElement>('[data-testid="backlinks-refresh"]')!.disabled).toBe(
      false,
    )
  })

  it('lists the rows the API returned, in that order, with a count over them', async () => {
    answer = ok([note('NOTE-7'), note('NOTE-2', { path: '' })])
    render(note('NOTE-1'))
    await settledOn('backlinks')

    // `updated_at DESC, id DESC` is the server's order (`notes_linking_to`); nothing here re-sorts.
    expect(rows()).toEqual(['NOTE-7', 'NOTE-2'])
    expect(host.querySelector('[data-testid="backlinks-count"]')!.textContent).toBe('2')
    expect(rail().textContent).toContain('Title NOTE-7')
    // `path: ''` is legal (ADR 0008) and gets an em dash rather than a blank line.
    expect(rail().textContent).toContain('—')
  })

  it('says there is nothing open, rather than answering about a note it has not got', async () => {
    // Distinct from `empty` on purpose: "no note" is not an answer about a note. This is the
    // in-flight window between a note route and `getNote` resolving, and a panel saying "nothing
    // links to this note" there would be a claim about a note nobody has confirmed exists.
    render(null)
    const closed = await settledOn('backlinks-closed')

    expect(closed.textContent).toContain('Open a note')
    expect(rail().textContent).not.toContain('Nothing links to')
    expect(asked).toEqual([])
  })
})

describe('the identity guard, which is what stops a request per keystroke', () => {
  it('asks once for a note, and not again when the prop object is replaced', async () => {
    const panel = render(note('NOTE-1'))
    await settledOn('backlinks-empty')
    expect(asked).toEqual(['/api/v1/notes/NOTE-1/backlinks'])

    // Exactly the parent the guard is written for: a new object per update, same note. Reading the
    // prop in the effect registers *all* of it, so this re-runs the effect — and must not refetch.
    for (const body of ['a', 'ab', 'abc']) {
      panel.open(note('NOTE-1', { body }))
    }
    // A poll, not a tick count: if the guard were broken the requests would arrive asynchronously,
    // so a synchronous assertion right here would pass on the defect.
    await vi.waitFor(() => {
      flushSync()
      expect(asked).toEqual(['/api/v1/notes/NOTE-1/backlinks'])
    })
  })

  it('asks again, exactly once, when the ref moves', async () => {
    answer = ok([note('NOTE-9')])
    const panel = render(note('NOTE-1'))
    await settledOn('backlinks')

    panel.open(note('NOTE-2'))
    await vi.waitFor(() => {
      flushSync()
      expect(asked).toEqual([
        '/api/v1/notes/NOTE-1/backlinks',
        '/api/v1/notes/NOTE-2/backlinks',
      ])
    })
  })

  it('clears the previous note’s rows the moment the ref moves, rather than after the round trip', async () => {
    answer = ok([note('NOTE-9', { title: 'Points at the first note' })])
    const panel = render(note('NOTE-1'))
    await settledOn('backlinks')
    expect(rail().textContent).toContain('Points at the first note')

    // Held open so the window is standable-in. Rows belonging to NOTE-1 sitting under a heading
    // that is now about NOTE-2 is the bug the `subject` rune exists for, and it is invisible in a
    // suite that only ever looks at settled states.
    answer = () => new Promise<Response>(() => {})
    panel.open(note('NOTE-2'))
    await settledOn('backlinks-loading')
    expect(rail().textContent).not.toContain('Points at the first note')
    expect(rows()).toEqual([])
  })

  it('does not let a superseded response land on the note that replaced it', async () => {
    // Two requests genuinely in flight across a fast navigation. `AbortController` does not order
    // their rejections, so the panel keys staleness on the controller's identity.
    let releaseFirst: (value: Response) => void = () => {}
    answer = () => new Promise<Response>((resolve) => (releaseFirst = resolve))
    const panel = render(note('NOTE-1'))
    await settledOn('backlinks-loading')

    answer = ok([note('NOTE-4', { title: 'Points at the second note' })])
    panel.open(note('NOTE-2'))
    await settledOn('backlinks')
    expect(rail().textContent).toContain('Points at the second note')

    // The first note's answer arrives late. It must go nowhere.
    releaseFirst(
      new Response(JSON.stringify({ notes: [note('NOTE-8', { title: 'STALE ANSWER' })] }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    await vi.waitFor(() => {
      flushSync()
      expect(rail().textContent).toContain('Points at the second note')
    })
    expect(rail().textContent).not.toContain('STALE ANSWER')
  })

  it('goes back to the closed state when the note goes away, and asks nothing', async () => {
    const panel = render(note('NOTE-1'))
    await settledOn('backlinks-empty')

    panel.open(null)
    await settledOn('backlinks-closed')
    expect(asked).toEqual(['/api/v1/notes/NOTE-1/backlinks'])
  })
})

describe('refresh, which is the only way this panel re-reads', () => {
  it('asks again for the note already on screen', async () => {
    // There is deliberately no automatic refresh: inbound links change when *another* note's body
    // changes, in another tab or an agent's `kaya note edit`, and this app is not told. A panel
    // refetching on save would be right about one of the ways it goes stale and silently wrong
    // about the rest.
    answer = ok([])
    const panel = render(note('NOTE-1'))
    await settledOn('backlinks-empty')

    answer = ok([note('NOTE-6', { title: 'Newly linked' })])
    host.querySelector<HTMLButtonElement>('[data-testid="backlinks-refresh"]')!.click()
    await settledOn('backlinks')

    expect(asked).toEqual([
      '/api/v1/notes/NOTE-1/backlinks',
      '/api/v1/notes/NOTE-1/backlinks',
    ])
    expect(rail().textContent).toContain('Newly linked')
    expect(panel.expired).toEqual([])
  })

  it('recovers out of a failure', async () => {
    answer = refused(503, 'upstream_unavailable', 'unreachable')
    render(note('NOTE-1'))
    await settledOn('backlinks-error')

    answer = ok([note('NOTE-6')])
    host.querySelector<HTMLButtonElement>('[data-testid="backlinks-refresh"]')!.click()
    await settledOn('backlinks')
    expect(host.querySelector('[data-testid="backlinks-error"]')).toBeNull()
  })
})

describe('a 401 leaves this component rather than being absorbed by it', () => {
  it('hands the refusal to `onexpired` and renders no local error', async () => {
    // `App.svelte` owns the credential lifecycle, because acquiring one changes which region renders
    // and losing one is discovered by a request the landing state never made. Keyed on the status,
    // never on the code (`kaya-cli/failures.py`): the backend's code vocabulary grows without this
    // client's knowledge.
    answer = refused(401, 'invalid_token', 'That token is not valid.')
    const panel = render(note('NOTE-1'))

    await vi.waitFor(() => {
      flushSync()
      expect(panel.expired).toEqual(['That token is not valid.'])
    })
    // Not shown here as well: the app is on its way to the landing state, and a rail complaining
    // about a credential it does not own would be a second, worse explanation of the same event.
    expect(host.querySelector('[data-testid="backlinks-error"]')).toBeNull()
  })

  it('reports a missing credential the same way, without a request', async () => {
    // `MissingCredential` is a `401` raised before the fetch, so it has to travel the same road.
    auth.clearToken()
    const panel = render(note('NOTE-1'))

    await vi.waitFor(() => {
      flushSync()
      expect(panel.expired).toHaveLength(1)
    })
    expect(asked).toEqual([])
  })

  it('says nothing about the credential itself, in any state', async () => {
    // `tests/auth.test.ts` sweeps the seam and stays green while a component renders the token into
    // a `<p>` — the trap KAN-555 met. So the sweep runs over what is on screen. Four characters,
    // for `kaya config show`'s reason: a leak of exactly pandan's four walked through a six-window.
    answer = ok([note('NOTE-2')])
    render(note('NOTE-1'))
    await settledOn('backlinks')

    for (let start = 0; start + 4 <= FAKE_TOKEN.length; start += 1) {
      expect(rail().innerHTML).not.toContain(FAKE_TOKEN.slice(start, start + 4))
    }
    for (const anchor of host.querySelectorAll('a')) {
      expect(anchor.getAttribute('href')).not.toContain('kanban')
    }
    for (const url of asked) {
      expect(url).not.toContain('kanban')
    }
  })
})

describe('a click on a backlink is a route change and nothing more', () => {
  it('addresses the note by its ref, through the app’s router', async () => {
    answer = ok([note('NOTE-7')])
    render(note('NOTE-1'))
    await settledOn('backlinks')

    const anchor = host.querySelector<HTMLAnchorElement>('a[href="/notes/NOTE-7"]')!
    // The href is real, so ⌘-click and "open in new tab" reach `spa.py`'s history fallback and load
    // a working page — `interceptClick` returns early for a modified click for exactly that reason.
    expect(anchor.getAttribute('href')).toBe('/notes/NOTE-7')

    const before = globalThis.location.pathname
    anchor.click()
    flushSync()
    expect(globalThis.location.pathname).toBe('/notes/NOTE-7')
    expect(globalThis.location.pathname).not.toBe(before)
  })
})

/**
 * A backlink's title is prose somebody else wrote, in a different note, reaching this rail with no
 * renderer in front of it. That makes this the app's second user-content surface after the preview,
 * and the one an XSS probe would not think to look at.
 */
describe('a hostile title is text, all of it', () => {
  const HOSTILE =
    '<script>globalThis.KAYA_XSS = true</script>' +
    '<img src=x onerror="globalThis.KAYA_XSS = true">' +
    '[click](javascript:globalThis.KAYA_XSS=true)'

  /** Anything the payload would create if a single byte of it were parsed as markup. */
  const CREATED = 'script, img, a[href^="javascript"]'

  it('proves the probe first: the same payload as markup really does create those elements', () => {
    // The positive control, and the reason it is here rather than assumed. The near-miss on record
    // in this repo is an XSS probe scoped to `[class*="preview"]`, which matched the Preview
    // *button* and asserted nothing. A selector has to be shown matching a known-bad input before
    // its emptiness means anything.
    const control = document.createElement('div')
    control.innerHTML = HOSTILE

    expect(control.querySelectorAll(CREATED).length).toBeGreaterThan(0)
    expect(control.querySelector('script')).not.toBeNull()
    expect(control.querySelector('img')).not.toBeNull()
  })

  it('creates no element from it, and holds every byte in one text node', async () => {
    ;(globalThis as Record<string, unknown>).KAYA_XSS = false
    answer = ok([note('NOTE-9', { title: HOSTILE })])
    render(note('NOTE-1'))
    await settledOn('backlinks')

    // The load-bearing assertion, and it is structural rather than behavioural: jsdom does not run
    // an injected `<script>` and does not load images, so "no handler fired" is a weaker claim here
    // than "no element exists to fire one". Both are asserted; this is the one that would still be
    // true in a real browser.
    expect(rail().querySelectorAll(CREATED)).toHaveLength(0)

    const title = host.querySelector<HTMLElement>('a[href="/notes/NOTE-9"] .title')!
    expect(Array.from(title.childNodes).map((child) => child.nodeType)).toEqual([Node.TEXT_NODE])
    // Byte for byte, so nothing was stripped either — a refusal a reader can see, the same call
    // `lib/markdown.ts` makes for raw HTML and for a refused link.
    expect(title.textContent).toBe(HOSTILE)
    // The serialized HTML carries the escaped form, which is what a devtools copy and a bug report
    // both hold.
    expect(rail().innerHTML).toContain('&lt;script&gt;')
    expect(rail().innerHTML).not.toContain('<script>')

    expect((globalThis as Record<string, unknown>).KAYA_XSS).not.toBe(true)
  })

  it('is not made clickable by anything in the title, only by the ref', async () => {
    answer = ok([note('NOTE-9', { title: HOSTILE })])
    render(note('NOTE-1'))
    await settledOn('backlinks')

    // Every `href` in the rail is a route this app built out of a ref. Nothing from the payload
    // reaches an attribute value at all, which is the property the preview's protocol allow-list
    // has to work for and this component gets for free by never putting source in an attribute.
    for (const anchor of host.querySelectorAll('a')) {
      expect(anchor.getAttribute('href')).toBe('/notes/NOTE-9')
    }
  })
})
