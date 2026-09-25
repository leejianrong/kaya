// @vitest-environment jsdom
/**
 * `PandanConnect.svelte` end to end against the ambient `fetch`, mirroring `tests/tokens-page.test.ts`'s
 * shape (ADR 0012's amendment, KAN-1741) — this component has no injectable `fetchImpl` of its own,
 * so the seam under test is the DOM plus every URL `lib/pandanLink.ts` reaches.
 *
 * Unlike `Tokens.svelte`, this component authenticates through `lib/auth.ts`'s `kaya_pat_…` bearer
 * (`apiRequest`, not `lib/identity.ts`'s cookie-only `identityRequest`) — see `lib/pandanLink.ts`'s
 * own module docstring for why. `auth.setToken(FAKE_TOKEN)` before each test is what stands in for
 * "already inside the authenticated shell".
 */

import { type Component, flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import PandanConnect from '../src/components/PandanConnect.svelte'
import * as auth from '../src/lib/auth'
import { FAKE_TOKEN } from './token'

let host: HTMLDivElement
const mounted: unknown[] = []
const realFetch = globalThis.fetch

let connected: boolean
let calls: Array<{ url: string; method: string; body: unknown }>

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
  connected = false
  calls = []

  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    const body = init?.body ? JSON.parse(init.body as string) : undefined
    calls.push({ url, method, body })

    if (url === '/api/v1/pandan-link' && method === 'GET') {
      return jsonResponse(200, { connected })
    }
    if (url === '/api/v1/pandan-link' && method === 'POST') {
      const token = (body as { token?: string } | undefined)?.token
      if (token === 'a-bad-pandan-token') {
        return jsonResponse(422, {
          error: { code: 'invalid_pandan_token', message: 'pandan did not accept this token' },
        })
      }
      connected = true
      return jsonResponse(200, { connected: true })
    }
    if (url === '/api/v1/pandan-link' && method === 'DELETE') {
      connected = false
      return jsonResponse(200, { connected: false })
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
  auth.clearToken()
})

function render(): HTMLDivElement {
  mounted.push(
    mount(PandanConnect as Component<Record<string, never>>, { target: host, props: {} }),
  )
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

describe('not yet connected', () => {
  it('shows the paste form, not the connected state', async () => {
    render()
    await until(() => host.querySelector('[data-testid="connect-form"]') !== null, 'the form')

    expect(host.querySelector('[data-testid="connected-state"]')).toBeNull()
  })

  it('connecting a good token shows the connected state', async () => {
    render()
    await until(() => host.querySelector('[data-testid="connect-form"]') !== null, 'the form')

    const input = host.querySelector<HTMLInputElement>('#pandan-token')!
    input.value = 'a-real-looking-pandan-pat'
    input.dispatchEvent(new Event('input', { bubbles: true }))
    flushSync()

    const form = host.querySelector<HTMLFormElement>('[data-testid="connect-form"]')!
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    await until(
      () => host.querySelector('[data-testid="connected-state"]') !== null,
      'the connected state',
    )

    expect(host.querySelector('[data-testid="disconnect"]')).not.toBeNull()
  })

  it('clears the field before the request is sent, win or lose', async () => {
    render()
    await until(() => host.querySelector('[data-testid="connect-form"]') !== null, 'the form')

    const input = host.querySelector<HTMLInputElement>('#pandan-token')!
    input.value = 'a-real-looking-pandan-pat'
    input.dispatchEvent(new Event('input', { bubbles: true }))
    flushSync()

    host
      .querySelector<HTMLFormElement>('[data-testid="connect-form"]')!
      .dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    flushSync()

    expect(input.value).toBe('')
  })

  it('a token pandan rejects shows the refusal and stays disconnected', async () => {
    render()
    await until(() => host.querySelector('[data-testid="connect-form"]') !== null, 'the form')

    const input = host.querySelector<HTMLInputElement>('#pandan-token')!
    input.value = 'a-bad-pandan-token'
    input.dispatchEvent(new Event('input', { bubbles: true }))
    flushSync()

    host
      .querySelector<HTMLFormElement>('[data-testid="connect-form"]')!
      .dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    await until(() => host.querySelector('[data-testid="problem"]') !== null, 'the refusal')

    expect(host.querySelector('[data-testid="connected-state"]')).toBeNull()
  })
})

describe('already connected', () => {
  beforeEach(() => {
    connected = true
  })

  it('shows the connected state, not the paste form', async () => {
    render()
    await until(
      () => host.querySelector('[data-testid="connected-state"]') !== null,
      'the connected state',
    )

    expect(host.querySelector('[data-testid="connect-form"]')).toBeNull()
  })

  it('disconnecting shows the paste form again', async () => {
    render()
    await until(
      () => host.querySelector('[data-testid="disconnect"]') !== null,
      'the disconnect button',
    )

    host.querySelector<HTMLButtonElement>('[data-testid="disconnect"]')!.click()
    await until(() => host.querySelector('[data-testid="connect-form"]') !== null, 'the form')

    expect(calls.some((call) => call.url === '/api/v1/pandan-link' && call.method === 'DELETE')).toBe(
      true,
    )
  })
})
