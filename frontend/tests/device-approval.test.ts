// @vitest-environment jsdom
/**
 * `DeviceApproval.svelte` end to end against the ambient `fetch`, mirroring
 * `tests/tokens-page.test.ts`'s shape (ADR 0013, KAN-1743) — this component has no injectable
 * `fetchImpl` either, so the seam under test is the DOM plus every URL `lib/identity.ts` reaches.
 */

import { type Component, flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import DeviceApproval from '../src/components/DeviceApproval.svelte'

interface Authorization {
  user_code: string
  status: 'pending' | 'approved' | 'denied'
  requested_scope: string
  expires_at: string
}

interface RegisteredClient {
  client_name: string | null
}

let host: HTMLDivElement
const mounted: unknown[] = []
const realFetch = globalThis.fetch

let session: { id: string; email: string } | null
let codes: Map<string, Authorization>
let oauthClients: Map<string, RegisteredClient>

const AUTHORIZE_PARAMS =
  'client_id=kaya_client_abc&redirect_uri=https%3A%2F%2Fclaude.ai%2Fcallback&' +
  'code_challenge=abc123&code_challenge_method=S256&resource=https%3A%2F%2Fkaya.example%2Fmcp&' +
  'scope=write&state=xyz'

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

beforeEach(() => {
  host = document.createElement('div')
  document.body.append(host)
  window.history.pushState({}, '', '/device')
  session = null
  codes = new Map()
  oauthClients = new Map([['kaya_client_abc', { client_name: 'Claude.ai' }]])

  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    const [path, search] = url.split('?')

    if (url === '/users/me') {
      return session === null
        ? jsonResponse(401, { error: { code: 'unauthorized', message: 'not authenticated' } })
        : jsonResponse(200, session)
    }
    if (url === '/auth/github/authorize') {
      return jsonResponse(200, {
        authorization_url: 'https://github.com/login/oauth/authorize?x=1',
      })
    }
    if (path === '/auth/authorize/info' && method === 'GET') {
      const clientId = new URLSearchParams(search).get('client_id') ?? ''
      const client = oauthClients.get(clientId)
      if (client === undefined) {
        return jsonResponse(400, { error: 'invalid_client', error_description: 'unknown client_id' })
      }
      return jsonResponse(200, {
        client_name: client.client_name,
        requested_scope: new URLSearchParams(search).get('scope') ?? 'write',
        resource: new URLSearchParams(search).get('resource'),
      })
    }
    if ((path === '/auth/authorize/approve' || path === '/auth/authorize/deny') && method === 'POST') {
      const body = JSON.parse(init?.body as string) as { redirect_uri: string; state: string | null }
      const outcome = path.endsWith('approve') ? 'code=a-fresh-code' : 'error=access_denied'
      const state = body.state !== null ? `&state=${body.state}` : ''
      return jsonResponse(200, { redirect_to: `${body.redirect_uri}?${outcome}${state}` })
    }
    const match = /^\/auth\/device\/([^/]+)(\/(approve|deny))?$/.exec(url)
    if (match) {
      const code = decodeURIComponent(match[1] as string)
      const action = match[3] as 'approve' | 'deny' | undefined
      const found = codes.get(code)
      if (found === undefined) {
        return jsonResponse(404, {
          error: { code: 'device_code_not_found', message: 'code not found' },
        })
      }
      if (action === 'approve') {
        found.status = 'approved'
      } else if (action === 'deny') {
        found.status = 'denied'
      } else if (method !== 'GET') {
        return jsonResponse(404, { error: { code: 'not_found', message: 'nothing here' } })
      }
      return jsonResponse(200, found)
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
  window.history.pushState({}, '', '/')
})

function render(): HTMLDivElement {
  mounted.push(mount(DeviceApproval as Component<Record<string, never>>, { target: host, props: {} }))
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
  it('shows a GitHub sign-in prompt, not the consent screen', async () => {
    render()
    await until(() => host.querySelector('[data-testid="github-signin"]') !== null, 'sign-in')

    expect(host.querySelector('[data-testid="pending-consent"]')).toBeNull()
  })
})

describe('signed in, code supplied by the query string', () => {
  beforeEach(() => {
    session = { id: 'alice-id', email: 'alice@example.com' }
    window.history.pushState({}, '', '/device?user_code=WDJB-MJHT')
    codes.set('WDJB-MJHT', {
      user_code: 'WDJB-MJHT',
      status: 'pending',
      requested_scope: 'write',
      expires_at: '2026-09-26T12:00:00Z',
    })
  })

  it('reads the code from the query string with no code form shown', async () => {
    render()
    await until(() => host.querySelector('[data-testid="pending-consent"]') !== null, 'consent')

    expect(host.querySelector('[data-testid="code-form"]')).toBeNull()
    expect(host.textContent).toContain('write')
  })

  it('approving shows the approved state', async () => {
    render()
    await until(() => host.querySelector('[data-testid="approve"]') !== null, 'approve button')

    host.querySelector<HTMLButtonElement>('[data-testid="approve"]')!.click()
    await until(() => host.querySelector('[data-testid="approved-state"]') !== null, 'approved')
  })

  it('denying shows the denied state', async () => {
    render()
    await until(() => host.querySelector('[data-testid="deny"]') !== null, 'deny button')

    host.querySelector<HTMLButtonElement>('[data-testid="deny"]')!.click()
    await until(() => host.querySelector('[data-testid="denied-state"]') !== null, 'denied')
  })
})

describe('signed in, no code in the query string', () => {
  beforeEach(() => {
    session = { id: 'alice-id', email: 'alice@example.com' }
  })

  it('shows an editable code field instead of guessing one', async () => {
    render()
    await until(() => host.querySelector('[data-testid="code-form"]') !== null, 'code form')

    expect(host.querySelector('[data-testid="pending-consent"]')).toBeNull()
  })

  it('submitting a code loads its consent state', async () => {
    codes.set('TYPED-CODE', {
      user_code: 'TYPED-CODE',
      status: 'pending',
      requested_scope: 'read',
      expires_at: '2026-09-26T12:00:00Z',
    })
    render()
    await until(() => host.querySelector('[data-testid="code-form"]') !== null, 'code form')

    const input = host.querySelector<HTMLInputElement>('#user-code')!
    input.value = 'TYPED-CODE'
    input.dispatchEvent(new Event('input', { bubbles: true }))
    flushSync()
    host
      .querySelector<HTMLFormElement>('[data-testid="code-form"]')!
      .dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))

    await until(() => host.querySelector('[data-testid="pending-consent"]') !== null, 'consent')
    expect(host.textContent).toContain('read')
  })
})

