/**
 * A hand-rolled force-directed layout for the note graph (KAN-1050) — pure, framework-free, and
 * the deliberate ADR 0001 §2 move: `d3-force` would have needed the measured-cost justification
 * `frontend/README.md` describes for a new runtime dependency, and a few dozen nodes' worth of
 * physics does not clear that bar. `frontend/package.json`'s `dependencies` array is unchanged by
 * this card.
 *
 * Three forces, the textbook Fruchterman–Reingold shape:
 *
 * - **Repulsion** between every pair of nodes (Coulomb-like, `k / distance²`), so two nodes never
 *   want to occupy the same point. `O(n²)` per iteration, which is fine at this app's scale — a
 *   personal notes graph is dozens to a couple hundred nodes, not thousands, and this runs once per
 *   `/graph` visit rather than per frame.
 * - **Attraction** along each edge (Hooke-like, proportional to how far the edge's current length
 *   is from {@link LayoutOptions.springLength}), so linked notes pull toward a comfortable
 *   distance instead of drifting arbitrarily far apart under repulsion alone.
 * - **Centering**, a mild pull toward the canvas center, so the whole graph does not walk off
 *   screen — repulsion alone has no reason to prefer any particular location, only relative ones.
 *
 * **Deterministic**, on purpose: starting positions are an evenly-spaced circle keyed on each
 * node's index, never `Math.random()`. A snapshot test would be flaky otherwise, and re-opening the
 * same graph would visually "jump" between two unrelated layouts for no reason a person could see.
 * Re-running the simulation on every fetch is fine — v1 does not persist a node's position.
 */

import type { GraphEdge, GraphNode } from './types'

export interface Position {
  x: number
  y: number
}

export interface LayoutOptions {
  /** Canvas size the layout targets. Positions are not clamped to it — a node can end up outside
   *  these bounds, the same way a force-directed layout in any other tool can — but the starting
   *  circle and the centering force are both sized from it. */
  width?: number
  height?: number
  /** Fixed iteration count. 240 is comfortably past the point a few dozen-to-a-couple-hundred-node
   *  graph stops moving visibly under this file's damping (checked by hand against the shapes
   *  `tests/layout.test.ts` builds — a path, a star, a fully-connected cluster), while staying well
   *  under a millisecond of work at that size: there is no card asking for more, and a simulation
   *  that never settles is a bug in the forces below, not a reason to run it longer. */
  iterations?: number
  /** Coulomb-like repulsion constant between every pair of nodes. */
  repulsion?: number
  /** The edge length the spring force pulls toward. */
  springLength?: number
  /** How hard the spring force corrects a length away from {@link springLength}. */
  springStrength?: number
  /** How hard every node is pulled toward the canvas center each iteration. */
  centerStrength?: number
  /** Velocity multiplier applied after integrating each iteration's forces, `(0, 1)`. Below 1 so
   *  the simulation settles instead of oscillating forever. */
  damping?: number
}

const DEFAULTS: Required<LayoutOptions> = {
  width: 900,
  height: 640,
  iterations: 240,
  repulsion: 12000,
  springLength: 130,
  springStrength: 0.02,
  centerStrength: 0.01,
  damping: 0.82,
}

/**
 * Lay out `nodes` and `edges`, returning each node's `ref` mapped to a final `{x, y}`.
 *
 * An edge naming a `ref` absent from `nodes` is ignored rather than throwing — `graph_read` on the
 * backend already guarantees every edge names two of the caller's own nodes, but this function
 * takes plain data and has no reason to trust its caller more than that guarantee requires; a
 * malformed edge should not crash a rendering pass.
 */
