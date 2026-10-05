<!--
  The three section icons the bottom bar, the rail and the landing page's phone demo share
  (KAN-1822). Material-style 24px paths, drawn with `currentColor` so the owner's colour tokens
  restyle them. Always decorative: the label beside each one carries the name.
-->
<script lang="ts">
  const { name }: { name: 'notes' | 'graph' | 'settings' } = $props()
</script>

<svg class="nav-icon" viewBox="0 0 24 24" width="24" height="24" aria-hidden="true" focusable="false">
  {#if name === 'notes'}
    <path
      d="M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z"
    />
  {:else if name === 'graph'}
    <path d="M6 3a3 3 0 100 6 3 3 0 000-6zm12 6a3 3 0 100 6 3 3 0 000-6zM8 15a3 3 0 100 6 3 3 0 000-6z" />
    <path d="M8.2 7.8l7.6 2.6M7.3 14.9l8-3.3" stroke="currentColor" stroke-width="1.5" fill="none" />
  {:else}
    <path
      d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58a.49.49 0 00.12-.61l-1.92-3.32a.488.488 0 00-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54a.484.484 0 00-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58a.49.49 0 00-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6A3.6 3.6 0 1115.6 12 3.611 3.611 0 0112 15.6z"
    />
  {/if}
</svg>

<style>
  .nav-icon {
    fill: currentColor;
    flex: none;
    display: block;
  }
</style>
