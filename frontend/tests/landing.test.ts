// @vitest-environment jsdom
/**
 * The landing state, the one-time PAT paste, and the `401` you must be able to walk out of
 * (KAN-555).
 *
 * ## Why this file asserts over the DOM rather than over return values
 *
 * `tests/auth.test.ts` sweeps every four-character fragment of a fake token across everything the
 * credential seam *exposes*, and it stays green while a component renders the token into a `<p>`.
 * That is CLAUDE.md's rule about structural guards turned on this card: the seam's sweep proves the
 * seam, and nothing else. This card adds three surfaces the seam cannot see — the rendered landing
 * page, the form during and after a paste, and the error state after a bad token — so the sweep here
 * runs over `document.body.innerHTML`, over every `href` in the page, and over every URL the app
 * hands to `fetch`.
 *
 * ## Where the credential legitimately *is*
 *
 * Mid-paste it is in the input's `value` **property**, which is unavoidable — it is the field the
 * person is typing into. It is not in the serialized HTML, because Svelte's `bind:value` writes the
 * property and never the attribute, and the serialized HTML is what a devtools "copy element", an
 * HTML snapshot and a bug report all carry. `holds the token only as a value property` asserts both
 * halves of that on purpose: if the sweep ever stopped being able to tell the difference, it would
 * be passing for the wrong reason.
 *
 * ## If you re-run this sweep by hand against a *live* PAT, read this first
 *
 * It will report hits, and they are not leaks. A real credential is prefixed `pandan_pat_` (or
 * `kanban_pat_`, still accepted — pandan ADR 0018), and this page has to say the word **pandan**: it
 * is the name of the product identity comes from. So a whole-token sweep finds `pand`, `anda` and
 * `ndan` in the prose, by construction, on a page that leaks nothing. Measured against the live PAT
 * on 2026-08-11: six hit ranges on the landing page and the same six mid-paste, **all confined to
 * the 11-character published prefix**, and **zero** hits of the 43-character secret portion in
 * either state — the useful sweep is the one over `PAT.slice(PAT.indexOf('_pat_') + 5)`.
 *
 * The fake credential in `tests/token.ts` has the `kanban_` spelling, so the sweep in this file can
 * run over the *whole* token and does. That is also why `Landing.svelte`'s copy says "the board"
 * rather than "the kanban board" — that collision is real too, and the comment there says so.
 */

import { type Component, flushSync, mount, unmount } from 'svelte'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from '../src/App.svelte'
import Landing from '../src/components/Landing.svelte'
import * as auth from '../src/lib/auth'
import { FAKE_TOKEN, fragments } from './token'

const PANDAN = 'https://pandan.example.test'

const NOTE = {
  ref: 'NOTE-6',
  id: 6,
  title: 'Weekly review',
  body: '# Week of 2026-08-03\n',
  path: 'journal/2026/08/weekly-review.md',
  created_at: '2026-08-09T10:00:00+00:00',
  updated_at: '2026-08-09T10:00:00.123456+00:00',
}

interface Call {
  url: string
  init: RequestInit | undefined
}

