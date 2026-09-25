// @vitest-environment jsdom
/**
 * `DeviceConsent.svelte` end to end against the ambient `fetch`, mirroring
 * `tests/tokens-page.test.ts`'s shape (ADR 0013, KAN-1743) — this component has no injectable
 * `fetchImpl` of its own, so the seam under test is the DOM plus every URL `lib/identity.ts`
 * reaches.
 */

import { type Component, flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import DeviceConsent from '../src/components/DeviceConsent.svelte'

let host: HTMLDivElement
const mounted: unknown[] = []
const realFetch = globalThis.fetch
const realSearch = globalThis.location.search

interface Row {
  user_code: string
  status: 'pending' | 'approved' | 'denied'
  requested_scope: 'read' | 'write'
  expires_at: string
}

let session: { id: string; email: string } | null
let row: Row | null

function jsonResponse(status: number, body: unknown): Response {
  return new Response(body === null ? null : JSON.stringify(body), {
    status,
    headers: body === null ? {} : { 'Content-Type': 'application/json' },
  })
}

function setSearch(search: string): void {
  vi.stubGlobal('location', { ...globalThis.location, search })
}

beforeEach(() => {
  host = document.createElement('div')
  document.body.append(host)
  session = { id: 'abc-123', email: 'alice@example.com' }
  row = {
    user_code: 'WDJB-MJHT',
    status: 'pending',
    requested_scope: 'write',
    expires_at: '2026-09-25T00:15:00Z',
  }
  setSearch('?user_code=WDJB-MJHT')

  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'

    if (url === '/users/me') {
      return session === null
        ? jsonResponse(401, { error: { code: 'unauthorized', message: 'not authenticated' } })
        : jsonResponse(200, session)
    }
    if (url === '/auth/github/authorize') {
      return jsonResponse(200, { authorization_url: 'https://github.com/login/oauth/authorize?x=1' })
    }
    if (url === '/auth/device/WDJB-MJHT' && method === 'GET') {
      return row === null
        ? jsonResponse(404, { error: { code: 'not_found', message: 'code not found' } })
        : jsonResponse(200, row)
    }
    if (url === '/auth/device/WDJB-MJHT/approve' && method === 'POST') {
      const body = JSON.parse(init?.body as string) as { scope: 'read' | 'write' }
      row = { ...(row as Row), status: 'approved', requested_scope: body.scope }
      return jsonResponse(200, row)
    }
    if (url === '/auth/device/WDJB-MJHT/deny' && method === 'POST') {
      row = { ...(row as Row), status: 'denied' }
      return jsonResponse(204, null)
    }
    return jsonResponse(404, { error: { code: 'not_found', message: `nothing fake at ${url}` } })
  }) as unknown as typeof fetch
})

afterEach(() => {
  for (const instance of mounted.splice(0)) {
    unmount(instance as never)
  }
  host.remove()
  globalThis.fetch = realFetch
  vi.unstubAllGlobals()
  setSearch(realSearch)
})

function render(): HTMLDivElement {
  mounted.push(mount(DeviceConsent as Component<Record<string, never>>, { target: host, props: {} }))
  flushSync()
  return host
}

async function until(predicate: () => boolean, label: string): Promise<void> {
  for (let turn = 0; turn < 400; turn += 1) {
    flushSync()
    if (predicate()) {
      return
    }
    await new Promise((resolve) => setTimeout(resolve, 5))
  }
  throw new Error(`timed out waiting for ${label}`)
}

describe('signed out', () => {
  beforeEach(() => {
    session = null
  })

  it('shows a GitHub sign-in button, not the consent screen', async () => {
    render()
    await until(
      () => host.querySelector('[data-testid="github-signin"]') !== null,
      'the sign-in button',
    )

    expect(host.querySelector('[data-testid="approve"]')).toBeNull()
  })
})

describe('signed in, with a pending code', () => {
  it('shows the requested scope and the user code', async () => {
    render()
    await until(() => host.querySelector('[data-testid="user-code"]') !== null, 'the user code')

    expect(host.querySelector('[data-testid="user-code"]')?.textContent).toBe('WDJB-MJHT')
    expect(host.textContent).toContain('write')
  })

  it('approving shows the approved state', async () => {
    render()
    await until(() => host.querySelector('[data-testid="approve"]') !== null, 'the approve button')

    host.querySelector<HTMLButtonElement>('[data-testid="approve"]')!.click()
    await until(
      () => host.querySelector('[data-testid="approved-state"]') !== null,
      'the approved state',
    )

    expect(host.querySelector('[data-testid="deny"]')).toBeNull()
  })

  it('denying shows the denied state', async () => {
    render()
    await until(() => host.querySelector('[data-testid="deny"]') !== null, 'the deny button')

    host.querySelector<HTMLButtonElement>('[data-testid="deny"]')!.click()
    await until(
      () => host.querySelector('[data-testid="denied-state"]') !== null,
      'the denied state',
    )

    expect(host.querySelector('[data-testid="approve"]')).toBeNull()
  })
})

describe('an unknown or expired code', () => {
  beforeEach(() => {
    row = null
  })

  it('shows a message telling the caller to log in again, not a crash', async () => {
    render()
    await until(() => host.querySelector('[data-testid="gone"]') !== null, 'the gone state')

    expect(host.querySelector('[data-testid="gone"]')?.textContent).toContain('kaya auth login')
  })
})

describe('a missing user_code in the URL', () => {
  beforeEach(() => {
    setSearch('')
  })

  it('shows a message rather than calling the API with nothing', async () => {
    render()
    await until(() => host.querySelector('[data-testid="gone"]') !== null, 'the gone state')

    expect(host.querySelector('[data-testid="gone"]')?.textContent).toContain('whole link')
  })
})
