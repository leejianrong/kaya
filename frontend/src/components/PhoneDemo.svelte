<!--
  A phone-shaped mock for the landing page (KAN-1822): fixed demo content, never the live app.

  It shows the Read / Edit switch the real note screen has (KAN-1819) and the bottom navigation bar
  (KAN-1818), and its Graph item swaps the note for a small static node-link picture. Nothing in
  here is a link or reaches the network, and it takes no part in routing.

  Accessibility: the frame is one labelled group ("Note preview demo"), icons are `aria-hidden`,
  and the only tab stops are the real `<button>`s (Read, Edit and the three bottom items), each
  with a visible focus ring. The colours are the app's own tokens (`app.css`), so a palette change
  restyles the phone along with everything else.
-->
<script lang="ts">
  import NavIcon from './NavIcon.svelte'

  type Screen = 'read' | 'edit' | 'graph'

  let screen: Screen = $state('read')
  /** The note's last mode, so Notes in the bottom bar returns to where Read / Edit left off. */
  let mode: 'read' | 'edit' = $state('read')

  const show = (next: Screen): void => {
    screen = next
    if (next !== 'graph') {
      mode = next
    }
  }

  // Static layout for the Graph screen: [x, y, label], and index pairs for the edges.
  const NODES: [number, number, string][] = [
    [120, 100, 'Sprint planning'],
    [56, 46, 'Retro notes'],
    [190, 44, 'Roadmap'],
    [214, 126, 'Release'],
    [150, 188, 'Agent notes'],
    [62, 168, 'Reading list'],
    [30, 108, 'Journal'],
    [120, 252, 'API design'],
  ]
  const EDGES: [number, number][] = [
    [0, 1],
    [0, 2],
    [0, 4],
    [2, 3],
    [3, 4],
    [1, 6],
    [6, 5],
    [4, 7],
    [5, 7],
  ]
</script>

