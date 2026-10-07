// @vitest-environment jsdom
/**
 * KAN-1823: `Logo.svelte` as rendered, and the icon set `index.html` and the web manifest promise.
 *
 * The second half is a file-existence guard: a favicon link that 404s is invisible in review (the
 * tab just shows a generic globe), and the SPA fallback would answer it with `index.html` rather
 * than an error, so nothing downstream would notice either.
 */
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

import { flushSync, mount, unmount } from 'svelte'
import { afterEach, describe, expect, it } from 'vitest'

import Logo from '../src/components/Logo.svelte'

const ROOT = join(__dirname, '..')
const PUBLIC = join(ROOT, 'public')

let target: HTMLElement | null = null
let component: Record<string, unknown> | null = null

function render(props: { size?: number; title?: string } = {}): SVGSVGElement {
  target = document.createElement('div')
  document.body.append(target)
  component = mount(Logo, { target, props })
  flushSync()
  return target.querySelector('svg') as SVGSVGElement
}

afterEach(() => {
  if (component) unmount(component)
  target?.remove()
  component = null
  target = null
})

describe('Logo.svelte', () => {
  it('is decorative by default: hidden from assistive tech, no name, no role', () => {
    const svg = render()
    expect(svg.getAttribute('aria-hidden')).toBe('true')
    expect(svg.hasAttribute('aria-label')).toBe(false)
    expect(svg.hasAttribute('role')).toBe(false)
  })

  it('becomes a named image when given a title', () => {
    const svg = render({ title: 'kaya' })
    expect(svg.getAttribute('role')).toBe('img')
    expect(svg.getAttribute('aria-label')).toBe('kaya')
    expect(svg.hasAttribute('aria-hidden')).toBe(false)
  })

  it('renders at the requested size, square', () => {
    const svg = render({ size: 72 })
    expect(svg.getAttribute('width')).toBe('72')
    expect(svg.getAttribute('height')).toBe('72')
  })

  it('takes every colour from the --logo-* tokens, never a literal', () => {
    const svg = render()
    const paint = [...svg.querySelectorAll('[fill], [stroke]')].flatMap((el) => [
      el.getAttribute('fill'),
      el.getAttribute('stroke'),
    ])
    const colours = paint.filter((value): value is string => value !== null)
    expect(colours.length).toBeGreaterThan(0)
    for (const colour of colours) expect(colour).toMatch(/^var\(--logo-(k|toast|kaya|lt)\)$/)
  })
})

describe('the icon set', () => {
  const html = readFileSync(join(ROOT, 'index.html'), 'utf8')
  const manifest = JSON.parse(readFileSync(join(PUBLIC, 'manifest.webmanifest'), 'utf8')) as {
    icons: { src: string }[]
    start_url: string
  }

  const fromHtml = [...html.matchAll(/(?:href|content)="(\/[^"]+\.(?:svg|ico|png|webmanifest))"/g)].map(
    (m) => m[1],
  )
  const fromManifest = manifest.icons.map((icon) => icon.src)

  it('index.html links an icon, a touch icon, the manifest and a share image', () => {
    for (const path of [
      '/favicon.svg',
      '/favicon.ico',
      '/apple-touch-icon.png',
      '/manifest.webmanifest',
      '/og.png',
    ]) {
      expect(fromHtml).toContain(path)
    }
  })

  it('every path index.html and the manifest reference exists under public/', () => {
    const paths = [...new Set([...fromHtml, ...fromManifest])]
    expect(paths.length).toBeGreaterThan(5)
    for (const path of paths) {
      expect(existsSync(join(PUBLIC, path)), `${path} is referenced but not in public/`).toBe(true)
    }
  })

  it('the manifest has a maskable icon and starts at /', () => {
    expect(manifest.start_url).toBe('/')
    expect(JSON.stringify(manifest.icons)).toContain('maskable')
  })
})
