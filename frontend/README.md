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
is built inside, and KAN-553 put CodeMirror 6 in it. What is here is a browsable three-region app
with a working markdown editor that saves under ADR 0009's precondition; what is not is a live
preview, a folder tree, a landing state or the conflict banner (KAN-554/555/556).

## The layout, and who replaces what

Each remaining V3 card replaces **one file**, which is the whole reason the layout is written down:

```
src/
  App.svelte                 the shell: layout regions, the route, the two reads they need
  app.css                    design tokens (--ink, --paper, --muted, --edge, --accent, --sans, --mono)
  lib/api.ts                 apiPath + apiRequest — the one place a request happens
  lib/auth.ts                the credential seam: the only module that knows what a bearer is
  lib/editor.ts              the editor's two guards + ADR 0009's two versions, as pure functions
  lib/notes.ts               the five note calls
  lib/router.ts              / and /notes/:ref, hand-written, no dependency
  lib/types.ts               the wire shapes, mirroring backend/app/api/schemas.py
  components/EditorPane.svelte CodeMirror 6, mounted once per note (KAN-553)
  components/Sidebar.svelte    → KAN-554 (folder tree, real list, preview)
```

Three rules that are decisions rather than layout, each argued in the file that holds it:

- **No shaping in the SPA.** No `--fields`-style projection, no truncation hint, no `{"count": n}`.
  The API returns complete records to a browser on purpose (ADR 0004 §Decision); those three are
  agent ergonomics living in `kaya-client`, and a copy here is the bug ADR 0004 exists to prevent.
  Rendering markdown to HTML for preview *is* the SPA's job — that is presentation, not shaping.
- **The token is `sessionStorage`, and the UI says `set` or `not set` and never a fragment.** It is a
  pandan PAT, so exfiltrating it hands over the kanban board too (ADR 0002), and KAN-554's preview
  will render user markdown to HTML in this origin. `lib/auth.ts` has the full argument.
- **Five runtime dependencies, and they are all CodeMirror.** `@codemirror/state`, `view`,
  `commands`, `language` and `lang-markdown` (all MIT) are the **first** runtime dependencies this
  project has ever taken; KAN-553 made that crossing with the bundle delta in its PR, as ADR 0001 §2
  obliges. Everything else in `package.json` is still a devDependency. The next addition is a
  decision of the same size, so measure it the same way (`npm run build`, then `gzip -9`).

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

## CodeMirror, and the two guards that are the whole point

CodeMirror owns its DOM subtree: `<div class="editor-host">` in `EditorPane.svelte` is Svelte's, and
**everything inside it is CM6's**. Nothing in the markup may put a node in there — no `{#if}`, no
interpolated text, not one word — because from that moment CM6's transactions and Svelte's rerenders
are editing one subtree. `tests/editor-container.test.ts` parses the component and asserts the
container has zero template children; `tests/shell.test.ts` asserts over `childNodes` that every node
in it was made by the `$effect`. Even the "No note open." zero state is CM6's own `placeholder()`
extension rather than a Svelte node, which is why the container needs no children to say it.

Two guards keep the rune binding from looping, they guard **opposite directions**, and they are not
interchangeable. Both live in `lib/editor.ts` as pure predicates so they can be tested in `node`:

- **The identity guard** (`needsRemount`), on the way *in*. Reading the `note` prop registers it, so a
  parent handing down a new object per keystroke re-runs the effect **whichever field you read** —
  `note.ref` and `note.body` are the same signal. So "depend on identity" means *compare* the incoming
  `note.ref` against the ref the view was built for and return early when they match. A new document
  for the same note goes in as a transaction; only a different ref rebuilds.
- **The echo guard** (`needsDispatch`, applied by `syncDocument`), on the way *back in*. CM6's
  `updateListener` fires for every transaction including our own, so
  `updateListener → set rune → effect → dispatch → updateListener` is a live cycle unless the incoming
  value is compared against `view.state.doc.toString()` first. Un-guarded, this is not subtle: in
  jsdom it recurses to `RangeError: Maximum call stack size exceeded`.

There is a third check beside them, and it is bookkeeping rather than a guard: the incoming document is
only offered to the echo guard when the **prop** moved (`appliedBody`). The two catch disjoint cases. A
parent re-rendering with a new object whose content is unchanged, while you are typing, produces a body
that differs from the editor's document — so the echo guard would let it through and your edit would
vanish on a re-render that changed nothing.

One consequence worth knowing before you edit the effect: **the teardown is not in that effect's
cleanup.** Svelte runs an effect's cleanup before every re-run, and the re-run is unavoidable, so a
`return () => view.destroy()` there would destroy the view on exactly the content change the identity
guard exists to survive. The per-note destroy sits in the effect body beside the construction it
replaces; the per-component destroy is a second effect that reads nothing.

### Saving

`Save` (or `Mod-s`) `PATCH`es the body with `if_updated_at` set to the `updated_at` this edit was based
on — ADR 0009's precondition, carried as an **opaque string** and never near a `Date`, because the
backend's comparison is exact to the microsecond. The precondition is never *fetched*: it comes from
the note that was opened and then from each save's own response. Fetching it would look safer and
would disable the guarantee.

A `409` is shown with both timestamps and both whole notes held in state. That is deliberately **not**
the banner — KAN-556 owns the side-by-side and keep-mine / keep-theirs, and `conflictVersions()` is
where it reads `attempted` / `stored` from.

### The bundle, which is the number ADR 0001 §2 asked for

Re-measurable in two commands, and worth re-measuring whenever a CodeMirror package is added:

```bash
npm run build
for f in dist/assets/*; do echo "$f $(stat -c%s "$f") $(gzip -9 -c "$f" | wc -c)"; done
```

KAN-553, measured that way (`vite build` reports gzip at a lower level, so it says `118.98 kB` where
`gzip -9` says `117,173 B` — quote whichever, but say which):

| | before (KAN-552) | after (KAN-553) | delta |
|---|---|---|---|
| JS raw | 42,911 B | 356,640 B | **+313,729 B (+731%)** |
| JS gzip -9 | 16,667 B | 117,173 B | **+100,506 B (+603%)** |
| CSS raw | 3,212 B | 3,611 B | +399 B (+12.4%) |
| CSS gzip -9 | 1,175 B | 1,249 B | +74 B (+6.3%) |

One JS chunk and one CSS file, so an editor page fetches **360,251 B raw / 118,422 B gzip -9** in
total and there is no second request hiding behind the entry number. CSS barely moves because CM6
injects its own styles through `style-mod` at runtime — the editor's theme is JavaScript, which is
also why it can read `app.css`'s tokens.

`markdownLanguage.extension` is installed rather than `markdown()`, and that is where 187,820 B raw /
69,497 B gzip went **un**spent: `markdown()` wires `@codemirror/lang-html` in for raw-HTML blocks, and
that drags `lang-javascript` and `lang-css` behind it. The component's comment carries the measurement.
The remaining cost is CodeMirror's core (state + view + commands ≈ 268 kB raw on its own) and the
markdown grammar, and there is no version of a real editor that does not pay it.
