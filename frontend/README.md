# kaya frontend

Svelte 5 (runes) + Vite + TypeScript, on `npm`.

```bash
npm ci
npm run dev      # http://localhost:5173, /api proxied to the backend on :8000
npm run build    # -> dist/
npm run lint     # eslint + svelte-check
npm test         # vitest, once
```

Shell only for now: KAN-531 gets the toolchain and the dev proxy working. The editor
(CodeMirror 6), the folder tree and the backlinks panel arrive in V3.

## The proxy, and why the SPA never writes an absolute URL

In production one artifact serves the SPA and `/api/v1` from a single origin
([ADR 0001](../docs/adr/0001-stack-inherited-from-pandan.md)). In development that is two
processes, so `vite.config.ts` forwards `/api` to `http://localhost:8000` to keep the same-origin
promise true locally. `src/lib/api.ts` builds relative paths only and throws on an absolute URL —
bake in an origin and you need a per-environment build and a CORS policy to go with it.

`tests/dev-proxy.test.ts` asserts the proxy target, because a proxy that quietly stops forwarding
does not fail loudly: `fetch('/api/v1/notes')` just returns `index.html` with a 200, and you spend
the afternoon debugging a JSON parse error.

Both ends are overridable, for the same reason `docker-compose.yml` takes `COMPOSE_PROJECT_NAME` —
parallel worktrees share a machine:

```bash
KAYA_SPA_PORT=5273 KAYA_BACKEND_ORIGIN=http://localhost:8001 npm run dev
```

`strictPort` is on, so an occupied port is an error rather than a silent move to 5174 that leaves
your browser pointed at whatever else is on 5173.

## When CodeMirror lands

CodeMirror owns its DOM subtree. Mount it once in an `$effect` against an element ref, put changes
in as transactions, take them out through an update listener, and never render Svelte inside that
subtree. A rune bound naively to the document and written back creates an update loop — the
write-back needs a guard comparing against the editor's current document (ADR 0001 §2).
