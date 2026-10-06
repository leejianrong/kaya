// @vitest-environment jsdom
/**
 * KAN-1826: `EditorToolbar.svelte`'s contract with the editor it drives and the keyboard it sits on.
 * The text rules are `formatting.test.ts`; this is the button wiring.
 */
import { readFileSync } from 'node:fs'

import { flushSync, mount, unmount } from 'svelte'
import { afterEach, describe, expect, it, vi } from 'vitest'

import EditorToolbar from '../src/components/EditorToolbar.svelte'
import type { EditorCommands } from '../src/lib/toolbar'

let target: HTMLElement | null = null
let component: Record<string, unknown> | null = null

afterEach(() => {
  if (component) unmount(component)
  target?.remove()
  component = null
  target = null
})

function render(commands: EditorCommands | null, inset = 0): HTMLElement {
  target = document.createElement('div')
  document.body.append(target)
  component = mount(EditorToolbar, { target, props: { commands, inset } })
  flushSync()
  return target
}

const commands = (): EditorCommands => ({ run: vi.fn(), revealCaret: vi.fn() })

describe('EditorToolbar', () => {
  it('is a toolbar of eight type=button buttons with accessible names', () => {
    const host = render(commands())
    expect(host.querySelector('[role="toolbar"]')?.getAttribute('aria-label')).toBe('Formatting')
    const buttons = [...host.querySelectorAll('button')]
    expect(buttons.map((b) => b.getAttribute('aria-label'))).toEqual([
      'Bold',
      'Italic',
      'Bulleted list',
      'Checkbox list',
      'Code',
      'Link',
      'Wikilink',
      'Undo',
    ])
    for (const button of buttons) {
      expect(button.type).toBe('button')
    }
  })

  it('runs the matching command on click', () => {
    const live = commands()
    const host = render(live)
    host.querySelector<HTMLButtonElement>('[data-testid="tool-checkbox"]')!.click()
    host.querySelector<HTMLButtonElement>('[data-testid="tool-undo"]')!.click()
    expect(live.run).toHaveBeenNthCalledWith(1, 'checkbox')
    expect(live.run).toHaveBeenNthCalledWith(2, 'undo')
  })

  it.each(['pointerdown', 'mousedown'])(
    'refuses focus on %s, so the editor keeps it and the keyboard stays up',
    (type) => {
      const host = render(commands())
      for (const button of host.querySelectorAll('button')) {
        const event = new Event(type, { bubbles: true, cancelable: true })
        button.dispatchEvent(event)
        expect(event.defaultPrevented, button.getAttribute('aria-label') ?? '').toBe(true)
      }
    },
  )

  it('sits on the keyboard: bottom is the inset', () => {
    const host = render(commands(), 300)
    const bar = host.querySelector<HTMLElement>('[data-testid="editor-toolbar"]')!
    expect(bar.style.bottom).toBe('300px')
    expect(bar.classList.contains('docked')).toBe(false)
  })

  it('docks to the screen edge when there is no keyboard', () => {
    const host = render(commands(), 0)
    const bar = host.querySelector<HTMLElement>('[data-testid="editor-toolbar"]')!
    expect(bar.style.bottom).toBe('0px')
    expect(bar.classList.contains('docked')).toBe(true)
  })

  it('does nothing and disables its buttons while there is no editor', () => {
    const host = render(null)
    for (const button of host.querySelectorAll('button')) {
      expect(button.disabled).toBe(true)
    }
  })

  it('never imports CodeMirror', () => {
    const source = readFileSync('src/components/EditorToolbar.svelte', 'utf8')
    expect(source).not.toMatch(/@codemirror/)
  })
})
