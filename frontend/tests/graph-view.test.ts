// @vitest-environment jsdom
/**
 * `GraphView.svelte` as rendered — KAN-1050's read-only graph view.
 *
 * Same harness as `tests/backlinks-panel.test.ts`: Svelte's own `mount`/`flushSync`, a faked
 * `fetch`, and `vi.waitFor` for every settle, because the component fetches on mount and
 * `mount()` + `flushSync()` alone does not leave an answer on screen.
 */

import { flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import GraphView from '../src/components/GraphView.svelte'
import * as auth from '../src/lib/auth'
import type { GraphEdge, GraphNode } from '../src/lib/types'
import { FAKE_TOKEN } from './token'

function node(ref: string, title = `Title ${ref}`): GraphNode {
  return { ref, title, path: '' }
}

let host: HTMLDivElement
const mounted: unknown[] = []
const realFetch = globalThis.fetch

let asked: string[]
let answer: () => Promise<Response>

function ok(nodes: GraphNode[], edges: GraphEdge[] = []): () => Promise<Response> {
  return async () =>
    new Response(JSON.stringify({ nodes, edges }), {
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
}

function render(): Handles {
  const expired: string[] = []
  mounted.push(
    mount(GraphView, {
      target: host,
      props: { onexpired: (reason: string) => expired.push(reason) },
    }),
  )
  flushSync()
  return { expired }
}

function section(): HTMLElement {
  const found = host.querySelector<HTMLElement>('section.graph')
  expect(found, 'no graph section in the host').not.toBeNull()
  return found!
}

async function settledOn(testid: string): Promise<HTMLElement> {
  let element: HTMLElement | null = null
  await vi.waitFor(() => {
    flushSync()
    element = host.querySelector<HTMLElement>(`[data-testid="${testid}"]`)
    expect(element, `never settled on ${testid}; section said ${JSON.stringify(section().textContent)}`)
      .not.toBeNull()
  })
  return element!
}

/** Every node anchor's ref, by the href it addresses. */
function nodeRefs(): string[] {
  return Array.from(host.querySelectorAll<HTMLAnchorElement>('a[href^="/notes/"]')).map((anchor) =>
    anchor.getAttribute('href')!.replace('/notes/', ''),
  )
}

describe('the states this view can be in', () => {
  it('says loading while the request is in flight, and only then', async () => {
    let release: (value: Response) => void = () => {}
    answer = () => new Promise<Response>((resolve) => (release = resolve))

    render()
    const loading = await settledOn('graph-loading')
    expect(loading.textContent).toContain('Loading')

    release(
      new Response(JSON.stringify({ nodes: [], edges: [] }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    await settledOn('graph-empty')
    expect(host.querySelector('[data-testid="graph-loading"]')).toBeNull()
  })

  it('shows an empty state for a caller with no notes yet', async () => {
    answer = ok([])
    render()
    const empty = await settledOn('graph-empty')

    expect(empty.textContent).toContain('No notes yet')
    expect(host.querySelector('[data-testid="graph-canvas"]')).toBeNull()
    expect(host.querySelector('[data-testid="graph-error"]')).toBeNull()
  })

  it('says the request failed, using the API’s own message', async () => {
    answer = refused(503, 'upstream_unavailable', 'The database is unreachable right now.')
    render()
    const failed = await settledOn('graph-error')

    expect(failed.textContent).toContain('Could not load the graph')
    expect(failed.textContent).toContain('The database is unreachable right now.')
    expect(host.querySelector('[data-testid="graph-canvas"]')).toBeNull()
    expect(host.querySelector('[data-testid="graph-empty"]')).toBeNull()
  })

  it('renders every node and every edge the API returned, with a count over the nodes', async () => {
    answer = ok(
      [node('NOTE-1', 'Reading List'), node('NOTE-2', 'Source')],
      [{ source: 'NOTE-2', target: 'NOTE-1' }],
    )
    render()
    await settledOn('graph-canvas')

    expect(nodeRefs().sort()).toEqual(['NOTE-1', 'NOTE-2'])
    expect(host.querySelector('[data-testid="graph-count"]')!.textContent).toBe('2')
    expect(section().textContent).toContain('Reading List')
    expect(section().textContent).toContain('Source')

    const lines = host.querySelectorAll('line.edge')
    expect(lines).toHaveLength(1)
  })

  it('renders a node with no edges too, and no lines at all when there are none', async () => {
    answer = ok([node('NOTE-1')], [])
    render()
    await settledOn('graph-canvas')

    expect(nodeRefs()).toEqual(['NOTE-1'])
    expect(host.querySelectorAll('line.edge')).toHaveLength(0)
  })
})

describe('a 401 leaves this component rather than being absorbed by it', () => {
  it('hands the refusal to onexpired and renders no local error', async () => {
    answer = refused(401, 'invalid_token', 'That token is not valid.')
    const view = render()

    await vi.waitFor(() => {
      flushSync()
      expect(view.expired).toEqual(['That token is not valid.'])
    })
    expect(host.querySelector('[data-testid="graph-error"]')).toBeNull()
  })
})

describe('clicking a node is a route change and nothing more', () => {
  it('addresses the note by its ref, through the app’s router', async () => {
    answer = ok([node('NOTE-7', 'Target Note')])
    render()
    await settledOn('graph-canvas')

    const anchor = host.querySelector<HTMLAnchorElement>('a[href="/notes/NOTE-7"]')!
    expect(anchor.getAttribute('href')).toBe('/notes/NOTE-7')

    const before = globalThis.location.pathname
    // `SVGAElement` has no `.click()` in jsdom, unlike an HTML anchor — dispatch the same event
    // `interceptClick` actually reads (`button`, the modifier keys, `defaultPrevented`).
    anchor.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 }))
    flushSync()
    expect(globalThis.location.pathname).toBe('/notes/NOTE-7')
    expect(globalThis.location.pathname).not.toBe(before)
  })
})

/**
 * A node's title is prose from a note somebody else may have written, rendered with no markdown
 * renderer in front of it — the same class of surface `BacklinksPanel`'s hostile-title suite
 * covers, one component over.
 */
describe('a hostile title is text, all of it', () => {
  const HOSTILE =
    '<script>globalThis.KAYA_XSS = true</script>' +
    '<img src=x onerror="globalThis.KAYA_XSS = true">'
  const CREATED = 'script, img'

  it('creates no element from it, and holds every byte in one text node', async () => {
    ;(globalThis as Record<string, unknown>).KAYA_XSS = false
    answer = ok([node('NOTE-9', HOSTILE)])
    render()
    await settledOn('graph-canvas')

    expect(section().querySelectorAll(CREATED)).toHaveLength(0)

    const label = host.querySelector<SVGTextElement>('a[href="/notes/NOTE-9"] text.node-label')!
    expect(Array.from(label.childNodes).map((child) => child.nodeType)).toEqual([Node.TEXT_NODE])
    expect(label.textContent).toBe(HOSTILE)
    expect(section().innerHTML).toContain('&lt;script&gt;')
    expect(section().innerHTML).not.toContain('<script>')
    expect((globalThis as Record<string, unknown>).KAYA_XSS).not.toBe(true)
  })
})
