// @vitest-environment jsdom
/**
 * `Tokens.svelte` end to end against the ambient `fetch`, mirroring `tests/landing.test.ts`'s shape
 * (ADR 0012, KAN-1739) — this component has no injectable `fetchImpl` of its own, the same as
 * `Landing.svelte`, so the seam under test is the DOM plus every URL `lib/identity.ts` reaches.
 */

import { type Component, flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import Tokens from '../src/components/Tokens.svelte'

interface Call {
  url: string
  init: RequestInit | undefined
}

let host: HTMLDivElement
let calls: Call[]
const mounted: unknown[] = []
const realFetch = globalThis.fetch

let session: { id: string; email: string } | null
let tokens: Array<{
  id: number
  name: string
  token_prefix: string
  scope: string
  created_at: string
  last_used_at: string | null
  expires_at: string | null
}>

function jsonResponse(status: number, body: unknown): Response {
  return new Response(body === null ? null : JSON.stringify(body), {
    status,
    headers: body === null ? {} : { 'Content-Type': 'application/json' },
  })
}

beforeEach(() => {
  host = document.createElement('div')
  document.body.append(host)
  calls = []
  session = null
  tokens = []

  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    calls.push({ url, init })

    if (url === '/users/me') {
      return session === null
        ? jsonResponse(401, { error: { code: 'unauthorized', message: 'not authenticated' } })
        : jsonResponse(200, session)
    }
    if (url === '/auth/github/authorize') {
      return jsonResponse(200, { authorization_url: 'https://github.com/login/oauth/authorize?x=1' })
    }
    if (url === '/api/v1/tokens' && method === 'GET') {
      return jsonResponse(200, tokens)
    }
    if (url === '/api/v1/tokens' && method === 'POST') {
      const body = JSON.parse(init?.body as string) as { name: string; scope?: string }
      const created = {
        id: tokens.length + 1,
        name: body.name,
        token_prefix: 'kaya_pat_ab12',
        scope: body.scope ?? 'write',
        created_at: '2026-09-25T00:00:00Z',
        last_used_at: null,
        expires_at: null,
      }
      tokens = [...tokens, created]
      return jsonResponse(201, { ...created, token: 'kaya_pat_FAKEsecretvalue1234' })
    }
    if (url.startsWith('/api/v1/tokens/') && method === 'DELETE') {
      const id = Number(url.split('/').pop())
      tokens = tokens.filter((token) => token.id !== id)
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
})

function render(): HTMLDivElement {
  mounted.push(mount(Tokens as Component<Record<string, never>>, { target: host, props: {} }))
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
  it('shows a GitHub sign-in button, not the token list', async () => {
    render()
    await until(
      () => host.querySelector('[data-testid="github-signin"]') !== null,
      'the sign-in button',
    )

    expect(host.querySelector('[data-testid="token-list"]')).toBeNull()
  })

  it('sends the browser to the authorization_url the backend returned', async () => {
    render()
    await until(
      () => host.querySelector('[data-testid="github-signin"]') !== null,
      'the sign-in button',
    )

    const assign = vi.fn()
    vi.stubGlobal('location', { ...globalThis.location, assign })

    host.querySelector<HTMLButtonElement>('[data-testid="github-signin"]')!.click()
    await until(() => assign.mock.calls.length > 0, 'the navigation')

    expect(assign).toHaveBeenCalledWith('https://github.com/login/oauth/authorize?x=1')
    vi.unstubAllGlobals()
  })
})

describe('signed in', () => {
  beforeEach(() => {
    session = { id: 'abc-123', email: 'alice@example.com' }
  })

  it('shows the signed-in email and an empty token list', async () => {
    render()
    await until(
      () => host.querySelector('[data-testid="current-email"]') !== null,
      'the signed-in state',
    )

    expect(host.querySelector('[data-testid="current-email"]')?.textContent).toBe(
      'alice@example.com',
    )
    expect(host.querySelector('[data-testid="token-list"]')).toBeNull()
  })

  it('creates a token, shows the secret exactly once, and lists it afterwards', async () => {
    render()
    await until(() => host.querySelector('[data-testid="create-form"]') !== null, 'the create form')

    const nameInput = host.querySelector<HTMLInputElement>('#token-name')!
    nameInput.value = 'laptop'
    nameInput.dispatchEvent(new Event('input', { bubbles: true }))
    flushSync()

    const form = host.querySelector<HTMLFormElement>('[data-testid="create-form"]')!
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    await until(
      () => host.querySelector('[data-testid="created-secret"]') !== null,
      'the revealed secret',
    )

    expect(host.querySelector('[data-testid="created-secret"]')?.textContent).toContain(
      'kaya_pat_FAKEsecretvalue1234',
    )
    await until(
      () => host.querySelectorAll('[data-testid="token-list"] li').length === 1,
      'the token appearing in the list',
    )
    expect(host.querySelector('[data-testid="token-list"]')?.textContent).toContain('laptop')
    // The list read must never carry the secret — only the create response does.
    expect(host.querySelector('[data-testid="token-list"]')?.textContent).not.toContain(
      'FAKEsecretvalue1234',
    )
  })

  it('revoking a token removes it from the list', async () => {
    tokens = [
      {
        id: 5,
        name: 'old laptop',
        token_prefix: 'kaya_pat_zz99',
        scope: 'write',
        created_at: '2026-09-25T00:00:00Z',
        last_used_at: null,
        expires_at: null,
      },
    ]

    render()
    await until(
      () => host.querySelectorAll('[data-testid="token-list"] li').length === 1,
      'the existing token to render',
    )

    host.querySelector<HTMLButtonElement>('[data-testid="token-list"] button')!.click()
    await until(() => host.querySelector('[data-testid="token-list"]') === null, 'the empty state')

    expect(host.textContent).toContain('No tokens yet')
  })
})
