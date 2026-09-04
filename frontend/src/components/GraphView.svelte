<script lang="ts">
  import { ApiError } from '../lib/api'
  import { fetchGraph } from '../lib/graph'
  import { layoutGraph, type Position } from '../lib/layout'
  import { interceptClick, routeHref } from '../lib/router'
  import type { GraphEdge, GraphNode } from '../lib/types'

  /**
   * KAN-1050's `/graph`: the caller's whole `note_link` graph, read-only, as an SVG diagram.
   *
   * **A route-level view, not a rail like `BacklinksPanel`.** It answers one question about the
   * whole corpus ("how does everything connect") rather than one question about the open note, so
   * it is `App.svelte`'s `main` content for `route.name === 'graph'`, the same slot `route.name ===
   * 'unknown'`'s notice occupies — not a fourth region beside it.
   *
   * **Fetch once per mount, lay out once per fetch, render.** There is no editing here and nothing
   * to keep in sync with an editor's keystrokes, so this component has none of `BacklinksPanel`'s
   * identity-guard machinery — that exists to stop a request per keystroke as a prop's *object*
   * identity changes under an unmoving ref, and this component takes no props that could do that.
   *
   * **No drag-to-reposition in this first cut.** `lib/layout.ts`'s positions are read straight into
   * the SVG on every layout; a person can navigate to a note by clicking it and nothing more.
   *
   * **Text interpolation only, never `{@html}`.** A node's `title` is prose someone wrote in a
   * different note — the same class of surface `BacklinksPanel`'s docstring calls out — and Svelte
   * escapes every `{…}` into a text node, which is the whole of this component's XSS posture.
   * `tests/no-html-injection.test.ts` asserts the absence structurally, over `src/`.
   */
  const {
    onexpired,
  }: {
    /** The API refused the credential. Handed to `App.svelte`, which owns the credential
     *  lifecycle — see `BacklinksPanel.svelte`'s identical prop for the full argument. */
    onexpired: (reason: string) => void
  } = $props()

  const WIDTH = 900
  const HEIGHT = 640

  let loading = $state(true)
  /** The last failure's prose, or `null`. The API's own message, used verbatim. */
  let failure: string | null = $state(null)
  let nodes: GraphNode[] = $state([])
  let edges: GraphEdge[] = $state([])

  /**
   * Positions, recomputed whenever `nodes`/`edges` change — which today is exactly once, on the
   * fetch settling. Re-laying-out on every fetch rather than persisting a node's position is v1's
   * explicit scope (`lib/layout.ts`'s docstring): nothing here remembers where a node was.
   */
  const positions: Map<string, Position> = $derived(
    layoutGraph(nodes, edges, { width: WIDTH, height: HEIGHT }),
  )

  /** A node's laid-out position, or the canvas center for a ref `layoutGraph` did not place —
   *  unreachable in practice (every node it is handed gets a position), and safer than a
   *  non-null assertion at every one of this template's several reads of the same map. */
  function at(ref: string): Position {
    return positions.get(ref) ?? { x: WIDTH / 2, y: HEIGHT / 2 }
  }

  function label(node: GraphNode): string {
    return node.title === '' ? node.ref : node.title
  }

  /**
   * A failure, sorted the same way `BacklinksPanel.absorb` sorts one: a `401` is not this
   * component's to explain, because `App.svelte` owns the credential lifecycle.
   */
  function absorb(error: unknown): void {
    if (error instanceof ApiError && error.isUnauthenticated) {
      onexpired(error.message)
      return
    }
    failure = error instanceof Error ? error.message : 'Could not load the graph.'
  }

  /**
   * The component's one once-per-lifetime job: fetch the graph.
   *
   * Reads nothing, so it runs exactly once per mount — the same shape `PreviewPane.svelte`'s
   * chunk-loader effect uses for the identical reason. `live` stops a component unmounted
   * mid-flight from assigning a rune afterwards.
   */
  $effect(() => {
    let live = true
    fetchGraph().then(
      (graph) => {
        if (!live) {
          return
        }
        nodes = graph.nodes
        edges = graph.edges
        loading = false
      },
      (error: unknown) => {
        if (!live) {
          return
        }
        absorb(error)
        loading = false
      },
    )
    return () => {
      live = false
    }
  })
