// @vitest-environment jsdom
/**
 * KAN-1818: the compact (<600px) shell. jsdom has no layout, so this asserts which regions the shell
 * *renders* (the list and the note are separate screens, the back link, the on-demand rail);
 * `e2e/mobile.spec.ts` proves the widths in a real browser.
 */

import { flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from '../src/App.svelte'
import * as auth from '../src/lib/auth'
import { FAKE_TOKEN } from './token'

const NOTE = {
  ref: 'NOTE-6',
  id: 6,
  title: 'Weekly review',
  body: 'hello',
  path: 'journal/review.md',
  created_at: '2026-08-09T10:00:00+00:00',
  updated_at: '2026-08-09T10:00:00.123456+00:00',
  team_id: null,
}

let host: HTMLDivElement
let instance: unknown
const realFetch = globalThis.fetch
const realPathname = window.location.pathname

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function stubMatchMedia(width: number): void {
  vi.stubGlobal('matchMedia', (query: string) => {
    const min = Number(/min-width: (\d+)px/.exec(query)![1])
    return { matches: width >= min, addEventListener() {}, removeEventListener() {} }
  })
}

async function open(path: string, width: number): Promise<void> {
  stubMatchMedia(width)
  window.history.pushState({}, '', path)
  auth.setToken(FAKE_TOKEN)
  instance = mount(App, { target: host, props: {} })
  flushSync()
  await vi.waitFor(() => {
    flushSync()
    expect(host.querySelector('[data-testid="nav-column"]')).not.toBeNull()
  })
}

beforeEach(() => {
  host = document.createElement('div')
  document.body.append(host)
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url === '/api/v1/notes') {
      return json(200, { notes: [NOTE] })
    }
    if (url === '/api/v1/notes/NOTE-6') {
      return json(200, NOTE)
    }
    if (url.startsWith('/api/v1/notes/NOTE-6/')) {
      return json(200, { backlinks: [], versions: [], links: [] })
    }
    return json(404, { error: { code: 'not_found', message: `nothing fake at ${url}` } })
  }) as unknown as typeof fetch
})

afterEach(() => {
  unmount(instance as never)
  host.remove()
  auth.clearToken()
  vi.unstubAllGlobals()
  globalThis.fetch = realFetch
  window.history.pushState({}, '', realPathname)
})

describe('the compact shell', () => {
  it('shows the note list alone on /, with search, New note and the nav bar', async () => {
    await open('/', 390)

    expect(host.querySelector('.sidebar')).not.toBeNull()
    expect(host.querySelector('main')).toBeNull()
    expect(host.querySelector('[data-testid="new-note-button"]')).not.toBeNull()
    expect(host.querySelector('[data-testid="search-input"]')).not.toBeNull()
    expect(host.querySelector('.tagline')).not.toBeNull() // hidden by CSS, not removed
    const labels = [...host.querySelectorAll('[data-testid="nav-column"] a')].map((a) =>
      a.textContent?.trim(),
    )
    expect(labels).toEqual(['Notes', 'Graph', 'Settings'])
  })

  it('shows the note alone, with a back link to the list, when a note is open', async () => {
    await open('/notes/NOTE-6', 390)

    expect(host.querySelector('.sidebar')).toBeNull()
    expect(host.querySelector('main .split')).not.toBeNull()
    const back = host.querySelector<HTMLAnchorElement>('[data-testid="back-to-list"]')!
    expect(back.getAttribute('href')).toBe('/')
    // Real navigation: following it changes the URL, so the browser's back button agrees.
    back.click()
    await vi.waitFor(() => {
      flushSync()
      expect(window.location.pathname).toBe('/')
      expect(host.querySelector('.sidebar')).not.toBeNull()
    })
  })

  it('keeps the backlinks/history rail closed until asked for', async () => {
    await open('/notes/NOTE-6', 390)

    expect(host.querySelector('.right-rail')).toBeNull()
    host.querySelector<HTMLButtonElement>('[data-testid="toggle-details"]')!.click()
    flushSync()
    expect(host.querySelector('.right-rail')).not.toBeNull()
  })

  it('starts with the preview off, so the editor owns the screen', async () => {
    await open('/notes/NOTE-6', 390)

    expect(host.querySelector('.split.solo')).not.toBeNull()
  })

  it('does not apply on expanded: list, note and rail all render together', async () => {
    await open('/notes/NOTE-6', 1440)

    expect(host.querySelector('.sidebar')).not.toBeNull()
    expect(host.querySelector('main .split')).not.toBeNull()
    expect(host.querySelector('.right-rail')).not.toBeNull()
    expect(host.querySelector('[data-testid="back-to-list"]')).toBeNull()
    expect(host.querySelector('[data-testid="toggle-details"]')).toBeNull()
  })
})
