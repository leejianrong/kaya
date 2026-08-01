import { describe, expect, it } from 'vitest'

import config, { BACKEND_ORIGIN } from '../vite.config'

/**
 * The dev proxy is the deliverable of this card, so it gets an assertion rather than a comment.
 *
 * If it silently stops forwarding, nothing fails loudly — `fetch('/api/v1/notes')` just returns
 * the SPA's own index.html with a 200, and you debug a JSON parse error instead of a proxy.
 */
describe('the vite dev server proxy', () => {
  const proxy = (config as { server?: { proxy?: Record<string, { target?: string }> } }).server
    ?.proxy

  it('forwards /api to the backend on :8000', () => {
    expect(proxy).toBeDefined()
    expect(proxy?.['/api']?.target).toBe('http://localhost:8000')
  })

  it('agrees with the exported backend origin', () => {
    expect(proxy?.['/api']?.target).toBe(BACKEND_ORIGIN)
  })

  it('defaults the dev server to :5173 and refuses to drift off it', () => {
    const server = (config as { server?: { port?: number; strictPort?: boolean } }).server
    expect(server?.port).toBe(5173)
    expect(server?.strictPort).toBe(true)
  })

  it('proxies the api prefix and nothing else', () => {
    expect(Object.keys(proxy ?? {})).toEqual(['/api'])
  })
})
