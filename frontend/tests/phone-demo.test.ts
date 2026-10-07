// @vitest-environment jsdom
/**
 * `PhoneDemo.svelte` (KAN-1822): the landing page's mock phone. It is a labelled, decorative group
 * with a real two-button Read / Edit switch, and exactly one screen is rendered at a time.
 */
import { flushSync, mount, unmount } from 'svelte'
import { afterEach, describe, expect, it } from 'vitest'

import PhoneDemo from '../src/components/PhoneDemo.svelte'

let target: HTMLElement | null = null
let component: Record<string, unknown> | null = null

function render(): HTMLElement {
  target = document.createElement('div')
  document.body.append(target)
  component = mount(PhoneDemo, { target })
  flushSync()
  return target
}

afterEach(() => {
  if (component) unmount(component)
  target?.remove()
  component = null
  target = null
})

const button = (host: HTMLElement, name: string): HTMLButtonElement =>
  Array.from(host.querySelectorAll('button')).find(
    (b) => b.textContent?.trim() === name,
  ) as HTMLButtonElement

describe('PhoneDemo', () => {
  it('is one labelled group with decorative icons and no links', () => {
    const host = render()
    const group = host.querySelector('[data-testid="phone-demo"]')!
    expect(group.getAttribute('role')).toBe('group')
    expect(group.getAttribute('aria-label')).toBe('Note preview demo')
    expect(host.querySelectorAll('a')).toHaveLength(0)
    for (const svg of host.querySelectorAll('svg')) {
      expect(svg.closest('[aria-hidden="true"]')).not.toBeNull()
    }
    expect(host.querySelector('[role="group"][aria-label="View mode"]')).not.toBeNull()
  })

  it('starts in Read and shows only that mode', () => {
    const host = render()
    expect(button(host, 'Read').getAttribute('aria-pressed')).toBe('true')
    expect(button(host, 'Edit').getAttribute('aria-pressed')).toBe('false')
    expect(host.querySelector('[data-testid="phone-read"]')).not.toBeNull()
    expect(host.querySelector('[data-testid="phone-edit"]')).toBeNull()
  })

  it('switches to Edit with aria-pressed following, and back, one mode at a time', () => {
    const host = render()
    button(host, 'Edit').click()
    flushSync()
    expect(button(host, 'Edit').getAttribute('aria-pressed')).toBe('true')
    expect(button(host, 'Read').getAttribute('aria-pressed')).toBe('false')
    expect(host.querySelector('[data-testid="phone-read"]')).toBeNull()
    expect(host.querySelector('[data-testid="phone-edit"]')?.textContent).toContain(
      '[[Retro notes]]',
    )

    button(host, 'Read').click()
    flushSync()
    expect(host.querySelector('[data-testid="phone-edit"]')).toBeNull()
    expect(host.querySelector('[data-testid="phone-read"]')).not.toBeNull()
  })

  it('uses real buttons, so Enter and Space work through the native click', () => {
    const host = render()
    for (const b of host.querySelectorAll('button')) {
      expect(b.getAttribute('type')).toBe('button')
    }
  })

  it('Graph in the bottom bar shows the graph, and Notes returns to the last note mode', () => {
    const host = render()
    button(host, 'Edit').click()
    flushSync()
    button(host, 'Graph').click()
    flushSync()
    expect(host.querySelector('[data-testid="phone-graph"]')).not.toBeNull()
    expect(host.querySelector('[data-testid="phone-edit"]')).toBeNull()
    expect(host.querySelector('.seg')).toBeNull()

    button(host, 'Notes').click()
    flushSync()
    expect(host.querySelector('[data-testid="phone-edit"]')).not.toBeNull()
    expect(host.querySelector('[data-testid="phone-graph"]')).toBeNull()
  })
})
