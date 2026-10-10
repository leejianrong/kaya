// @vitest-environment jsdom
/**
 * KAY-138: `HistoryPanel.svelte` shows who made each version and a line diff between two of them.
 * `tests/history-panel.test.ts` owns the list/preview/restore behaviour; this file owns only what
 * this card added, with the same no-testing-library harness.
 */

import { flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import HistoryPanel from '../src/components/HistoryPanel.svelte'
import * as auth from '../src/lib/auth'
import type { Note, NoteVersion, VersionActor } from '../src/lib/types'
import { box } from './reactive.svelte'
import { FAKE_TOKEN } from './token'

const NOTE: Note = {
  ref: 'NOTE-1',
  id: 1,
  title: 'Title',
  body: 'current body',
  path: '',
  created_at: '2026-08-09T10:00:00+00:00',
  updated_at: '2026-08-09T10:00:00.123456+00:00',
  team_id: null,
}

function version(id: number, overrides: Partial<NoteVersion> = {}): NoteVersion {
  return { id, body: `body ${id}`, created_at: '2026-08-09T10:00:00+00:00', ...overrides }
}

const tokenActor: VersionActor = {
  user_id: 'u',
  email: 'a@x.io',
  channel: 'token',
  token: { id: 1, prefix: 'kaya_pat_ab12', name: 'ci-bot', kind: null },
  is_you: false,
}
const youOnTheWeb: VersionActor = {
  user_id: 'u',
  email: 'a@x.io',
  channel: 'session',
  token: null,
  is_you: true,
}

let host: HTMLDivElement
const mounted: unknown[] = []
const realFetch = globalThis.fetch
let asked: string[]
let versions: NoteVersion[]

beforeEach(() => {
  host = document.createElement('div')
  document.body.append(host)
  auth.setToken(FAKE_TOKEN)
  asked = []
  versions = []
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    asked.push(String(input))
    return new Response(JSON.stringify({ versions }), {
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
  const opened = box<Note | null>(NOTE)
  mounted.push(
    mount(HistoryPanel, {
      target: host,
      props: {
        get note() {
          return opened.value
        },
        onexpired: () => {},
        onrestored: () => {},
      },
    }),
  )
  flushSync()
}

async function settledOn(testid: string): Promise<HTMLElement> {
  let element: HTMLElement | null = null
  await vi.waitFor(() => {
    flushSync()
    element = host.querySelector<HTMLElement>(`[data-testid="${testid}"]`)
    expect(element, `never settled on ${testid}`).not.toBeNull()
  })
  return element!
}

function click(testid: string, index = 0): void {
  host.querySelectorAll<HTMLButtonElement>(`[data-testid="${testid}"]`)[index].click()
  flushSync()
}

const squash = (text: string | null): string => (text ?? '').replace(/\s+/g, ' ').trim()

describe('who made each version', () => {
  it('labels each row: You on the web, a named token, and before tracking', async () => {
    versions = [
      version(3, { actor: youOnTheWeb }),
      version(2, { actor: tokenActor }),
      version(1, { actor: null }),
    ]
    render()
    await settledOn('history-versions')

    const labels = [...host.querySelectorAll('[data-testid="history-actor"]')].map((element) =>
      squash(element.textContent),
    )
    expect(labels).toEqual([
      'You · web',
      'a@x.io · Token ci-bot (kaya_pat_ab12…)',
      'before tracking',
    ])
  })
})

describe('the diff between two versions', () => {
  it('shows what changed against the previous version, without a second request', async () => {
    versions = [version(2, { body: 'a\nB\nc' }), version(1, { body: 'a\nb\nc' })]
    render()
    await settledOn('history-versions')

    const before = asked.length
    click('history-row', 0)
    click('history-view-changes')

    const stat = await settledOn('history-diff-stat')
    expect(squash(stat.textContent)).toContain('v1 to v2: +1 −1')
    const kinds = [...host.querySelectorAll('[data-testid="history-diff-line"]')].map((line) =>
      line.className.replace('drow ', '').replace(/svelte-\S+/, '').trim(),
    )
    expect(kinds).toEqual(['same', 'del', 'add', 'same'])
    expect(asked).toHaveLength(before)
  })

  it('diffs the first version against nothing', async () => {
    versions = [version(1, { body: 'x\ny' })]
    render()
    await settledOn('history-versions')
    click('history-row')
    click('history-view-changes')
    const stat = await settledOn('history-diff-stat')
    expect(squash(stat.textContent)).toContain('nothing to v1: +2 −0')
  })

  it('says so when two versions are identical', async () => {
    versions = [version(2, { body: 'same' }), version(1, { body: 'same' })]
    render()
    await settledOn('history-versions')
    click('history-row', 0)
    click('history-view-changes')
    await settledOn('history-diff-empty')
  })
})
