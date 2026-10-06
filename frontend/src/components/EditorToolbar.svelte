<script lang="ts">
  /**
   * KAN-1826: the formatting toolbar above the soft keyboard.
   *
   * Eight plain `<button>`s. It knows the editor only as an `EditorCommands` (`lib/toolbar.ts`), so
   * it imports nothing from CodeMirror, and it is rendered by `App.svelte` beside `EditorPane`, never
   * inside it: the pane owns its container and nothing else.
   *
   * **A button must not take focus.** A tap that moves focus off the editor closes the soft
   * keyboard and the toolbar with it. `preventDefault` on `pointerdown` and `mousedown` stops the
   * focus change (iOS Safari synthesises a `mousedown` after a touch, which is why both are here);
   * `click` still fires and runs the command.
   *
   * It is pinned to the *visible* bottom: `inset` is how far the keyboard covers the layout
   * viewport (`lib/viewport.ts`), and `position: fixed; bottom: inset` lifts it clear. With no
   * `visualViewport` the inset is `0` and it sits at the bottom edge.
   */
  import { KEYBOARD_MIN_INSET } from '../lib/viewport'
  import { TOOLBAR_BUTTONS, type EditorCommands, type ToolbarAction } from '../lib/toolbar'

  const {
    commands,
    inset,
  }: {
    commands: EditorCommands | null
    inset: number
  } = $props()

  // Material "filled" 24px glyphs. `wikilink` has no icon and is drawn as its own syntax.
  const ICONS: Partial<Record<ToolbarAction, string>> = {
    bold: 'M15.6 10.79c.97-.67 1.65-1.77 1.65-2.79 0-2.26-1.75-4-4-4H7v14h7.04c2.09 0 3.71-1.7 3.71-3.79 0-1.52-.86-2.82-2.15-3.42zM10 6.5h3c.83 0 1.5.67 1.5 1.5s-.67 1.5-1.5 1.5h-3v-3zm3.5 9H10v-3h3.5c.83 0 1.5.67 1.5 1.5s-.67 1.5-1.5 1.5z',
    italic: 'M10 4v3h2.21l-3.42 8H6v3h8v-3h-2.21l3.42-8H18V4z',
    list: 'M4 10.5a1.5 1.5 0 100 3 1.5 1.5 0 000-3zm0-6a1.5 1.5 0 100 3 1.5 1.5 0 000-3zm0 12a1.5 1.5 0 100 3 1.5 1.5 0 000-3zM7 19h14v-2H7v2zm0-6h14v-2H7v2zm0-8v2h14V5H7z',
    checkbox:
      'M19 3H5a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2V5a2 2 0 00-2-2zm-9 14l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z',
    code: 'M9.4 16.6L4.8 12l4.6-4.6L8 6l-6 6 6 6 1.4-1.4zm5.2 0l4.6-4.6-4.6-4.6L16 6l6 6-6 6-1.4-1.4z',
    link: 'M3.9 12c0-1.71 1.39-3.1 3.1-3.1h4V7H7c-2.76 0-5 2.24-5 5s2.24 5 5 5h4v-1.9H7c-1.71 0-3.1-1.39-3.1-3.1zM8 13h8v-2H8v2zm9-6h-4v1.9h4c1.71 0 3.1 1.39 3.1 3.1s-1.39 3.1-3.1 3.1h-4V17h4c2.76 0 5-2.24 5-5s-2.24-5-5-5z',
    undo: 'M12.5 8c-2.65 0-5.05.99-6.9 2.6L2 7v9h9l-3.62-3.62c1.39-1.16 3.16-1.88 5.12-1.88 3.54 0 6.55 2.31 7.6 5.5l2.37-.78C21.08 11.03 17.15 8 12.5 8z',
  }

  function keepFocus(event: Event): void {
    event.preventDefault()
  }
</script>

<div
  class="toolbar"
  class:docked={inset < KEYBOARD_MIN_INSET}
  role="toolbar"
  aria-label="Formatting"
  style:bottom="{inset}px"
  data-testid="editor-toolbar"
>
  {#each TOOLBAR_BUTTONS as button (button.action)}
    <button
      type="button"
      class="tool"
      class:apart={button.action === 'undo'}
      aria-label={button.label}
      title={button.label}
      disabled={commands === null}
      data-testid={`tool-${button.action}`}
      onpointerdown={keepFocus}
      onmousedown={keepFocus}
      onclick={() => commands?.run(button.action)}
    >
      {#if button.action === 'wikilink'}
        <span class="glyph" aria-hidden="true">[[ ]]</span>
      {:else}
        <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" focusable="false">
          <path d={ICONS[button.action]} fill="currentColor" />
        </svg>
      {/if}
    </button>
  {/each}
</div>

<style>
  .toolbar {
    position: fixed;
    inset-inline: 0;
    z-index: 20;
    display: flex;
    align-items: stretch;
    border-top: 1px solid var(--outline-variant);
    background: var(--surface-container-high);
  }

  /* No keyboard to sit on: clear the home indicator instead. */
  .toolbar.docked {
    padding-bottom: env(safe-area-inset-bottom, 0px);
  }

  .tool {
    display: flex;
    flex: 1 1 0;
    align-items: center;
    justify-content: center;
    min-width: 2.5rem;
    min-height: 2.75rem;
    padding: 0;
    border: 0;
    border-radius: 0;
    background: transparent;
    color: var(--on-surface);
    cursor: pointer;
    font: inherit;
    touch-action: manipulation;
  }

  .tool:active {
    background: var(--layer-pressed);
  }

  .tool:focus-visible {
    outline: 2px solid var(--primary);
    outline-offset: -2px;
  }

  .tool:disabled {
    color: var(--on-surface-variant);
    cursor: default;
  }

  .tool.apart {
    border-left: 1px solid var(--outline-variant);
  }

  .glyph {
    font-family: var(--mono);
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: -0.02em;
  }
</style>
