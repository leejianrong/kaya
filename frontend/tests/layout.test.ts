/**
 * `lib/layout.ts`'s force-directed layout, as a pure function — no DOM, no component, no fetch.
 *
 * The claims worth asserting are the ones the module docstring makes: deterministic (no
 * `Math.random()`), nodes end up spread apart rather than stacked on the starting point, an
 * isolated node still gets a position, and empty input does not throw.
 */

import { describe, expect, it } from 'vitest'

import { layoutGraph } from '../src/lib/layout'
import type { GraphEdge, GraphNode } from '../src/lib/types'

function node(ref: string, title = ref): GraphNode {
  return { ref, title, path: '' }
}

function edge(source: string, target: string): GraphEdge {
  return { source, target }
}

function distance(a: { x: number; y: number }, b: { x: number; y: number }): number {
  return Math.hypot(a.x - b.x, a.y - b.y)
}

describe('layoutGraph', () => {
  it('returns an empty map for no nodes, and does not throw', () => {
    expect(() => layoutGraph([], [])).not.toThrow()
    expect(layoutGraph([], []).size).toBe(0)
    expect(layoutGraph([], [edge('NOTE-1', 'NOTE-2')]).size).toBe(0)
  })

  it('places a single node, and it is finite', () => {
    const positions = layoutGraph([node('NOTE-1')], [])

    expect(positions.size).toBe(1)
    const p = positions.get('NOTE-1')!
    expect(Number.isFinite(p.x)).toBe(true)
    expect(Number.isFinite(p.y)).toBe(true)
  })

  it('gives every node in the input a position, edges or not', () => {
    const nodes = [node('NOTE-1'), node('NOTE-2'), node('NOTE-3')]
    const positions = layoutGraph(nodes, [edge('NOTE-1', 'NOTE-2')])

    // NOTE-3 has no edge at all, and still has to end up somewhere.
    expect([...positions.keys()].sort()).toEqual(['NOTE-1', 'NOTE-2', 'NOTE-3'])
    for (const ref of positions.keys()) {
      const p = positions.get(ref)!
      expect(Number.isFinite(p.x)).toBe(true)
      expect(Number.isFinite(p.y)).toBe(true)
    }
  })

  it('is deterministic: the same input lays out to the same positions every time', () => {
    const nodes = [node('NOTE-1'), node('NOTE-2'), node('NOTE-3'), node('NOTE-4')]
    const edges = [edge('NOTE-1', 'NOTE-2'), edge('NOTE-2', 'NOTE-3'), edge('NOTE-3', 'NOTE-4')]

    const first = layoutGraph(nodes, edges)
    const second = layoutGraph(nodes, edges)

    for (const ref of ['NOTE-1', 'NOTE-2', 'NOTE-3', 'NOTE-4']) {
      expect(second.get(ref)).toEqual(first.get(ref))
    }
  })

  it('spreads unconnected nodes apart rather than stacking them at the origin', () => {
    const nodes = Array.from({ length: 6 }, (_, i) => node(`NOTE-${i + 1}`))
    const positions = layoutGraph(nodes, [])

    const refs = [...positions.keys()]
    for (let i = 0; i < refs.length; i++) {
      for (let j = i + 1; j < refs.length; j++) {
        expect(distance(positions.get(refs[i]!)!, positions.get(refs[j]!)!)).toBeGreaterThan(5)
      }
    }
  })

  it('pulls a connected pair closer together than two nodes with no edge between them', () => {
    // Four nodes, one edge (1–2). Repulsion pushes every pair apart; the spring is the only force
    // that pulls 1 and 2 back together, so they should end up closer than an unconnected pair.
    const nodes = [node('NOTE-1'), node('NOTE-2'), node('NOTE-3'), node('NOTE-4')]
    const positions = layoutGraph(nodes, [edge('NOTE-1', 'NOTE-2')])

    const linked = distance(positions.get('NOTE-1')!, positions.get('NOTE-2')!)
    const unlinked = distance(positions.get('NOTE-3')!, positions.get('NOTE-4')!)

    expect(linked).toBeLessThan(unlinked)
  })

  it('ignores an edge naming a ref outside the node set, rather than throwing', () => {
    const nodes = [node('NOTE-1'), node('NOTE-2')]

    expect(() => layoutGraph(nodes, [edge('NOTE-1', 'NOTE-999')])).not.toThrow()
    const positions = layoutGraph(nodes, [edge('NOTE-1', 'NOTE-999')])
    expect([...positions.keys()].sort()).toEqual(['NOTE-1', 'NOTE-2'])
  })

  it('respects a smaller iteration count without throwing or producing non-finite positions', () => {
    const nodes = [node('NOTE-1'), node('NOTE-2'), node('NOTE-3')]
    const edges = [edge('NOTE-1', 'NOTE-2'), edge('NOTE-2', 'NOTE-3')]

    const positions = layoutGraph(nodes, edges, { iterations: 1 })

    expect(positions.size).toBe(3)
    for (const p of positions.values()) {
      expect(Number.isFinite(p.x)).toBe(true)
      expect(Number.isFinite(p.y)).toBe(true)
    }
  })

  it('keeps every position within a sane multiple of the requested canvas', () => {
    // Not a hard clamp — a force-directed layout is not clipped to its canvas, the docstring says
    // so — but a layout that runs away to infinity is a bug, not a feature, and 240 damped
    // iterations should settle well inside a small multiple of the canvas size.
    const nodes = Array.from({ length: 12 }, (_, i) => node(`NOTE-${i + 1}`))
    const edges = nodes.slice(1).map((n, i) => edge(nodes[i]!.ref, n.ref))
    const positions = layoutGraph(nodes, edges, { width: 900, height: 640 })

    for (const p of positions.values()) {
      expect(Math.abs(p.x)).toBeLessThan(900 * 5)
      expect(Math.abs(p.y)).toBeLessThan(640 * 5)
    }
  })
})