</script>

<section class="graph" aria-label="Note graph">
  <header>
    <h2>Graph</h2>
    {#if !loading && failure === null}
      <!-- A label on the nodes already on screen, not an aggregate over the payload — the same call
           `BacklinksPanel`'s count and `Sidebar`'s "no path" count already make (ADR 0004). -->
      <span class="count" data-testid="graph-count">{nodes.length}</span>
    {/if}
  </header>

  {#if loading}
    <p class="empty" data-testid="graph-loading">Loading…</p>
  {:else if failure !== null}
    <p class="notice" data-testid="graph-error">Could not load the graph: {failure}</p>
  {:else if nodes.length === 0}
    <p class="empty" data-testid="graph-empty">
      No notes yet. Create one from the sidebar to start the graph.
    </p>
  {:else}
    <svg
      class="canvas"
      viewBox="0 0 {WIDTH} {HEIGHT}"
      role="img"
      aria-label={`Graph of ${nodes.length} notes and ${edges.length} links`}
      data-testid="graph-canvas"
    >
      <!-- Edges first, so every line sits under the nodes it connects rather than crossing a label. -->
      {#each edges as edge (`${edge.source}→${edge.target}`)}
        {@const from = at(edge.source)}
        {@const to = at(edge.target)}
        <line class="edge" x1={from.x} y1={from.y} x2={to.x} y2={to.y} />
      {/each}
      {#each nodes as node (node.ref)}
        {@const p = at(node.ref)}
        <!--
          An SVG `<a>`, the same element `Sidebar.svelte`/`BacklinksPanel.svelte` use in HTML — a
          real `href` so a modified click (⌘-click, middle-click) reaches `spa.py`'s history
          fallback rather than doing nothing, and `interceptClick` routes an ordinary one through
          `navigate()`, which is what KAN-969's unsaved-editor guard is wired to consult.
        -->
        <!-- No `aria-label` carrying the title: the accessible name comes from the `<text>` node
             below instead, so a hostile title never has to survive a round trip through an
             attribute at all — one fewer place for user content to land. -->
        <a
          href={routeHref({ name: 'note', ref: node.ref })}
          onclick={(event) => interceptClick(event, `/notes/${node.ref}`)}
          data-testid="graph-node"
        >
          <circle class="node-circle" cx={p.x} cy={p.y} r="8" />
          <text class="node-label" x={p.x} y={p.y + 20} text-anchor="middle">{label(node)}</text>
        </a>
      {/each}
    </svg>
  {/if}
</section>

<style>
  .graph {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    height: 100%;
    padding: 1.5rem;
  }

  header {
    display: flex;
    align-items: baseline;
    gap: 0.4rem;
  }

  h2 {
    margin: 0;
    color: var(--muted);
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  .count {
    color: var(--muted);
    font-family: var(--mono);
    font-size: 0.7rem;
  }

  .empty {
    margin: 0;
    color: var(--muted);
    font-size: 0.9rem;
  }

  /* Same shape as `EditorPane`/`PreviewPane`/`BacklinksPanel`'s failure notices, so a fourth
     surface reads as the same app rather than as a fourth design. */
  .notice {
    max-width: 34rem;
    margin: 0;
    padding: 0.75rem 1rem;
    border: 1px solid var(--border);
    border-left: 3px solid var(--accent);
    border-radius: 0.35rem;
    font-size: 0.85rem;
  }

  .canvas {
    flex: 1;
    min-height: 0;
    border: 1px solid var(--border);
    border-radius: 0.4rem;
  }

  .edge {
    stroke: var(--border);
    stroke-width: 1.5;
  }

  .node-circle {
    fill: var(--accent);
  }

  a:hover .node-circle {
    fill: color-mix(in srgb, var(--accent) 70%, var(--text));
  }

  .node-label {
    fill: var(--text);
    font-family: var(--mono);
    font-size: 11px;
  }

  a:hover .node-label {
    fill: var(--accent);
  }
</style>
