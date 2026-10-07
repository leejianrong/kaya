/**
 * KAN-1828: the colour tokens meet WCAG contrast in both schemes. Pure: it parses `src/tokens.css`
 * and does the arithmetic, no browser. The old accent (#0d9488 on white) was about 3.7:1 and would
 * have failed the first row of this table.
 */

import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const CSS = readFileSync('src/tokens.css', 'utf8')

type Scheme = Record<string, string>

/** Every `--name: #hex;` declaration inside one block's body. */
function declarations(body: string): Scheme {
  const out: Scheme = {}
  for (const match of body.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)) {
    out[match[1]!] = match[2]!.toLowerCase()
  }
  return out
}

/** The light block is the first `:root {...}`; the dark one is `:root` inside the dark media query. */
function schemes(): { light: Scheme; dark: Scheme } {
  const dark = /@media \(prefers-color-scheme: dark\)\s*\{\s*:root\s*\{([\s\S]*?)\n {2}\}\s*\n\}/.exec(CSS)
  const light = /(?:^|\n):root\s*\{([\s\S]*?)\n\}/.exec(CSS)
  if (!dark || !light) throw new Error('tokens.css has no light :root block and dark media block')
  return { light: declarations(light[1]!), dark: declarations(dark[1]!) }
}

function luminance(hex: string): number {
  const channel = (offset: number) => {
    const c = parseInt(hex.slice(offset, offset + 2), 16) / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5)
}

export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number]
  return (hi + 0.05) / (lo + 0.05)
}

/** [foreground, background] role names. Text needs 4.5:1. */
const TEXT_PAIRS: [string, string][] = [
  ['on-primary', 'primary'],
  ['on-primary-container', 'primary-container'],
  ['on-secondary', 'secondary'],
  ['on-secondary-container', 'secondary-container'],
  ['on-tertiary-container', 'tertiary-container'],
  ['on-error', 'error'],
  ['on-error-container', 'error-container'],
  ['on-ok-container', 'ok-container'],
  ['on-warn-container', 'warn-container'],
  ['on-surface', 'surface'],
  ['on-surface-variant', 'surface'],
  ['on-surface', 'surface-container-lowest'],
  ['on-surface', 'surface-container-low'],
  ['on-surface', 'surface-container'],
  ['on-surface', 'surface-container-high'],
  ['on-surface-variant', 'surface-container'],
  ['on-surface-variant', 'surface-container-high'],
  ['on-surface-variant', 'surface-container-highest'],
  ['inverse-on-surface', 'inverse-surface'],
  // Link and accent text sits straight on the page and on the tonal tiers.
  ['primary', 'surface'],
  ['primary', 'surface-container-low'],
  ['primary', 'surface-container'],
  ['error', 'surface'],
  ['ok', 'surface'],
  ['warn', 'surface'],
]

describe.each(['light', 'dark'] as const)('%s scheme', (name) => {
  const scheme = schemes()[name]

  it.each(TEXT_PAIRS)('%s on %s is at least 4.5:1', (fg, bg) => {
    expect(scheme[fg], `--${fg} is missing`).toBeDefined()
    expect(scheme[bg], `--${bg} is missing`).toBeDefined()
    expect(contrast(scheme[fg]!, scheme[bg]!)).toBeGreaterThanOrEqual(4.5)
  })

  it.each([
    ['outline', 'surface'],
    ['outline', 'surface-container-low'],
    ['primary', 'surface-container-high'],
  ])('%s against %s is at least 3:1', (fg, bg) => {
    expect(contrast(scheme[fg]!, scheme[bg]!)).toBeGreaterThanOrEqual(3)
  })
})