export function layoutGraph(
  nodes: readonly GraphNode[],
  edges: readonly GraphEdge[],
  options: LayoutOptions = {},
): Map<string, Position> {
  const opts = { ...DEFAULTS, ...options }
  const positions = new Map<string, Position>()
  if (nodes.length === 0) {
    return positions
  }

  const cx = opts.width / 2
  const cy = opts.height / 2
  const radius = Math.max(1, Math.min(opts.width, opts.height) / 2 - 40)

  const refs = nodes.map((node) => node.ref)
  const velocities = new Map<string, Position>()
  refs.forEach((ref, index) => {
    const angle = (2 * Math.PI * index) / refs.length
    positions.set(ref, { x: cx + radius * Math.cos(angle), y: cy + radius * Math.sin(angle) })
    velocities.set(ref, { x: 0, y: 0 })
  })

  const validEdges = edges.filter((edge) => positions.has(edge.source) && positions.has(edge.target))

  for (let iteration = 0; iteration < opts.iterations; iteration++) {
    const forces = new Map<string, Position>(refs.map((ref) => [ref, { x: 0, y: 0 }]))

    applyRepulsion(refs, positions, forces, opts.repulsion)
    applySprings(validEdges, positions, forces, opts.springLength, opts.springStrength)
    applyCentering(refs, positions, forces, cx, cy, opts.centerStrength)
    integrate(refs, positions, velocities, forces, opts.damping)
  }

  return positions
}

function applyRepulsion(
  refs: readonly string[],
  positions: Map<string, Position>,
  forces: Map<string, Position>,
  repulsion: number,
): void {
  for (let i = 0; i < refs.length; i++) {
    for (let j = i + 1; j < refs.length; j++) {
      const a = refs[i]!
      const b = refs[j]!
      const pa = positions.get(a)!
      const pb = positions.get(b)!
      let dx = pa.x - pb.x
      let dy = pa.y - pb.y
      let distanceSquared = dx * dx + dy * dy
      if (distanceSquared < 0.0001) {
        // Two nodes landed on (or very near) the same point. A tiny, index-derived offset breaks
        // the tie deterministically — `Math.random()` here would be the one place non-determinism
        // could sneak back in, exactly what the module docstring rules out.
        dx = 0.01 * (i - j || 1)
        dy = 0.01
        distanceSquared = dx * dx + dy * dy
      }
      const distance = Math.sqrt(distanceSquared)
      const force = repulsion / distanceSquared
      const fx = (dx / distance) * force
      const fy = (dy / distance) * force
      const fa = forces.get(a)!
      const fb = forces.get(b)!
      fa.x += fx
      fa.y += fy
      fb.x -= fx
      fb.y -= fy
    }
  }
}

function applySprings(
  edges: readonly GraphEdge[],
  positions: Map<string, Position>,
  forces: Map<string, Position>,
  springLength: number,
  springStrength: number,
): void {
  for (const edge of edges) {
    const pa = positions.get(edge.source)!
    const pb = positions.get(edge.target)!
    const dx = pb.x - pa.x
    const dy = pb.y - pa.y
    const distance = Math.sqrt(dx * dx + dy * dy) || 0.01
    const force = (distance - springLength) * springStrength
    const fx = (dx / distance) * force
    const fy = (dy / distance) * force
    const fa = forces.get(edge.source)!
    const fb = forces.get(edge.target)!
    fa.x += fx
    fa.y += fy
    fb.x -= fx
    fb.y -= fy
  }
}

function applyCentering(
  refs: readonly string[],
  positions: Map<string, Position>,
  forces: Map<string, Position>,
  cx: number,
  cy: number,
  centerStrength: number,
): void {
  for (const ref of refs) {
    const p = positions.get(ref)!
    const f = forces.get(ref)!
    f.x += (cx - p.x) * centerStrength
    f.y += (cy - p.y) * centerStrength
  }
}

function integrate(
  refs: readonly string[],
  positions: Map<string, Position>,
  velocities: Map<string, Position>,
  forces: Map<string, Position>,
  damping: number,
): void {
  for (const ref of refs) {
    const v = velocities.get(ref)!
    const f = forces.get(ref)!
    v.x = (v.x + f.x) * damping
    v.y = (v.y + f.y) * damping
    const p = positions.get(ref)!
    p.x += v.x
    p.y += v.y
  }
}
