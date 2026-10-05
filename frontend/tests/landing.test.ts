// @vitest-environment jsdom
/**
 * The landing state (KAN-555; KAN-1740's identity cutover; KAN-1791 removed the browser
 * paste-a-token flow entirely).
 *
 * There is no longer a credential-bearing surface in this component for a fragment sweep to run
 * over. Before KAN-1791, a live token sat in the paste field's `value` property mid-paste, which is
 * why this file used to carry an elaborate sweep (`surfaces()`/`sweep()`) over the serialized HTML,
 * every `href` and every request URL. GitHub sign-in is a pure redirect instead — `githubLoginUrl()`
 * resolves to a URL and the tab navigates, so no credential value ever exists inside this component
 * at all, and there is nothing left here for that sweep to protect. `tests/auth.test.ts` still
 * sweeps everything the credential seam itself exposes, and `tests/tokens-page.test.ts` covers the
 * one remaining place a token is typed and shown (`Tokens.svelte`'s "Use this token now").
 *
 * What is still this file's job: the landing copy itself, the GitHub sign-in button, the
 * declined/failed consent-screen message (and its single-use query param), and the `rejected`
 * banner `App.svelte`'s `discard()` still feeds this component after a real `401` — relocated from
 * the now-deleted paste section into the hero, beside the one credential-acquisition path left.
 */

