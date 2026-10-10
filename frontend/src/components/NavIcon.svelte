<!--
  The icons the bottom bar, the rail, the top bar and the landing page's phone demo share
  (KAN-1822, KAN-1995). Material Symbols (Outlined, weight 400) from `@material-symbols/svg-400`,
  one file per icon, imported with Vite's `?raw` so only the icons used end up in the bundle
  (nothing is fetched at runtime and the whole icon set is never loaded). Drawn in `currentColor`
  so the owner's colour tokens restyle them. Always decorative: the label beside each one carries
  the name.
-->
<script lang="ts" module>
  import hub from '@material-symbols/svg-400/outlined/hub.svg?raw'
  import description from '@material-symbols/svg-400/outlined/description.svg?raw'
  import settings from '@material-symbols/svg-400/outlined/settings.svg?raw'
  import add from '@material-symbols/svg-400/outlined/add.svg?raw'
  import rightPanelOpen from '@material-symbols/svg-400/outlined/right_panel_open.svg?raw'
  import rightPanelClose from '@material-symbols/svg-400/outlined/right_panel_close.svg?raw'

  import leftPanelOpen from '@material-symbols/svg-400/outlined/left_panel_open.svg?raw'
  import leftPanelClose from '@material-symbols/svg-400/outlined/left_panel_close.svg?raw'

  export type IconName =
    | 'notes'
    | 'graph'
    | 'settings'
    | 'panel'
    | 'panel-open'
    | 'left-open'
    | 'left-close'
    | 'add'

  /** The one `d` attribute of a Material Symbols file. A path is data here, never markup. */
  function pathOf(svg: string): string {
    return /<path d="([^"]+)"/.exec(svg)?.[1] ?? ''
  }

  const PATHS: Record<IconName, string> = {
    notes: pathOf(description),
    graph: pathOf(hub),
    settings: pathOf(settings),
    panel: pathOf(rightPanelOpen),
    'panel-open': pathOf(rightPanelClose),
    'left-open': pathOf(leftPanelOpen),
    'left-close': pathOf(leftPanelClose),
    add: pathOf(add),
  }
</script>

<script lang="ts">
  const { name, size = 24 }: { name: IconName; size?: number } = $props()
</script>

<!-- Material Symbols are drawn on a 960-unit grid whose origin is the top left minus 960. -->
<svg
  class="nav-icon"
  viewBox="0 -960 960 960"
  width={size}
  height={size}
  aria-hidden="true"
  focusable="false"
>
  <path d={PATHS[name]} />
</svg>

<style>
  .nav-icon {
    fill: currentColor;
    flex: none;
    display: block;
  }
</style>
