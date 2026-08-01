<script lang="ts">
  import { API_BASE } from './lib/api'

  // Svelte 5 runes. The editor (CodeMirror 6, mounted once against an element ref) lands in V3;
  // this is the shell that proves the toolchain compiles and the SPA serves.
  type Package = { name: string; role: string; done: boolean }

  const packages: Package[] = [
    { name: 'backend', role: 'FastAPI, sync SQLAlchemy, Alembic', done: true },
    { name: 'kaya-client', role: 'the shared core and the render() seam', done: false },
    { name: 'kaya-cli', role: 'the kaya console script', done: false },
    { name: 'mcp', role: 'the MCP adapter', done: false },
    { name: 'frontend', role: 'this SPA', done: true },
  ]

  let showAll = $state(false)
  const shown = $derived(showAll ? packages : packages.filter((p) => p.done))
</script>

<main>
  <h1>kaya</h1>
  <p class="lede">
    Markdown notes, API-first and agent-drivable. The skeleton is up; the notes are not written yet.
  </p>

  <p class="meta">
    API base <code>{API_BASE}</code> — same origin in production, proxied to
    <code>:8000</code> by the dev server.
  </p>

  <ul>
    {#each shown as pkg (pkg.name)}
      <li><code>{pkg.name}</code> <span>{pkg.role}</span></li>
    {/each}
  </ul>

  <button onclick={() => (showAll = !showAll)}>
    {showAll ? 'Show what boots' : 'Show every package'}
  </button>
</main>

<style>
  main {
    max-width: 42rem;
    margin: 0 auto;
    padding: 4rem 1.5rem;
  }

  h1 {
    margin: 0;
    font-size: 2.25rem;
    letter-spacing: -0.02em;
  }

  .lede {
    margin: 0.25rem 0 1.5rem;
    font-size: 1.05rem;
  }

  .meta {
    color: var(--muted);
    font-size: 0.9rem;
  }

  ul {
    list-style: none;
    padding: 0;
    border-top: 1px solid var(--edge);
  }

  li {
    display: flex;
    gap: 0.75rem;
    align-items: baseline;
    padding: 0.6rem 0;
    border-bottom: 1px solid var(--edge);
  }

  li span {
    color: var(--muted);
    font-size: 0.9rem;
  }

  button {
    font: inherit;
    color: var(--accent);
    background: none;
    border: 1px solid var(--edge);
    border-radius: 0.4rem;
    padding: 0.45rem 0.9rem;
    cursor: pointer;
  }
</style>
