// @vitest-environment jsdom
/** `NavColumn.svelte` carries one decorative icon per destination (KAN-1822). */
import { flushSync, mount, unmount } from 'svelte'
import { afterEach, describe, expect, it } from 'vitest'

import NavColumn from '../src/components/NavColumn.svelte'

let target: HTMLElement | null = null
let component: Record<string, unknown> | null = null

afterEach(() => {
  if (component) unmount(component)
  target?.remove()
  component = null
  target = null
})

describe('NavColumn icons', () => {
  it('renders three aria-hidden icons, one per labelled destination', () => {
    target = document.createElement('div')
    document.body.append(target)
    component = mount(NavColumn, { target, props: { route: { name: 'home' } as never } })
    flushSync()

    const items = Array.from(target.querySelectorAll('[data-testid^="nav-item-"]'))
    expect(items.map((i) => i.querySelector('.nav-label')?.textContent)).toEqual([
      'Notes',
      'Graph',
      'Settings',
    ])
    for (const item of items) {
      const icons = item.querySelectorAll('svg')
      expect(icons).toHaveLength(1)
      expect(icons[0].getAttribute('aria-hidden')).toBe('true')
    }
    expect(target.querySelectorAll('svg')).toHaveLength(3)
    // The icon is decoration: the link's accessible text is still just the label.
    expect(items[0].textContent?.trim()).toBe('Notes')
  })
})
