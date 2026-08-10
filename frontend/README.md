# kaya frontend

Svelte 5 (runes) + Vite + TypeScript, on `npm`.

```bash
npm ci
npm run dev      # http://localhost:5173, /api proxied to the backend on :8000
npm run build    # -> dist/
npm run lint     # eslint + svelte-check
npm test         # vitest, once
```

KAN-531 got the toolchain and the dev proxy working; KAN-552 added the app skeleton the rest of V3
is built inside. What is here is a browsable three-region app; what is not is an editor.

## The layout, and who replaces what

Three cards follow this one and each replaces **one file**, which is the whole reason the layout is
written down:

```
src/
  App.svelte                 the shell: layout regions, the route, the two reads they need
  app.css                    design tokens (--ink, --paper, --muted, --edge, --accent, --sans, --mono)
  lib/api.ts                 apiPath + apiRequest — the one place a request happens
  lib/auth.ts                the credential seam: the only module that knows what a bearer is
  lib/notes.ts               the five note calls
  lib/router.ts              / and /notes/:ref, hand-written, no dependency
  lib/types.ts               the wire shapes, mirroring backend/app/api/schemas.py
  components/Sidebar.svelte    → KAN-554 (folder tree, real list, preview)
  components/EditorPane.svelte → KAN-553 (CodeMirror 6)
```

Three rules that are decisions rather than layout, each argued in the file that holds it:

- **No shaping in the SPA.** No `--fields`-style projection, no truncation hint, no `{"count": n}`.
  The API returns complete records to a browser on purpose (ADR 0004 §Decision); those three are
  agent ergonomics living in `kaya-client`, and a copy here is the bug ADR 0004 exists to prevent.
  Rendering markdown to HTML for preview *is* the SPA's job — that is presentation, not shaping.
- **The token is `sessionStorage`, and the UI says `set` or `not set` and never a fragment.** It is a
  pandan PAT, so exfiltrating it hands over the kanban board too (ADR 0002), and KAN-554's preview
  will render user markdown to HTML in this origin. `lib/auth.ts` has the full argument.
- **Zero runtime dependencies.** Everything in `package.json` is a devDependency, so the shipped
  bundle is our own code. CodeMirror 6 is the first crossing and it is KAN-553's to make, with a
  bundle-size delta in its PR (ADR 0001 §2).

### Testing

`vitest`, with `node` as the default environment. A test that needs a DOM asks for one per file:

```ts
// @vitest-environment jsdom
```

Component tests use Svelte's own `mount` / `unmount` / `flushSync` — there is no testing library, on
the same "each dependency is a decision" grounds as the rest. `tests/dev-proxy.test.ts` imports
`vite.config.ts` and stays in `node`, because a config module evaluated inside a fake DOM is one
whose environment checks can lie.

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

The element is already there. `components/EditorPane.svelte` holds `<div class="editor-host">`, and
its `$effect` is a rehearsal of the real one: it creates a node imperatively, appends it to the
container, and removes it on teardown — exactly where `new EditorView({ parent })` and
`view.destroy()` go. **Replace those two statements; do not move the boundary.** Nothing in the
markup may put a node inside that element, in this card or in KAN-553, which is what
`tests/shell.test.ts` checks by asserting the note body renders outside it.
