<!--
  The kaya mark (KAN-1823): a slice of toast, a green note spread on it, a butter knife.

  Colours come from `--logo-k/-toast/-kaya/-lt` (app.css), which swap under
  `prefers-color-scheme: dark` on their own — deliberately not the UI's `--accent` etc., so the
  mark keeps its colours when the interface palette is reworked.

  Decorative by default (`aria-hidden`), because it sits beside the live "kaya" text. Pass `title`
  where the mark stands alone and it becomes an `img` with an accessible name instead.
-->
<script lang="ts">
  const { size = 24, title = undefined }: { size?: number; title?: string } = $props()
</script>

<svg
  class="logo"
  xmlns="http://www.w3.org/2000/svg"
  viewBox="4.8 4.3 34.4 34.4"
  width={size}
  height={size}
  role={title ? 'img' : undefined}
  aria-hidden={title ? undefined : 'true'}
  aria-label={title}
  focusable="false"
  data-testid="logo"
>
  <path
    d="M11.5 33V20.4A5.2 5.2 0 0 1 11.5 10.4H28.5A5.2 5.2 0 0 1 28.5 20.4V33Z"
    fill="var(--logo-toast)"
    stroke="var(--logo-toast)"
    stroke-width="2.2"
    stroke-linejoin="round"
  />
  <rect x="13.6" y="14" width="12.8" height="14" rx="2.4" fill="var(--logo-kaya)" />
  <path
    d="M16.6 18.4h6.6M16.6 22.2h4"
    stroke="var(--logo-lt)"
    stroke-width="1.8"
    stroke-linecap="round"
  />
  <g transform="rotate(-14 22 28)" fill="var(--logo-k)">
    <rect x="11" y="26.1" width="14" height="4" rx="2" />
    <rect x="24" y="27.1" width="14" height="2" rx="1" />
  </g>
</svg>

<style>
  .logo {
    display: block;
    flex: none;
  }
</style>