let host: HTMLDivElement
let calls: Call[]
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
  calls = []
  notesAnswer = () => jsonResponse(200, { notes: [NOTE] })

  // The ambient `fetch`, not an injected one: the components under test reach the network through
  // `lib/api.ts` with no seam for a test to pass a fake through, and inventing one would be a
  // production parameter that exists for this file.
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    calls.push({ url, init })
    if (url === '/api/v1/meta') {
      return jsonResponse(200, { pandan_url: PANDAN })
    }
    if (url === '/api/v1/notes') {
      return notesAnswer()
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

/** Wait for the effects and the promises they started to settle. */
async function settle(): Promise<void> {
  for (let turn = 0; turn < 10; turn += 1) {
    await Promise.resolve()
    flushSync()
  }
}

function field(): HTMLInputElement {
  const input = host.querySelector<HTMLInputElement>('[data-testid="paste-form"] input')
  expect(input).not.toBeNull()
  return input!
}

/** Type into the field the way a paste does: set the value, then let Svelte hear about it. */
function type(value: string): void {
  const input = field()
  input.value = value
  input.dispatchEvent(new Event('input', { bubbles: true }))
  flushSync()
}

function submitForm(): void {
  const form = host.querySelector<HTMLFormElement>('[data-testid="paste-form"]')!
  form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
  flushSync()
}

/**
 * Every surface this card is responsible for, as one string per surface.
 *
 * The `Authorization` header is deliberately **not** in here: the token belongs in exactly one
 * place, and that is it. Everything else — the serialized page, the links, the request URLs — is
 * swept.
 */
function surfaces(): Record<string, string> {
  const hrefs = Array.from(document.querySelectorAll('[href]'))
    .map((element) => element.getAttribute('href') ?? '')
    .join('|')
  return {
    'serialized HTML': document.body.innerHTML,
    'rendered text': document.body.textContent ?? '',
    'every href': hrefs,
    'every request URL': calls.map((call) => call.url).join('|'),
  }
}

/** No four-character fragment of the token in any of them. */
function sweep(): void {
  const found = surfaces()
  for (const fragment of fragments(FAKE_TOKEN)) {
    for (const [where, text] of Object.entries(found)) {
      if (text.includes(fragment)) {
        // Thrown by hand so the failure names the surface and the fragment length rather than
        // dumping a page of HTML with an unexplained `false`.
        throw new Error(
          `${where} leaked a ${fragment.length}-character fragment of the credential: ${fragment}`,
        )
      }
    }
  }
}

describe('the landing state', () => {
  it('says what kaya is, and that identity comes from pandan', async () => {
    render(Landing, { rejected: null, onaccept: () => {} })
    await settle()

    const text = host.textContent ?? ''
    expect(text).toContain('markdown notes')
    expect(text).toContain('kaya mints no credentials of its own')
    expect(text).toContain('Tokens')
  })

  it('builds the link to mint a token from GET /api/v1/meta', async () => {
    render(Landing, { rejected: null, onaccept: () => {} })
    await settle()

    expect(calls.map((call) => call.url)).toContain('/api/v1/meta')
    const links = Array.from(host.querySelectorAll('a')).map((a) => a.getAttribute('href'))
    expect(links).toContain(`${PANDAN}/`)
    expect(host.querySelector('a')?.getAttribute('rel')).toBe('noopener noreferrer')
  })

  it('carries no hard-coded pandan origin, so a self-hosted one is reachable (ADR 0002)', async () => {
    render(Landing, { rejected: null, onaccept: () => {} })
    await settle()

    // The real deployment's origin must not appear anywhere in the rendered page: it comes from the
    // backend's `KAYA_PANDAN_URL`, and a literal here would send a self-hoster to somebody else's
    // board. `simple-kanban-jian` is the string a hard-coded fallback would be spelled with.
    expect(document.body.innerHTML).not.toContain('simple-kanban-jian')
  })

  it('degrades to instructions with no link when /api/v1/meta cannot be reached', async () => {
    globalThis.fetch = vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }) as unknown as typeof fetch

    render(Landing, { rejected: null, onaccept: () => {} })
    await settle()

    expect(host.textContent).toContain('Open your pandan deployment')
    expect(host.querySelector('a')).toBeNull()
    // Still usable: a visitor who already has a token does not need the link at all.
    expect(host.querySelector('[data-testid="paste-form"]')).not.toBeNull()
  })
})

describe('the paste form', () => {
  it('is never a GET, and its field cannot be serialized into a URL', () => {
    render(Landing, { rejected: null, onaccept: () => {} })

    const form = host.querySelector<HTMLFormElement>('[data-testid="paste-form"]')!
    // A form with no method submits as GET, which puts the credential in the address bar, in
    // history and in the backend's request line.
    expect(form.getAttribute('method')).toBe('post')
    expect(form.method).not.toBe('get')

    const input = field()
    // No `name` — an unnamed field is not serialized at all, so even a submission that escaped
    // `preventDefault()` would carry nothing. This is the guard that does not depend on a handler.
    expect(input.getAttribute('name')).toBeNull()
    expect(input.type).toBe('password')
    expect(input.getAttribute('autocomplete')).toBe('off')
    expect(input.getAttribute('spellcheck')).toBe('false')
  })

  it('holds the token only as a value property, never in the serialized HTML', () => {
    render(Landing, { rejected: null, onaccept: () => {} })
    type(FAKE_TOKEN)

    // Both halves on purpose. The first says the field really does hold the credential mid-paste —
    // without it this test would pass against a form that dropped the input. The second is the
    // property that matters: `bind:value` writes the property, so the credential is absent from the
    // HTML a devtools copy, a snapshot or a bug report would carry.
    expect(field().value).toBe(FAKE_TOKEN)
    sweep()
  })

  it('stores a usable paste and clears the field', () => {
    const onaccept = vi.fn()
    render(Landing, { rejected: null, onaccept })

    type(FAKE_TOKEN)
    submitForm()

    expect(auth.credentialState()).toBe('set')
    expect(onaccept).toHaveBeenCalledTimes(1)
    expect(field().value).toBe('')
    sweep()
  })

  it('does not store an unusable paste, and says nothing about what was pasted', () => {
    const onaccept = vi.fn()
    render(Landing, { rejected: null, onaccept })

    // A **tab**, not the `\r\n` the seam's own test uses, and the difference is a finding rather
    // than a preference: HTML's value sanitization algorithm strips CR and LF from a single-line
    // input, so `${FAKE_TOKEN}\r\nX-Injected: 1` arrives at the handler as one usable line and
    // gets stored. Header injection is therefore not reachable *through this field* — see the test
    // below, which pins that so nobody "fixes" this by pasting a newline and finding it works. A
    // tab survives sanitization and is refused by `isUsableToken` like any other C0 character.
    for (const unusable of ['   ', `${FAKE_TOKEN}\tX-Injected: 1`]) {
      type(unusable)
      submitForm()

      expect(auth.credentialState()).toBe('not set')
      expect(onaccept).not.toHaveBeenCalled()
      expect(host.querySelector('[data-testid="problem"]')?.textContent).toContain(
        'cannot be used as a credential',
      )
      // The field is cleared even on the failure path: a rejected credential left in a text box is
      // the same screen-share exposure as an accepted one.
      expect(field().value).toBe('')
      sweep()
    }
  })

  it('cannot carry a newline into a header, because the field itself strips one', () => {
    // The credential seam refuses a control character so a `\r\n` cannot reach `fetch` and split a
    // request (`tests/auth.test.ts`). This asserts the *other* layer, one nobody wrote: a
    // single-line `<input>` runs HTML's value sanitization algorithm, which deletes CR and LF
    // before any handler sees the value. So the seam's refusal is a backstop here rather than the
    // guard, and a reader who tries to demonstrate the injection through this form will find the
    // newline already gone. Written down because "I pasted a newline and it worked" is otherwise a
    // confusing five minutes.
    render(Landing, { rejected: null, onaccept: () => {} })

    type('one\r\ntwo\tthree')

    expect(field().value).toBe('onetwo\tthree')
  })
})

