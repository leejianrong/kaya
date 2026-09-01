// @vitest-environment jsdom
/**
 * `HistoryPanel.svelte` as rendered — `BacklinksPanel`'s behavioural twin
 * (`tests/backlinks-panel.test.ts`), plus the write `BacklinksPanel` never makes.
 *
 * CLAUDE.md's rule that a structural guard does not cover a behavioural claim is what this file is
 * for: `tests/history.test.ts` proves the five states are five *values*; this proves the component
 * renders them as five different things, and — the part with no unit-level equivalent — that
 * Restore sends the precondition it says it always sends and reacts correctly to both outcomes.
 *
 * No testing library — Svelte's own `mount`/`unmount`/`flushSync`, as everywhere else in this suite.
 */

import { flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import HistoryPanel from '../src/components/HistoryPanel.svelte'
import * as auth from '../src/lib/auth'
import type { Note, NoteVersion } from '../src/lib/types'
import { box } from './reactive.svelte'
import { FAKE_TOKEN } from './token'

function note(ref: string, overrides: Partial<Note> = {}): Note {
  return {
    ref,
    id: Number.parseInt(ref.replace(/\D/g, ''), 10),
    title: `Title ${ref}`,
    body: 'current body',
    path: 'design/adr.md',
    created_at: '2026-08-09T10:00:00+00:00',
    updated_at: '2026-08-09T10:00:00.123456+00:00',
    ...overrides,
  }
}

function version(id: number, overrides: Partial<NoteVersion> = {}): NoteVersion {
  return {
    id,
    body: `body ${id}`,
    created_at: '2026-08-09T10:00:00+00:00',
    ...overrides,
  }
}

let host: HTMLDivElement
const mounted: unknown[] = []
const realFetch = globalThis.fetch

let asked: { url: string; method: string; body: unknown }[]
let versionsAnswer: () => Promise<Response>
let patchAnswer: () => Promise<Response>

function ok(body: unknown): () => Promise<Response> {
  return async () =>
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
}

function refused(status: number, code: string, message: string, extra: object = {}) {
  return async () =>
    new Response(JSON.stringify({ error: { code, message, ...extra } }), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })
}

beforeEach(() => {
  host = document.createElement('div')
  document.body.append(host)
  auth.setToken(FAKE_TOKEN)
  asked = []
  versionsAnswer = ok({ versions: [] })
  patchAnswer = ok(note('NOTE-1', { body: 'restored' }))
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    const body = init?.body ? JSON.parse(String(init.body)) : undefined
    asked.push({ url, method, body })
    return url.endsWith('/versions') ? versionsAnswer() : patchAnswer()
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

interface Handles {
  expired: string[]
  restored: Note[]
  open: (next: Note | null) => void
}

function render(initial: Note | null): Handles {
  const opened = box<Note | null>(initial)
  const expired: string[] = []
  const restored: Note[] = []
  mounted.push(
    mount(HistoryPanel, {
      target: host,
      props: {
        get note() {
          return opened.value
        },
        onexpired: (reason: string) => expired.push(reason),
        onrestored: (stored: Note) => restored.push(stored),
      },
    }),
  )
  flushSync()
  return {
    expired,
    restored,
    open: (next) => {
      opened.value = next
      flushSync()
    },
  }
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

function click(testid: string): void {
  host.querySelector<HTMLButtonElement>(`[data-testid="${testid}"]`)!.click()
  flushSync()
}

describe('the states a note history can be in', () => {
  it('is closed with no note open', () => {
    render(null)
    expect(host.querySelector('[data-testid="history-closed"]')).not.toBeNull()
  })

  it('says empty when the request succeeds with nothing', async () => {
    render(note('NOTE-1'))
    const empty = await settledOn('history-empty')
    expect(empty.textContent).toContain('No saved versions')
  })

  it('lists versions newest first, with a count', async () => {
    versionsAnswer = ok({ versions: [version(3), version(2), version(1)] })
    render(note('NOTE-1'))
    await settledOn('history-versions')

    expect(host.querySelectorAll('[data-testid="history-row"]')).toHaveLength(3)
    expect(host.querySelector('[data-testid="history-count"]')!.textContent).toBe('3')
  })

  it('reports a failure distinctly from empty', async () => {
    versionsAnswer = refused(404, 'note_not_found', 'no such note')
    render(note('NOTE-1'))
    const failed = await settledOn('history-error')
    expect(failed.textContent).toContain('no such note')
    expect(host.querySelector('[data-testid="history-empty"]')).toBeNull()
  })

  it('hands a 401 to onexpired rather than showing it as a failure', async () => {
    versionsAnswer = refused(401, 'authentication_required', 'no credential')
    const handles = render(note('NOTE-1'))
    await vi.waitFor(() => expect(handles.expired).toEqual(['no credential']))
    expect(host.querySelector('[data-testid="history-error"]')).toBeNull()
  })
})

describe('selecting a version previews it, without a second round trip', () => {
  it('shows the full body on click, and hides it again on a second click', async () => {
    versionsAnswer = ok({ versions: [version(1, { body: 'the old text' })] })
    render(note('NOTE-1'))
    await settledOn('history-versions')

    const before = asked.length
    click('history-row')
    const preview = await settledOn('history-preview')
    expect(preview.textContent).toContain('the old text')
    // No new request — the row's full body was already in the list response.
    expect(asked).toHaveLength(before)

    click('history-row')
    expect(host.querySelector('[data-testid="history-preview"]')).toBeNull()
  })
})

describe('restore', () => {
  it('sends the open note’s updated_at as the precondition, and reports the result', async () => {
    versionsAnswer = ok({ versions: [version(1, { body: 'the old text' })] })
    const opened = note('NOTE-1', { updated_at: '2026-08-09T10:05:00.000001+00:00' })
    const handles = render(opened)
    await settledOn('history-versions')
    click('history-row')
    await settledOn('history-preview')

    patchAnswer = ok({ ...opened, body: 'the old text', updated_at: '2026-08-09T10:06:00+00:00' })
    click('history-restore')

    await vi.waitFor(() => expect(handles.restored).toHaveLength(1))
    const [written] = asked.filter((call) => call.method === 'PATCH')
    expect(written.url).toBe('/api/v1/notes/NOTE-1')
    expect(written.body).toEqual({
      body: 'the old text',
      if_updated_at: '2026-08-09T10:05:00.000001+00:00',
    })
    expect(handles.restored[0]?.body).toBe('the old text')
  })

  it('shows a 409 rather than silently doing nothing, and does not call onrestored', async () => {
    versionsAnswer = ok({ versions: [version(1, { body: 'the old text' })] })
    const handles = render(note('NOTE-1'))
    await settledOn('history-versions')
    click('history-row')
    await settledOn('history-preview')

    patchAnswer = refused(409, 'note_conflict', 'NOTE-1 has changed since you read it', {
      attempted: note('NOTE-1'),
      stored: note('NOTE-1'),
    })
    click('history-restore')

    const failure = await settledOn('history-restore-error')
    expect(failure.textContent).toContain('has changed since you read it')
    expect(handles.restored).toEqual([])
  })

  it('is disabled until a version is selected', async () => {
    versionsAnswer = ok({ versions: [version(1)] })
    render(note('NOTE-1'))
    await settledOn('history-versions')

    expect(host.querySelector('[data-testid="history-restore"]')).toBeNull()
  })
})
