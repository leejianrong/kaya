// @vitest-environment jsdom
/**
 * `Settings.svelte` (KAN-1815) end to end against the ambient `fetch`, and its nav entry — the
 * same shape as `pandan-connect.test.ts`.
 */

import { flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import NavColumn from '../src/components/NavColumn.svelte'
import Settings from '../src/components/Settings.svelte'
import * as auth from '../src/lib/auth'
import { formatOnSave, resetPreferencesCache } from '../src/lib/preferences'
import { FAKE_TOKEN } from './token'

let host: HTMLDivElement
const mounted: unknown[] = []
const realFetch = globalThis.fetch

let stored: boolean
let calls: Array<{ url: string; method: string; body: unknown }>
let failWrites: boolean

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

beforeEach(() => {
  host = document.createElement('div')
  document.body.append(host)
  auth.setToken(FAKE_TOKEN)
  resetPreferencesCache()
  stored = true
  failWrites = false
  calls = []

  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    const body = init?.body ? JSON.parse(init.body as string) : undefined
    calls.push({ url, method, body })

    if (url === '/api/v1/preferences' && method === 'GET') {
      return jsonResponse(200, { format_on_save: stored })
    }
    if (url === '/api/v1/preferences' && method === 'PATCH') {
      if (failWrites) {
        return jsonResponse(500, { error: { code: 'boom', message: 'could not store that' } })
      }
      stored = (body as { format_on_save: boolean }).format_on_save
      return jsonResponse(200, { format_on_save: stored })
    }
    return jsonResponse(404, { error: { code: 'not_found', message: `nothing fake at ${url}` } })
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

async function open(): Promise<HTMLInputElement> {
  mounted.push(mount(Settings, { target: host }))
  flushSync()
  await vi.waitFor(() =>
    expect(host.querySelector('[data-testid="format-on-save"]')).not.toBeNull(),
  )
  return host.querySelector<HTMLInputElement>('[data-testid="format-on-save"]')!
}

describe('the Settings page', () => {
  it('shows "Format on save" ON for an account that never chose', async () => {
    const toggle = await open()

    expect(toggle.checked).toBe(true)
    expect(host.textContent).toContain('Format on save')
  })

  it('says it governs browser saves only, and that CLI and MCP never format implicitly', async () => {
    await open()

    const help = host.querySelector('[data-testid="format-on-save-help"]')!.textContent!
    expect(help).toContain('browser')
    expect(help).toContain('CLI and MCP never format implicitly')
  })

  it("reflects the account's stored OFF choice after a reload", async () => {
    stored = false

    const toggle = await open()

    expect(toggle.checked).toBe(false)
  })

  it('writes the choice to the server and lets the next save see it without a refetch', async () => {
    const toggle = await open()

    toggle.click()
    await vi.waitFor(() => expect(stored).toBe(false))

    const writes = calls.filter((c) => c.method === 'PATCH')
    expect(writes).toEqual([{ url: '/api/v1/preferences', method: 'PATCH', body: { format_on_save: false } }])
    const readsBefore = calls.filter((c) => c.method === 'GET').length
    await vi.waitFor(async () => expect(await formatOnSave()).toBe(false))
    expect(calls.filter((c) => c.method === 'GET').length).toBe(readsBefore)
  })

  it('puts the toggle back and says why when the write fails', async () => {
    failWrites = true
    const toggle = await open()

    toggle.click()
    await vi.waitFor(() => expect(host.querySelector('[data-testid="problem"]')).not.toBeNull())

    expect(host.querySelector('[data-testid="problem"]')!.textContent).toContain(
      'could not store that',
    )
    expect(host.querySelector<HTMLInputElement>('[data-testid="format-on-save"]')!.checked).toBe(
      true,
    )
    expect(await formatOnSave()).toBe(true)
  })
})

describe('the nav column', () => {
  it('links Settings alongside Notes and Graph, active on /settings', () => {
    mounted.push(mount(NavColumn, { target: host, props: { route: { name: 'settings' } } }))
    flushSync()

    const link = host.querySelector<HTMLAnchorElement>('[data-testid="nav-item-settings"]')!
    expect(link.getAttribute('href')).toBe('/settings')
    expect(link.getAttribute('aria-current')).toBe('page')
    for (const other of ['notes', 'graph']) {
      expect(
        host.querySelector(`[data-testid="nav-item-${other}"]`)?.getAttribute('aria-current'),
      ).toBeNull()
    }
    expect(host.querySelector('[data-testid="nav-item-tokens"]')).toBeNull()
  })
})

describe('Settings is where Tokens and the pandan link live (KAN-1818)', () => {
  it('links to the Tokens and pandan-connection pages', async () => {
    await open()

    const links = host.querySelector('[data-testid="settings-links"]')!
    expect(links.querySelector('[data-testid="settings-tokens"]')?.getAttribute('href')).toBe('/tokens')
    expect(links.querySelector('[data-testid="settings-pandan"]')?.getAttribute('href')).toBe('/pandan')
  })
})
