/**
 * How the SPA addresses the API.
 *
 * Same-origin, always relative. In production one artifact serves both the SPA and `/api/v1`
 * (ADR 0001); in development Vite's proxy forwards `/api` to the backend on :8000. Both only
 * work if the SPA never builds an absolute URL — an origin baked in at build time is how a
 * frontend ends up needing a per-environment build and a CORS policy to go with it.
 */

export const API_BASE = '/api/v1'

/** Join a path onto the API base, tolerating a leading slash or its absence. */
export function apiPath(path: string): string {
  if (/^[a-z][a-z0-9+.-]*:/i.test(path) || path.startsWith('//')) {
    throw new Error(`apiPath expects a relative path, got an absolute URL: ${path}`)
  }
  const trimmed = path.replace(/^\/+/, '')
  return trimmed === '' ? API_BASE : `${API_BASE}/${trimmed}`
}
