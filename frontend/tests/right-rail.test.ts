// @vitest-environment jsdom
/**
 * `RightRail.svelte`: the tab strip R13/KAN-1064 put beside `BacklinksPanel`, and the one thing
 * this file has to prove that neither `tests/backlinks-panel.test.ts` nor
 * `tests/history-panel.test.ts` can: that only one tab's panel is mounted at a time, so switching
 * tabs does not leave a hidden panel's fetch lifecycle running (see `RightRail.svelte`'s docstring).
 */

import { flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import RightRail from '../src/components/RightRail.svelte'
import * as auth from '../src/lib/auth'
import type { Note } from '../src/lib/types'
import { FAKE_TOKEN } from './token'

const NOTE: Note = {
  ref: 'NOTE-1',
  id: 1,
  title: 'A note',
  body: 'body',
  path: '',
  created_at: '2026-08-09T10:00:00+00:00',
  updated_at: '2026-08-09T10:00:00.123456+00:00',
}

let host: HTMLDivElement
const mounted: unknown[] = []
const realFetch = globalThis.fetch
let asked: string[]

beforeEach(() => {
  host = document.createElement('div')
  document.body.append(host)
  auth.setToken(FAKE_TOKEN)
  asked = []
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    asked.push(url)
    const body = url.endsWith('/backlinks') ? { notes: [] } : { versions: [] }
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
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

function render(): void {
  mounted.push(
    mount(RightRail, {
      target: host,
      props: { note: NOTE, onexpired: () => {}, onrestored: () => {} },
    }),
  )
  flushSync()
}

function click(testid: string): void {
  host.querySelector<HTMLButtonElement>(`[data-testid="${testid}"]`)!.click()
  flushSync()
}

describe('RightRail', () => {
  it('shows Backlinks first, and switches panels on click', async () => {
    render()
    await vi.waitFor(() => {
      flushSync()
      expect(host.querySelector('aside.rail[aria-label="Backlinks"]')).not.toBeNull()
    })
    expect(host.querySelector('[data-testid="history-versions"]')).toBeNull()
    expect(host.querySelector('[data-testid="history-empty"]')).toBeNull()

    click('rail-tab-history')

    await vi.waitFor(() => {
      flushSync()
      expect(host.querySelector('[data-testid="history-empty"]')).not.toBeNull()
    })
    expect(host.querySelector('aside.rail[aria-label="Backlinks"]')).toBeNull()
  })

  it('marks the active tab with aria-selected', () => {
    render()
    const backlinks = host.querySelector<HTMLButtonElement>('[data-testid="rail-tab-backlinks"]')!
    const history = host.querySelector<HTMLButtonElement>('[data-testid="rail-tab-history"]')!
    expect(backlinks.getAttribute('aria-selected')).toBe('true')
    expect(history.getAttribute('aria-selected')).toBe('false')

    click('rail-tab-history')

    expect(backlinks.getAttribute('aria-selected')).toBe('false')
    expect(history.getAttribute('aria-selected')).toBe('true')
  })

  it('unmounts the hidden tab rather than merely hiding it', async () => {
    render()
    await vi.waitFor(() => {
      flushSync()
      expect(asked.some((url) => url.endsWith('/backlinks'))).toBe(true)
    })
    const backlinksCallsBeforeSwitch = asked.filter((url) => url.endsWith('/backlinks')).length

    click('rail-tab-history')
    await vi.waitFor(() => {
      flushSync()
      expect(asked.some((url) => url.endsWith('/versions'))).toBe(true)
    })

    // Switching back to Backlinks re-fetches, which is only possible if the first instance was
    // torn down rather than kept alive off-screen (a live instance would already have its answer).
    click('rail-tab-backlinks')
    await vi.waitFor(() => {
      flushSync()
      const backlinksCallsAfterSwitch = asked.filter((url) => url.endsWith('/backlinks')).length
      expect(backlinksCallsAfterSwitch).toBeGreaterThan(backlinksCallsBeforeSwitch)
    })
  })
})
