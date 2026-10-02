// @vitest-environment jsdom
/**
 * "Format on save" in the editor's save path (KAN-1815), against `EditorPane` as the app mounts it.
 *
 * The server's formatter is KAN-1814's; this file owns what the SPA does around it: send
 * `format: true` while the preference is ON (the default), send nothing extra while it is OFF, and
 * apply the **returned** body through the echo guard as a transaction — never a remount, never a
 * loop, never a second save, and never over keystrokes made while the save was in flight.
 *
 * "Not rebuilt" is node identity (`container.firstElementChild`), the same instrument
 * `editor-pane.test.ts` uses.
 */

import { undo } from '@codemirror/commands'
import { EditorView } from '@codemirror/view'
import { flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import EditorPane from '../src/components/EditorPane.svelte'
import * as auth from '../src/lib/auth'
import { resetPreferencesCache } from '../src/lib/preferences'
import type { Note } from '../src/lib/types'
import { editorArrived } from './editor-arrival'
import { box } from './reactive.svelte'
import { FAKE_TOKEN } from './token'

const READ_AT = '2026-08-09T10:00:00.123456+00:00'
const SAVED_AT = '2026-08-09T10:07:31.987654+00:00'

const UNFORMATTED = '#   Title\n*  one\n*  two\n'
const FORMATTED = '# Title\n\n- one\n- two\n'

function note(overrides: Partial<Note> = {}): Note {
  return {
    ref: 'NOTE-6',
    id: 6,
    title: 'Weekly review',
    body: '',
    path: 'journal/weekly-review.md',
    created_at: '2026-08-09T09:00:00+00:00',
    updated_at: READ_AT,
    team_id: null,
    ...overrides,
  }
}

interface Patch {
  body: Record<string, unknown>
}

let host: HTMLDivElement
const mounted: unknown[] = []
let patches: Patch[]
let preferenceReads: number
let formatOnSavePreference: boolean
/** What the (stubbed) server answers a `PATCH` with. */
let respond: (sent: Record<string, unknown>) => Note | Promise<Note>

beforeEach(() => {
  host = document.createElement('div')
  document.body.append(host)
  auth.setToken(FAKE_TOKEN)
  resetPreferencesCache()
  patches = []
  preferenceReads = 0
  formatOnSavePreference = true
  respond = (sent) =>
    note({
      body: sent.format === true ? FORMATTED : (sent.body as string),
      updated_at: SAVED_AT,
    })

  vi.stubGlobal('fetch', async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? 'GET'
    if (url === '/api/v1/preferences' && method === 'GET') {
      preferenceReads += 1
      return json(200, { format_on_save: formatOnSavePreference })
    }
    if (method === 'PATCH') {
      const body = JSON.parse(String(init.body)) as Record<string, unknown>
      patches.push({ body })
      return json(200, await respond(body))
    }
    return json(200, [])
  })
})

