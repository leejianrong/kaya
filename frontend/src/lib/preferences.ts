/**
 * `/api/v1/preferences` (KAN-1815) — per-account settings, stored server-side so a choice follows
 * the account across browsers.
 *
 * Plain `apiRequest`, the `lib/auth.ts` bearer like every other note-API call; nothing here touches
 * a credential.
 *
 * **"Format on save" governs browser saves only.** The editor's save path asks
 * {@link formatOnSave} and sends `format: true` on its `PATCH` when the answer is yes; the CLI and
 * MCP never format implicitly.
 *
 * The answer is cached for the life of the page (one `GET`, started when the editor mounts), because
 * a save must not pay a round trip to learn something that changes only on the Settings page, which
 * writes the cache itself ({@link rememberFormatOnSave}). A change made in another browser is seen
 * after a reload. **A failed read is not cached and answers the default, `true`**: absent means ON everywhere in kaya, and a save should behave the
 * same whether or not the preference read happened to succeed.
 */

import { apiRequest, type RequestOptions } from './api'

type Options = Pick<RequestOptions, 'signal' | 'fetchImpl'>

export interface Preferences {
  format_on_save: boolean
}

/** What an account that never chose gets, and what a failed read falls back to. */
export const DEFAULT_FORMAT_ON_SAVE = true

export function fetchPreferences(options: Options = {}): Promise<Preferences> {
  return apiRequest<Preferences>('preferences', options)
}

export function updatePreferences(
  patch: Partial<Preferences>,
  options: Options = {},
): Promise<Preferences> {
  return apiRequest<Preferences>('preferences', { ...options, method: 'PATCH', body: patch })
}

let pending: Promise<boolean> | null = null

/**
 * Start (or join) the one read of the account's "format on save" choice.
 *
 * The editor primes this when it mounts, so by the time anyone saves it has settled and
 * {@link formatOnSave} adds **no request of its own** to a save — "a save is one request, and the
 * client never reads before it writes" (ADR 0009's rule, pinned by `editor-pane.test.ts`) still
 * holds. A failed read answers the default and is forgotten, so the next prime retries.
 */
export function primePreferences(options: Options = {}): Promise<boolean> {
  if (pending === null) {
    const attempt: Promise<boolean> = fetchPreferences(options).then(
      (read) =>
        typeof read.format_on_save === 'boolean' ? read.format_on_save : DEFAULT_FORMAT_ON_SAVE,
      () => {
        if (pending === attempt) {
          pending = null
        }
        return DEFAULT_FORMAT_ON_SAVE
      },
    )
    pending = attempt
  }
  return pending
}

/** Whether a browser save should send `format: true`. */
export function formatOnSave(): Promise<boolean> {
  return primePreferences()
}

/** The Settings page's write-through, so the next save sees the choice without a refetch. */
export function rememberFormatOnSave(value: boolean): void {
  pending = Promise.resolve(value)
}

/** Forget the cached answer (sign-out, and tests). */
export function resetPreferencesCache(): void {
  pending = null
}

/**
 * KAN-1997, "Full-width reading": how wide the Read column may be.
 *
 * **A per-browser preference, not an account one** (`/api/v1/preferences` knows only
 * `format_on_save`, and a column width is a fact about a screen, not an account): it lives in
 * `localStorage`, like the pane and mode choices in `lib/shell.ts` and `lib/noteMode.ts`, and a
 * blocked or throwing `localStorage` just means the default.
 */

/** The Read measure, in `ch`: the one place the number is written. `App.svelte` hands it to CSS as
 *  `--reading-measure` (a stylesheet cannot import it), and a full-width reader gets `none`. */
export const READING_MEASURE_CH = 75

const FULL_WIDTH_KEY = 'kaya.reading.fullWidth'

/** The CSS value for `--reading-measure`. Pure, so the default and the off-switch are tested. */
export function readingMeasure(fullWidth: boolean): string {
  return fullWidth ? 'none' : `${READING_MEASURE_CH}ch`
}

/** Whether Read is full width. Anything but the stored `'1'` (including no storage) is `false`. */
export function readFullWidthReading(): boolean {
  try {
    return globalThis.localStorage?.getItem(FULL_WIDTH_KEY) === '1'
  } catch {
    return false
  }
}

const listeners = new Set<(fullWidth: boolean) => void>()

/** Store the choice and tell this page's subscribers (`storage` events only reach other tabs). */
export function writeFullWidthReading(fullWidth: boolean): void {
  try {
    globalThis.localStorage?.setItem(FULL_WIDTH_KEY, fullWidth ? '1' : '0')
  } catch {
    // Unwritable storage: the choice still applies for this page's life through the listeners.
  }
  for (const listener of listeners) {
    listener(fullWidth)
  }
}

/** Follow the choice: this page's writes and, through `storage`, another tab's. Returns the unsubscribe. */
export function watchFullWidthReading(listener: (fullWidth: boolean) => void): () => void {
  listeners.add(listener)
  const onStorage = (event: StorageEvent): void => {
    if (event.key === FULL_WIDTH_KEY || event.key === null) {
      listener(readFullWidthReading())
    }
  }
  globalThis.addEventListener?.('storage', onStorage)
  return () => {
    listeners.delete(listener)
    globalThis.removeEventListener?.('storage', onStorage)
  }
}
