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