import { type Component, flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from '../src/App.svelte'
import Landing from '../src/components/Landing.svelte'
import * as auth from '../src/lib/auth'
import { FAKE_TOKEN } from './token'

const PANDAN = 'https://pandan.example.test'

const NOTE = {
  ref: 'NOTE-6',
  id: 6,
  title: 'Weekly review',
  body: '# Week of 2026-08-03\n',
  path: 'journal/2026/08/weekly-review.md',
  created_at: '2026-08-09T10:00:00+00:00',
  updated_at: '2026-08-09T10:00:00.123456+00:00',
  team_id: null,
}

let host: HTMLDivElement
const mounted: unknown[] = []
const realFetch = globalThis.fetch

/** How `/api/v1/notes` answers. Swappable mid-test, which is what the `401` recovery needs. */
let notesAnswer: () => Response

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function refusal(status: number, code: string, message: string): Response {
  return jsonResponse(status, { error: { code, message } })
}

beforeEach(() => {
  host = document.createElement('div')
  document.body.append(host)
  notesAnswer = () => jsonResponse(200, { notes: [NOTE] })

  // The ambient `fetch`, not an injected one: the components under test reach the network through
  // `lib/api.ts` with no seam for a test to pass a fake through, and inventing one would be a
  // production parameter that exists for this file.
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url === '/api/v1/meta') {
      return jsonResponse(200, { pandan_url: null })
    }
    if (url === '/api/v1/notes') {
      return notesAnswer()
    }
    if (url === '/users/me') {
      return refusal(401, 'unauthorized', 'not signed in')
    }
    return refusal(404, 'not_found', `nothing fake at ${url}`)
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

function render<Props extends Record<string, unknown>>(
  component: Component<Props, Record<string, unknown>>,
  props: Props,
): HTMLDivElement {
  mounted.push(mount(component, { target: host, props }))
  flushSync()
  return host
}

/**
 * Let the effects run and the promises they started settle.
 *
 * **Macrotask turns, not microtask turns.** `Response.text()` resolves through the platform's stream
 * machinery rather than on the microtask queue, so a loop of `await Promise.resolve()` is a guess
 * about how many turns this machine needs — it passed locally and failed three tests on CI. Use
 * {@link until} wherever there is a condition to wait *for*; this is for "give everything a chance
 * to happen" where the assertion is a negative one.
 */
async function settle(): Promise<void> {
  for (let turn = 0; turn < 12; turn += 1) {
    await new Promise((resolve) => setTimeout(resolve, 0))
    flushSync()
  }
}

/** Poll until `predicate` holds, flushing Svelte between attempts, and name it if it never does. */
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

describe('the landing state', () => {
  it('carries the approved headline, subhead and three tile titles verbatim (KAN-1822)', async () => {
    render(Landing, { rejected: null, onaccept: () => {} })
    await settle()

    expect(host.querySelector('h1')?.textContent).toBe('Markdown for humans and agents.')
    expect(host.querySelector('.subhead')?.textContent).toBe('Work on notes alongside your agents.')
    expect(Array.from(host.querySelectorAll('.tile h2')).map((h) => h.textContent)).toEqual([
      'Agent ready',
      'Linked notes',
      'Knowledge graph',
    ])
    expect(host.textContent).toContain(
      'Write and edit notes from Claude Code or any MCP client, or script them with the CLI.',
    )
    // Only Claude Code has been checked against the MCP endpoint, so no other client is named.
    expect(host.textContent).not.toContain('Codex')
  })

  it('contains none of the removed copy and shows the phone demo, not the old example note', async () => {
    render(Landing, { rejected: null, onaccept: () => {} })
    await settle()

    const text = host.textContent ?? ''
    for (const gone of ['any device', 'no password', 'ADR', '/api/v1', 'Every save', 'mints']) {
      expect(text).not.toContain(gone)
    }
    expect(host.querySelector('.demo')).toBeNull()
    expect(host.querySelector('.identity-note')).toBeNull()
    expect(host.querySelector('[data-testid="phone-demo"]')).not.toBeNull()
    // Nothing on the page links anywhere: sign-in is a button, and the phone's contents are inert.
    expect(host.querySelectorAll('a')).toHaveLength(0)
  })

  it('carries no pandan origin anywhere — identity no longer routes through pandan at all', async () => {
    render(Landing, { rejected: null, onaccept: () => {} })
    await settle()

    // `simple-kanban-jian` was the string a hard-coded pandan-origin fallback would be spelled
    // with, before KAN-1740; `PANDAN` (this file's own fake origin, used by the App-level test
    // below) covers the general case.
    expect(document.body.innerHTML).not.toContain('simple-kanban-jian')
    expect(document.body.innerHTML).not.toContain(PANDAN)
  })

  it('has no paste form and no way to type a credential in — KAN-1791', async () => {
    render(Landing, { rejected: null, onaccept: () => {} })
    await settle()

    expect(host.querySelector('input[type="password"]')).toBeNull()
    expect(host.querySelector('[data-testid="paste-form"]')).toBeNull()
    expect(host.querySelector('[data-testid="github-signin"]')).not.toBeNull()
  })
})

describe('returning from a declined or failed GitHub consent screen', () => {
  afterEach(() => {
    history.replaceState(null, '', '/')
  })

  it('shows a friendly message for a declined consent screen, and clears the query param', async () => {
    history.pushState(null, '', '/?oauth_error=access_denied')

    render(Landing, { rejected: null, onaccept: () => {} })
    await until(
      () => host.querySelector('[data-testid="sign-in-problem"]') !== null,
      'the declined-consent message',
    )

    expect(host.querySelector('[data-testid="sign-in-problem"]')?.textContent).toBe(
      'GitHub sign-in was cancelled.',
    )
    // `_redirect_declined_oauth`'s query param is single-use: a reload of this same tab should
    // not re-show a message about an attempt from minutes ago.
    expect(globalThis.location.search).toBe('')
  })

  it('shows a generic message for any other oauth_error value', async () => {
    history.pushState(null, '', '/?oauth_error=oauth_failed')

    render(Landing, { rejected: null, onaccept: () => {} })
    await until(
      () => host.querySelector('[data-testid="sign-in-problem"]') !== null,
      'the failure message',
    )

    expect(host.querySelector('[data-testid="sign-in-problem"]')?.textContent).toBe(
      'GitHub sign-in failed. Try again.',
    )
  })
})

describe('a real 401, end to end through the shell', () => {
  it('returns to the landing state with the API\'s own message, beside the sign-in button rather than a paste form', async () => {
    // KAN-1791: there is no more paste-and-retry loop to assert here — the way out of a real `401`
    // is GitHub sign-in (or `Tokens.svelte`'s own named-token flow), and the `rejected` message this
    // file used to find beside a re-paste form now sits beside that button instead.
    auth.setToken(FAKE_TOKEN)
    notesAnswer = () => refusal(401, 'invalid_token', 'That token is not valid.')

    render(App, {})
    await until(
      () => host.querySelector('[data-testid="rejected"]') !== null,
      'the landing state to come back with the refusal',
    )

    expect(auth.credentialState()).toBe('not set')
    expect(host.querySelector('[data-testid="rejected"]')?.textContent).toContain(
      'That token is not valid.',
    )
    expect(host.querySelector('[data-testid="github-signin"]')).not.toBeNull()
    expect(host.querySelector('[data-testid="paste-form"]')).toBeNull()
    expect(host.querySelector('nav')).toBeNull()
  })
})