describe('a code that does not exist', () => {
  beforeEach(() => {
    session = { id: 'alice-id', email: 'alice@example.com' }
    window.history.pushState({}, '', '/device?user_code=NOPE-CODE')
  })

  it('shows the not-found state rather than a raw error', async () => {
    render()
    await until(() => host.querySelector('[data-testid="not-found"]') !== null, 'not-found')

    expect(host.querySelector('[data-testid="pending-consent"]')).toBeNull()
  })
})

describe('authorize mode (ADR 0014, KAN-1744): a client_id+redirect_uri redirect', () => {
  let assignSpy: ReturnType<typeof vi.fn>

  const realLocation = window.location

  beforeEach(() => {
    session = { id: 'alice-id', email: 'alice@example.com' }
    window.history.pushState({}, '', `/device?${AUTHORIZE_PARAMS}`)
    assignSpy = vi.fn()
    Object.defineProperty(window, 'location', {
      value: { ...realLocation, assign: assignSpy },
      configurable: true,
      writable: true,
    })
  })

  afterEach(() => {
    Object.defineProperty(window, 'location', {
      value: realLocation,
      configurable: true,
      writable: true,
    })
  })

  it('shows the requesting client name and scope, with no code form', async () => {
    render()
    await until(() => host.querySelector('[data-testid="pending-consent"]') !== null, 'consent')

    expect(host.querySelector('[data-testid="code-form"]')).toBeNull()
    expect(host.textContent).toContain('Claude.ai')
    expect(host.textContent).toContain('write')
  })

  it('approving navigates the browser to the redirect_to URL, never resolves in place', async () => {
    render()
    await until(() => host.querySelector('[data-testid="approve"]') !== null, 'approve button')

    host.querySelector<HTMLButtonElement>('[data-testid="approve"]')!.click()
    await until(() => assignSpy.mock.calls.length > 0, 'navigation')

    const [destination] = assignSpy.mock.calls[0] as [string]
    expect(destination).toBe('https://claude.ai/callback?code=a-fresh-code&state=xyz')
    expect(host.querySelector('[data-testid="approved-state"]')).toBeNull()
  })

  it('denying navigates to the redirect_to URL with access_denied', async () => {
    render()
    await until(() => host.querySelector('[data-testid="deny"]') !== null, 'deny button')

    host.querySelector<HTMLButtonElement>('[data-testid="deny"]')!.click()
    await until(() => assignSpy.mock.calls.length > 0, 'navigation')

    const [destination] = assignSpy.mock.calls[0] as [string]
    expect(destination).toBe('https://claude.ai/callback?error=access_denied&state=xyz')
  })

  it('an unknown client_id shows the not-found state with the server message', async () => {
    oauthClients.clear()
    render()
    await until(() => host.querySelector('[data-testid="not-found"]') !== null, 'not-found')

    expect(host.textContent).toContain('unknown client_id')
  })
})

describe('authorize mode with an incomplete query string', () => {
  beforeEach(() => {
    session = { id: 'alice-id', email: 'alice@example.com' }
    // client_id present, but none of the other required PKCE/resource params — must not be
    // mistaken for device mode (which would otherwise show an empty code-entry form).
    window.history.pushState({}, '', '/device?client_id=kaya_client_abc')
  })

  it('shows not-found immediately, with no network call at all', async () => {
    render()
    await until(() => host.querySelector('[data-testid="not-found"]') !== null, 'not-found')

    expect(host.querySelector('[data-testid="code-form"]')).toBeNull()
    const calledAuthorizeInfo = vi
      .mocked(globalThis.fetch)
      .mock.calls.some(([input]) => String(input).startsWith('/auth/authorize/info'))
    expect(calledAuthorizeInfo).toBe(false)
  })
})
