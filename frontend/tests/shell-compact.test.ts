// @vitest-environment jsdom
/**
 * KAN-1818: the compact (<600px) shell. jsdom has no layout, so this asserts which regions the shell
 * *renders* (the list and the note are separate screens, the back link, the Links sheet);
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
  localStorage.clear()
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

  it('keeps backlinks and history out of sight until the Links button opens the sheet (KAN-1827)', async () => {
    await open('/notes/NOTE-6', 390)

    expect(host.querySelector('.right-rail')).toBeNull()
    expect(host.querySelector('[role="dialog"]')).toBeNull()
    const links = host.querySelector<HTMLButtonElement>('[data-testid="toggle-details"]')!
    expect(links.textContent?.trim()).toBe('Links')
    expect(links.getAttribute('aria-expanded')).toBe('false')
    links.focus()
    links.click()
    flushSync()

    const sheet = host.querySelector<HTMLElement>('[role="dialog"]')!
    expect(sheet.getAttribute('aria-modal')).toBe('true')
    expect(sheet.getAttribute('aria-label')).toBe('Links and history')
    expect(sheet.querySelector('.right-rail')).not.toBeNull()
    expect(links.getAttribute('aria-expanded')).toBe('true')
    // Focus is inside the sheet, on the selected tab, and the page behind does not scroll.
    expect(sheet.contains(document.activeElement)).toBe(true)
    expect(document.activeElement?.getAttribute('role')).toBe('tab')
    expect(document.body.style.overflow).toBe('hidden')

    // Escape closes it, focus goes back to the button, the page scrolls again.
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    flushSync()
    expect(host.querySelector('[role="dialog"]')).toBeNull()
    expect(document.activeElement).toBe(links)
    expect(document.body.style.overflow).toBe('')
  })

  it('closes the sheet from the scrim and from the close button', async () => {
    await open('/notes/NOTE-6', 390)
    const links = host.querySelector<HTMLButtonElement>('[data-testid="toggle-details"]')!

    links.click()
    flushSync()
    host.querySelector<HTMLElement>('[data-testid="sheet-scrim"]')!.click()
    flushSync()
    expect(host.querySelector('[role="dialog"]')).toBeNull()

    links.click()
    flushSync()
    host.querySelector<HTMLElement>('[data-testid="sheet-close"]')!.click()
    flushSync()
    expect(host.querySelector('[role="dialog"]')).toBeNull()
  })

  it('switches tabs with the arrow keys, one tab stop at a time', async () => {
    await open('/notes/NOTE-6', 390)
    host.querySelector<HTMLButtonElement>('[data-testid="toggle-details"]')!.click()
    flushSync()
    const backlinks = host.querySelector<HTMLElement>('[data-testid="rail-tab-backlinks"]')!
    const history = host.querySelector<HTMLElement>('[data-testid="rail-tab-history"]')!
    expect(backlinks.getAttribute('tabindex')).toBe('0')
    expect(history.getAttribute('tabindex')).toBe('-1')

    backlinks.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }))
    flushSync()
    expect(history.getAttribute('aria-selected')).toBe('true')
    expect(document.activeElement).toBe(history)
    expect(host.querySelector('[role="tabpanel"]')!.getAttribute('aria-labelledby')).toBe(history.id)

    history.dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true }))
    flushSync()
    expect(backlinks.getAttribute('aria-selected')).toBe('true')
  })

  it('closes the sheet when navigation happens, also from one note to another', async () => {
    await open('/notes/NOTE-6', 390)
    host.querySelector<HTMLButtonElement>('[data-testid="toggle-details"]')!.click()
    flushSync()
    expect(host.querySelector('[role="dialog"]')).not.toBeNull()

    // Another note, not the list: the surface is still a sheet there, so only the navigation rule
    // (not "there is no note any more") can be what closes it.
    window.history.pushState({}, '', '/notes/NOTE-9')
    window.dispatchEvent(new PopStateEvent('popstate'))
    await vi.waitFor(() => {
      flushSync()
      expect(window.location.pathname).toBe('/notes/NOTE-9')
      expect(host.querySelector('[role="dialog"]')).toBeNull()
    })
  })

  it('opens a saved note in Read: the preview alone, the editor mounted but hidden (KAN-1819)', async () => {
    await open('/notes/NOTE-6', 390)

    expect(host.querySelector('.split')!.getAttribute('data-mode')).toBe('read')
    expect(host.querySelector('[data-testid="preview"]')).not.toBeNull()
    expect(host.querySelector('.pane.reading')).not.toBeNull()
    // Two segments: Split is absent below expanded, not disabled.
    expect(host.querySelector('[data-testid="mode-read"]')).not.toBeNull()
    expect(host.querySelector('[data-testid="mode-edit"]')).not.toBeNull()
    expect(host.querySelector('[data-testid="mode-split"]')).toBeNull()
    expect(host.querySelector('[data-testid="toggle-preview"]')).toBeNull()
  })

  it('on expanded the pane is closed by default and the Links button toggles it (KAN-1827)', async () => {
    await open('/notes/NOTE-6', 1440)

    expect(host.querySelector('.sidebar')).not.toBeNull()
    expect(host.querySelector('main .split')).not.toBeNull()
    expect(host.querySelector('[data-testid="back-to-list"]')).toBeNull()
    expect(host.querySelector('.right-rail')).toBeNull()
    expect(host.querySelector('[role="dialog"]')).toBeNull()
    const links = host.querySelector<HTMLButtonElement>('[data-testid="toggle-details"]')!
    expect(links.getAttribute('aria-expanded')).toBe('false')
    expect(links.getAttribute('aria-controls')).toBe('supporting-pane')

    links.click()
    flushSync()
    expect(host.querySelector('#supporting-pane')).not.toBeNull()
    expect(links.getAttribute('aria-expanded')).toBe('true')
    expect(localStorage.getItem('kaya.supportPane.expanded')).toBe('open')

    links.click()
    flushSync()
    expect(host.querySelector('.right-rail')).toBeNull()
    expect(localStorage.getItem('kaya.supportPane.expanded')).toBe('closed')
  })

  it('on expanded a remembered open pane is open on arrival', async () => {
    localStorage.setItem('kaya.supportPane.expanded', 'open')
    await open('/notes/NOTE-6', 1440)

    expect(host.querySelector('#supporting-pane')).not.toBeNull()
    expect(
      host.querySelector('[data-testid="toggle-details"]')!.getAttribute('aria-expanded'),
    ).toBe('true')
  })
})