describe('pasting a token, end to end through the shell', () => {
  it('reaches the note list without a reload', async () => {
    render(App, {})
    await settle()

    expect(host.querySelector('nav')).toBeNull()
    expect(host.querySelector('[data-testid="credential-state"]')?.textContent).toBe(
      'token not set',
    )

    type(FAKE_TOKEN)
    submitForm()
    await settle()

    // The same mounted App instance now shows the list: no reload, no remount.
    expect(host.querySelector('nav')).not.toBeNull()
    expect(host.textContent).toContain('Weekly review')
    expect(host.querySelector('[data-testid="paste-form"]')).toBeNull()
    expect(host.querySelector('[data-testid="credential-state"]')?.textContent).toBe('token set')

    // The credential went out as a header on the list request, and nowhere else.
    const list = calls.find((call) => call.url === '/api/v1/notes')!
    expect((list.init?.headers as Record<string, string>).Authorization).toBe(
      `Bearer ${FAKE_TOKEN}`,
    )
    sweep()
  })

  it('recovers from a 401 instead of stranding the visitor', async () => {
    notesAnswer = () => refusal(401, 'invalid_token', 'pandan did not accept this token')

    render(App, {})
    await settle()
    type(FAKE_TOKEN)
    submitForm()
    await settle()

    // Back on the landing state, with the credential gone from the tab rather than left there to
    // fail on every subsequent request.
    expect(auth.credentialState()).toBe('not set')
    expect(host.querySelector('[data-testid="credential-state"]')?.textContent).toBe(
      'token not set',
    )
    expect(host.querySelector('[data-testid="rejected"]')?.textContent).toContain(
      'pandan did not accept this token',
    )
    expect(host.querySelector('nav')).toBeNull()
    sweep()

    // And the way out is *usable*: a second paste, with the API answering properly this time,
    // reaches the list. A `401` state that needs devtools to leave is the bug this asserts against.
    const form = host.querySelector<HTMLFormElement>('[data-testid="paste-form"]')
    expect(form).not.toBeNull()
    expect(field().value).toBe('')

    notesAnswer = () => jsonResponse(200, { notes: [NOTE] })
    type(FAKE_TOKEN)
    submitForm()
    await settle()

    expect(host.textContent).toContain('Weekly review')
    sweep()
  })

  it('offers a way out while a credential is held, for the failures a 401 does not cover', async () => {
    // A `503` from a sleeping pandan, or a valid token for the wrong account, leaves a visitor
    // looking at a failure with a credential the app still believes in. The header's button is the
    // only thing between that and devtools.
    notesAnswer = () => refusal(503, 'upstream_unavailable', 'pandan is unreachable')
    auth.setToken(FAKE_TOKEN)

    render(App, {})
    await settle()

    expect(host.querySelector('nav')).not.toBeNull()
    const clear = host.querySelector<HTMLButtonElement>('[data-testid="clear-token"]')
    expect(clear).not.toBeNull()

    clear!.click()
    flushSync()

    expect(auth.credentialState()).toBe('not set')
    expect(host.querySelector('[data-testid="paste-form"]')).not.toBeNull()
    // A deliberate clear explains nothing: there is no refusal to report.
    expect(host.querySelector('[data-testid="rejected"]')).toBeNull()
    sweep()
  })
})
