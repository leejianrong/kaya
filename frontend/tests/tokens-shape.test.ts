/**
 * KAN-1828: the shape of the token layer. Every role has a light and a dark value, the type, shape
 * and state-layer scales exist, and no component paints with a raw colour (colours come from
 * `src/tokens.css`, so a theme change is one file). Pure file reads, no browser.
 */

import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const CSS = readFileSync('src/tokens.css', 'utf8')
const dark = /@media \(prefers-color-scheme: dark\)\s*\{\s*:root\s*\{([\s\S]*?)\n  \}\s*\n\}/.exec(CSS)
const light = /(?:^|\n):root\s*\{([\s\S]*?)\n\}/.exec(CSS)

function colourNames(body: string): string[] {
  return [...body.matchAll(/--([a-z0-9-]+):\s*#[0-9a-fA-F]{6}\s*;/g)].map((m) => m[1]!)
}

const ROLES = [
  'primary', 'on-primary', 'primary-container', 'on-primary-container',
  'secondary', 'on-secondary', 'secondary-container', 'on-secondary-container',
  'tertiary', 'on-tertiary-container', 'tertiary-container',
  'error', 'on-error', 'error-container', 'on-error-container',
  'ok', 'ok-container', 'on-ok-container', 'warn', 'warn-container', 'on-warn-container',
  'surface', 'on-surface', 'on-surface-variant', 'outline', 'outline-variant',
  'surface-container-lowest', 'surface-container-low', 'surface-container',
  'surface-container-high', 'surface-container-highest',
  'inverse-surface', 'inverse-on-surface', 'inverse-primary', 'scrim', 'shadow',
]

describe('tokens.css', () => {
  it('has a light and a dark block', () => {
    expect(light).not.toBeNull()
    expect(dark).not.toBeNull()
  })

  it.each(ROLES)('--%s has a light and a dark value', (role) => {
    expect(colourNames(light![1]!)).toContain(role)
    expect(colourNames(dark![1]!)).toContain(role)
  })

  it('the dark block overrides exactly the colours the light block defines', () => {
    expect(colourNames(dark![1]!).sort()).toEqual(colourNames(light![1]!).sort())
  })

  it('records the seed and the generation command', () => {
    expect(CSS).toContain('#0d9488')
    expect(CSS).toContain('@material/material-color-utilities@0.3.0')
  })

  it.each([
    'display-large', 'headline-medium', 'title-large', 'title-medium', 'body-large', 'body-medium',
    'body-small', 'label-large', 'label-medium', 'label-small',
  ])('has the %s type role (size, line height, weight)', (role) => {
    for (const part of ['size', 'line', 'weight']) expect(CSS).toContain(`--type-${role}-${part}:`)
  })

  it.each([
    ['shape-xs', '4px'], ['shape-sm', '8px'], ['shape-md', '12px'], ['shape-lg', '16px'],
    ['shape-xl', '28px'], ['shape-full', '9999px'],
  ])('shape %s is %s', (name, value) => {
    expect(CSS).toMatch(new RegExp(`--${name}:\\s*${value}\\s*;`))
  })

  it('has the state-layer opacities', () => {
    expect(CSS).toMatch(/--state-hover:\s*0\.08/)
    expect(CSS).toMatch(/--state-focus:\s*0\.1\b/)
    expect(CSS).toMatch(/--state-pressed:\s*0\.1\b/)
    expect(CSS).toMatch(/--state-disabled-content:\s*0\.38/)
    expect(CSS).toMatch(/--state-disabled-container:\s*0\.12/)
  })
})

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    return statSync(path).isDirectory() ? walk(path) : [path]
  })
}

/** Files that may spell a colour out: the token file, and nothing else. Add to this list on purpose. */
const RAW_COLOUR_ALLOWED = new Set(['src/tokens.css'])

function withoutComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/<!--[\s\S]*?-->/g, '').replace(/^\s*\/\/.*$/gm, '')
}

describe('no raw colours outside tokens.css', () => {
  const files = walk('src').filter((f) => /\.(svelte|css|ts)$/.test(f) && !RAW_COLOUR_ALLOWED.has(f))

  it.each(files)('%s', (file) => {
    const source = withoutComments(readFileSync(file, 'utf8'))
    const raw = source.match(/#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b(?![\w-])|\brgba?\(|\bhsla?\(/g)
    expect(raw, `${file} spells a colour out; use a token`).toBeNull()
  })
})
