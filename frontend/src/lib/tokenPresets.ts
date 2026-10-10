/**
 * The token presets a person can pick (KAY-141, mirroring pandan ADR 0027's `read` / `write` /
 * `write-no-delete`). The wire value is the backend's `scope` string; this module owns only the
 * plain-language words shown for it, so the select, the list chip and the consent text cannot
 * drift apart. The enforcement lives in the backend's `get_principal`, never here.
 */

import type { TokenScope } from './identity'

export interface TokenPreset {
  scope: TokenScope
  label: string
  description: string
}

/** Ordered from most to least capable; the first is the default for a new token. */
export const TOKEN_PRESETS: readonly TokenPreset[] = [
  {
    scope: 'write',
    label: 'Full access',
    description: 'Can read, create, edit, move and delete notes.',
  },
  {
    scope: 'write-no-delete',
    label: 'No delete',
    description: 'Can read, create, edit and move notes, but can never delete one.',
  },
  {
    scope: 'read',
    label: 'Read only',
    description: 'Can read notes and search; cannot change anything.',
  },
]

/** The preset for a scope string. An unknown value (a newer server) falls back to showing the raw
 * string, so a list never hides a token behind a blank chip. */
export function presetFor(scope: string): TokenPreset {
  return (
    TOKEN_PRESETS.find((preset) => preset.scope === scope) ?? {
      scope: scope as TokenScope,
      label: scope,
      description: '',
    }
  )
}

/** Narrow an untrusted string (a URL query parameter) to a known scope, defaulting to `write`. */
export function parseScope(value: string | null): TokenScope {
  return TOKEN_PRESETS.find((preset) => preset.scope === value)?.scope ?? 'write'
}