afterEach(() => {
  for (const instance of mounted.splice(0)) {
    unmount(instance as never)
  }
  host.remove()
  auth.clearToken()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function json(status: number, payload: unknown): Response {
  return new Response(JSON.stringify(payload), { status })
}

async function open(initial: Note) {
  const opened = box<Note | null>(initial)
  mounted.push(
    mount(EditorPane, {
      target: host,
      props: {
        get note() {
          return opened.value
        },
        error: null,
      },
    }),
  )
  flushSync()
  await editorArrived(host)
  const container = host.querySelector<HTMLElement>('.editor-host')!
  return { opened, container, view: EditorView.findFromDOM(container.querySelector('.cm-editor')!)! }
}

function typeAtEnd(view: EditorView, text: string): void {
  view.dispatch({
    changes: { from: view.state.doc.length, insert: text },
    userEvent: 'input.type',
  })
  flushSync()
}

function setDocument(view: EditorView, text: string): void {
  view.dispatch({
    changes: { from: 0, to: view.state.doc.length, insert: text },
    userEvent: 'input.type',
  })
  flushSync()
}

const saveButton = () => host.querySelector<HTMLButtonElement>('button')!
const status = () => host.querySelector('[data-testid="save-state"]')?.textContent ?? ''

describe('format on save, ON (the default)', () => {
  it('sends format: true on the one PATCH, with the guard intact', async () => {
    const { view } = await open(note())
    setDocument(view, UNFORMATTED)

    saveButton().click()
    await vi.waitFor(() => expect(patches).toHaveLength(1))

    expect(patches[0].body).toEqual({
      body: UNFORMATTED,
      if_updated_at: READ_AT,
      format: true,
    })
    expect(patches[0].body.if_updated_at).toBe(READ_AT)
  })

  it('reads the preference once at mount, not as part of the save', async () => {
    const { view } = await open(note())
    await vi.waitFor(() => expect(preferenceReads).toBe(1))
    setDocument(view, UNFORMATTED)

    saveButton().click()
    await vi.waitFor(() => expect(patches).toHaveLength(1))

    expect(preferenceReads).toBe(1)
  })

  it('applies the returned formatted body in place: same view, no remount, clean, one save', async () => {
    const { view, container } = await open(note())
    const root = container.firstElementChild
    setDocument(view, UNFORMATTED)

    saveButton().click()
    await vi.waitFor(() => expect(view.state.doc.toString()).toBe(FORMATTED))
    await vi.waitFor(() => expect(status()).toContain('saved'))

    expect(container.firstElementChild).toBe(root)
    expect(EditorView.findFromDOM(container.querySelector('.cm-editor')!)).toBe(view)
    expect(status()).not.toContain('unsaved')
    // No loop: applying the formatted body did not cause a second PATCH.
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(patches).toHaveLength(1)
  })

  it('makes the format a single undo that restores the text as typed', async () => {
    const { view } = await open(note())
    setDocument(view, UNFORMATTED)
    saveButton().click()
    await vi.waitFor(() => expect(view.state.doc.toString()).toBe(FORMATTED))

    undo(view)

    expect(view.state.doc.toString()).toBe(UNFORMATTED)
  })

  it('bases the next save on the stamp the response returned', async () => {
    const { view } = await open(note())
    setDocument(view, UNFORMATTED)
    saveButton().click()
    await vi.waitFor(() => expect(view.state.doc.toString()).toBe(FORMATTED))
    await vi.waitFor(() => expect(status()).toContain('saved'))

    typeAtEnd(view, 'more\n')
    saveButton().click()
    await vi.waitFor(() => expect(patches).toHaveLength(2))

    expect(patches[1].body.if_updated_at).toBe(SAVED_AT)
  })

  it('does not overwrite keystrokes typed while the save was in flight', async () => {
    let release!: () => void
    const gate = new Promise<void>((resolve) => (release = resolve))
    respond = async () => {
      await gate
      return note({ body: FORMATTED, updated_at: SAVED_AT })
    }
    const { view } = await open(note())
    setDocument(view, UNFORMATTED)

    saveButton().click()
    await vi.waitFor(() => expect(patches).toHaveLength(1))
    typeAtEnd(view, 'typed during the save')
    release()
    await vi.waitFor(() => expect(status()).toContain('unsaved'))

    expect(view.state.doc.toString()).toBe(`${UNFORMATTED}typed during the save`)
  })

  it('leaves the caret where it was when the format changed text before it', async () => {
    const { view } = await open(note())
    setDocument(view, UNFORMATTED)
    // The caret sits at the very end, after everything the formatter changes.
    view.dispatch({ selection: { anchor: view.state.doc.length } })

    saveButton().click()
    await vi.waitFor(() => expect(view.state.doc.toString()).toBe(FORMATTED))

    expect(view.state.selection.main.head).toBe(FORMATTED.length)
  })

  it('a body the server stored unchanged dispatches nothing (the echo guard)', async () => {
    respond = (sent) => note({ body: sent.body as string, updated_at: SAVED_AT })
    const { view } = await open(note())
    setDocument(view, FORMATTED)
    let transactions = 0
    const original = view.dispatch.bind(view)
    view.dispatch = ((...args: Parameters<EditorView['dispatch']>) => {
      transactions += 1
      return original(...args)
    }) as EditorView['dispatch']

    saveButton().click()
    await vi.waitFor(() => expect(status()).toContain('saved'))

    expect(transactions).toBe(0)
  })
})

describe('format on save, OFF', () => {
  it('sends no format flag and stores the text byte-for-byte as typed', async () => {
    formatOnSavePreference = false
    const { view } = await open(note())
    await vi.waitFor(() => expect(preferenceReads).toBe(1))
    setDocument(view, UNFORMATTED)

    saveButton().click()
    await vi.waitFor(() => expect(patches).toHaveLength(1))
    await vi.waitFor(() => expect(status()).toContain('saved'))

    expect(patches[0].body).toEqual({ body: UNFORMATTED, if_updated_at: READ_AT })
    expect('format' in patches[0].body).toBe(false)
    expect(view.state.doc.toString()).toBe(UNFORMATTED)
  })
})