<div class="phone" role="group" aria-label="Note preview demo" data-testid="phone-demo">
  <div class="status" aria-hidden="true"><span>9:41</span><i></i><span></span></div>

  <div class="bar" aria-hidden="true">
    <span class="ib">
      <svg viewBox="0 0 24 24"><path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z" /></svg>
    </span>
    <span class="bar-title">{screen === 'graph' ? 'Graph' : 'Sprint planning'}</span>
    {#if screen !== 'graph'}
      <span class="ib">
        <svg viewBox="0 0 24 24"
          ><path
            d="M3.9 12c0-1.71 1.39-3.1 3.1-3.1h4V7H7c-2.76 0-5 2.24-5 5s2.24 5 5 5h4v-1.9H7c-1.71 0-3.1-1.39-3.1-3.1zM8 13h8v-2H8v2zm9-6h-4v1.9h4c1.71 0 3.1 1.39 3.1 3.1s-1.39 3.1-3.1 3.1h-4V17h4c2.76 0 5-2.24 5-5s-2.24-5-5-5z"
          /></svg
        >
      </span>
    {/if}
    <span class="ib">
      <svg viewBox="0 0 24 24"
        ><path d="M12 8a2 2 0 100-4 2 2 0 000 4zm0 2a2 2 0 100 4 2 2 0 000-4zm0 6a2 2 0 100 4 2 2 0 000-4z" /></svg
      >
    </span>
  </div>

  {#if screen !== 'graph'}
    <div class="seg" role="group" aria-label="View mode">
      <button type="button" aria-pressed={screen === 'read'} onclick={() => show('read')}>Read</button>
      <button type="button" aria-pressed={screen === 'edit'} onclick={() => show('edit')}>Edit</button>
    </div>
  {/if}

  <div class="body" data-testid="phone-screen" data-screen={screen}>
    {#if screen === 'read'}
      <div class="doc" data-testid="phone-read">
        <p class="doc-title">Sprint planning</p>
        <div class="prose">
          <p class="sub">Agenda</p>
          <p>Review the board, then pick up the work in <span class="wl">Retro notes</span>.</p>
          <ul>
            <li>Review the board</li>
            <li>Decide on the release</li>
            <li>Pick up the mobile work</li>
          </ul>
          <pre><code>kaya note list --limit 5</code></pre>
        </div>
      </div>
    {:else if screen === 'edit'}
      <div class="doc" data-testid="phone-edit">
        <p class="doc-title">Sprint planning</p>
        <pre class="src"><span class="h">## Agenda</span>

Review the board, then pick up the work in <span class="w">[[Retro notes]]</span>.

- Review the board
- Decide on the release
- Pick up the mobile work

```
kaya note list --limit 5
```<span class="cur"></span></pre>
      </div>
    {:else}
      <svg class="graph" viewBox="0 0 240 280" data-testid="phone-graph" aria-hidden="true">
        {#each EDGES as [a, b] (`${a}-${b}`)}
          <line x1={NODES[a][0]} y1={NODES[a][1]} x2={NODES[b][0]} y2={NODES[b][1]} />
        {/each}
        {#each NODES as [x, y, label], index (label)}
          <circle class:hub={index === 0} cx={x} cy={y} r={index === 0 ? 9 : 6} />
          <text x={x} y={y + (index === 0 ? 22 : 18)} text-anchor="middle">{label}</text>
        {/each}
      </svg>
    {/if}
  </div>

  {#if screen === 'edit'}
    <div class="tools" aria-hidden="true">
      <span class="tool">B</span><span class="tool it">I</span><span class="tool">&bull;</span>
      <span class="tool mono">&lt;/&gt;</span><span class="tool mono">[[&nbsp;]]</span>
    </div>
  {/if}

  <div class="navbar" role="group" aria-label="Demo navigation">
    <button type="button" aria-pressed={screen !== 'graph' ? 'true' : 'false'} onclick={() => show(mode)}>
      <span class="pill"><NavIcon name="notes" /></span>Notes
    </button>
    <button type="button" aria-pressed={screen === 'graph'} onclick={() => show('graph')}>
      <span class="pill"><NavIcon name="graph" /></span>Graph
    </button>
    <div class="item">
      <span class="pill"><NavIcon name="settings" /></span>Settings
    </div>
  </div>
</div>

<style>
  .phone {
    box-sizing: border-box;
    width: min(100%, 18rem);
    height: 35rem;
    margin-inline: auto;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    border: 6px solid var(--text);
    border-radius: 2.1rem;
    background: var(--card-bg);
    box-shadow: var(--shadow-md);
    color: var(--text);
    font-size: 0.75rem;
    line-height: 1.4;
    text-align: left;
  }

  .status {
    flex: none;
    display: flex;
    justify-content: space-between;
    align-items: center;
    height: 1.4rem;
    padding: 0 1.1rem;
    font-size: 0.62rem;
    font-weight: 600;
  }

  .status i {
    width: 2.9rem;
    height: 0.3rem;
    border-radius: 0.2rem;
    background: var(--text);
    opacity: 0.8;
  }

  .bar {
    flex: none;
    display: flex;
    align-items: center;
    gap: 0.2rem;
    height: 3rem;
    padding: 0 0.4rem;
  }

  .bar-title {
    flex: 1;
    min-width: 0;
    padding-left: 0.3rem;
    font-size: 0.95rem;
    font-weight: 600;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .ib {
    display: grid;
    place-items: center;
    flex: none;
    width: 2.3rem;
    height: 2.3rem;
    color: var(--muted);
  }

  .ib svg {
    width: 1.3rem;
    height: 1.3rem;
    fill: currentColor;
  }

  .seg {
    flex: none;
    display: flex;
    height: 2.1rem;
    margin: 0 0.75rem 0.4rem;
    border: 1px solid var(--border);
    border-radius: 1.05rem;
    overflow: hidden;
  }

  .seg button {
    flex: 1;
    border: 0;
    border-right: 1px solid var(--border);
    background: none;
    color: var(--text);
    font: inherit;
    font-size: 0.78rem;
    font-weight: 600;
    cursor: pointer;
  }

  .seg button:last-child {
    border-right: 0;
  }

  .seg button[aria-pressed='true'] {
    background: var(--accent-soft);
  }

  .seg button:focus-visible,
  .navbar button:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: -2px;
  }

  .body {
    flex: 1;
    min-height: 0;
    overflow: hidden;
  }

  .doc-title {
    margin: 0;
    padding: 0.25rem 1.1rem 0;
    font-size: 1.3rem;
    line-height: 1.2;
    font-weight: 650;
  }

  .prose {
    padding: 0.5rem 1.1rem;
    font-size: 0.85rem;
    line-height: 1.55;
  }

  .prose .sub {
    font-weight: 650;
    margin: 0.5rem 0 0.25rem;
    font-size: 1rem;
  }

  .prose p {
    margin: 0 0 0.5rem;
  }

  .prose ul {
    margin: 0 0 0.6rem;
    padding-left: 1.15rem;
  }

  .prose pre {
    margin: 0;
    padding: 0.5rem 0.65rem;
    border-radius: 0.6rem;
    background: var(--surface-2);
    font-family: var(--mono);
    font-size: 0.68rem;
    overflow: hidden;
  }

  /* The same treatment `lib/codemirror.ts` gives a resolved wikilink, and not a real link: nothing
     in this mock navigates. */
  .wl,
  .w {
    padding: 0 0.15rem;
    border-radius: 0.25rem;
    background: color-mix(in srgb, var(--accent) 14%, transparent);
    color: var(--accent);
  }

  .wl {
    font-weight: 600;
  }

  .src {
    margin: 0;
    padding: 0.5rem 1.1rem;
    font-family: var(--mono);
    font-size: 0.72rem;
    line-height: 1.7;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }

  .src .h {
    color: var(--accent);
    font-weight: 600;
  }

  .cur {
    display: inline-block;
    width: 2px;
    height: 1.1em;
    background: var(--accent);
    vertical-align: text-bottom;
  }

  .tools {
    flex: none;
    display: flex;
    align-items: center;
    height: 2.4rem;
    padding: 0 0.4rem;
    background: var(--surface-2);
  }

  .tool {
    display: grid;
    place-items: center;
    flex: 1;
    font-weight: 700;
    font-size: 0.8rem;
  }

  .tool.it {
    font-style: italic;
    font-weight: 600;
  }

  .tool.mono {
    font-family: var(--mono);
    font-size: 0.68rem;
  }

  .graph {
    display: block;
    width: 100%;
    height: 100%;
  }

  .graph line {
    stroke: var(--border);
    stroke-width: 1.5;
  }

  .graph circle {
    fill: var(--muted);
  }

  .graph circle.hub {
    fill: var(--accent);
  }

  .graph text {
    fill: var(--muted);
    font-size: 8.5px;
  }

  .navbar {
    flex: none;
    display: flex;
    padding: 0.4rem 0.3rem 0.35rem;
    background: var(--surface-2);
  }

  .navbar button,
  .navbar .item {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.15rem;
    border: 0;
    background: none;
    color: var(--muted);
    font: inherit;
    font-size: 0.66rem;
    font-weight: 500;
    cursor: pointer;
  }

  .navbar .item {
    cursor: default;
  }

  .navbar .pill {
    display: grid;
    place-items: center;
    width: 3.1rem;
    height: 1.7rem;
    border-radius: 0.85rem;
  }

  .navbar button[aria-pressed='true'] {
    color: var(--text);
    font-weight: 650;
  }

  .navbar button[aria-pressed='true'] .pill {
    background: var(--accent-soft);
    color: var(--accent);
  }

  @media (prefers-reduced-motion: no-preference) {
    .seg button,
    .navbar .pill {
      transition: background-color 0.15s ease;
    }
  }
</style>
