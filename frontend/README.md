# kaya frontend

Svelte 5 (runes) + Vite + TypeScript, on `npm`.

```bash
npm ci
npm run dev      # http://localhost:5173, /api proxied to the backend on :8000
npm run build    # -> dist/
npm run lint     # eslint + svelte-check
npm test         # vitest, once
```

KAN-531 got the toolchain and the dev proxy working; KAN-552 added the app skeleton the rest of V3 is
built inside, KAN-553 put CodeMirror 6 in it, KAN-555 added the way in, KAN-556 the conflict banner,
KAN-554 the folder tree and the live preview, and KAN-767 and KAN-836 moved the editor and the
preview's markdown grammar out of the entry chunk. What
is here is the whole of V3: a browsable three-region app with a folder tree over `path`, a live
preview, and a markdown editor that saves under ADR 0009's precondition and offers keep mine / keep
theirs / side by side when it is refused — and that arrives on its own chunk, when a note is opened.

## The layout, and who replaces what

Each remaining V3 card replaces **one file**, which is the whole reason the layout is written down:

```
src/
  App.svelte                 the shell: layout regions, the route, the two reads they need
  app.css                    design tokens (--ink, --paper, --muted, --edge, --accent, --sans, --mono)
  lib/api.ts                 apiPath + apiRequest — the one place a request happens
  lib/auth.ts                the credential seam: the only module that knows what a bearer is
  lib/editor.ts              the editor's two guards + ADR 0009's two versions, as pure functions
  lib/codemirror.ts          every runtime CodeMirror value, behind one import() (KAN-767)
  lib/markdown.ts            markdown -> DOM nodes, behind one import() (KAN-554, KAN-836)
  lib/notes.ts               the five note calls
  lib/router.ts              / and /notes/:ref, hand-written, no dependency
  lib/types.ts               the wire shapes, mirroring backend/app/api/schemas.py
  lib/conflict.ts            ADR 0009's resolution rule + the side-by-side comparison (KAN-556)
  lib/backlinks.ts           the rail's five states + its identity guard, as pure functions (KAN-568)
  lib/wikilinks.ts           `[[...]]` span-finding, link matching and the `[[` trigger, as pure functions (KAN-567)
  components/EditorPane.svelte CodeMirror 6, mounted once per note (KAN-553); owns the write path
  components/ConflictBanner.svelte keep mine / keep theirs / side by side (KAN-556)
  components/Landing.svelte    the no-credential state and the one-time PAT paste (KAN-555)
  components/Sidebar.svelte    the folder tree over `path`, the flat list, the search box (KAN-554/559/962)
  components/PreviewPane.svelte live preview, a sibling of the editor (KAN-554, KAN-836)
  components/BacklinksPanel.svelte what links to the open note — the fourth region (KAN-568)
```

Three rules that are decisions rather than layout, each argued in the file that holds it:

- **No shaping in the SPA.** No `--fields`-style projection, no truncation hint, no `{"count": n}`.
  The API returns complete records to a browser on purpose (ADR 0004 §Decision); those three are
  agent ergonomics living in `kaya-client`, and a copy here is the bug ADR 0004 exists to prevent.
  Rendering markdown to HTML for preview *is* the SPA's job — that is presentation, not shaping.
- **The token is `sessionStorage`, and the UI says `set` or `not set` and never a fragment.** It is a
  pandan PAT, so exfiltrating it hands over the kanban board too (ADR 0002), and KAN-554's preview
  now renders user markdown to HTML in this origin. `lib/auth.ts` has the full argument, and
  `lib/markdown.ts` is the other half: it builds DOM nodes and never an HTML string, so there is no
  `{@html}` anywhere in `src/` and `tests/no-html-injection.test.ts` asserts that over parsed ASTs.
- **Eight runtime dependencies, and they are all CodeMirror or already inside it.**
  `@codemirror/state`, `view`, `commands`, `language` and `lang-markdown` (all MIT) are the **first**
  runtime dependencies this project has ever taken; KAN-553 made that crossing with the bundle delta
  in its PR, as ADR 0001 §2 obliges. KAN-554 added `@lezer/markdown` and `@lezer/common`, and those
  two are a **declaration rather than an addition**: `lang-markdown` already imports the markdown
  parser from them to build `markdownLanguage`, so `package-lock.json` gained no package and the
  bundle gained no byte (measured below). They are declared because importing a transitive dependency
  directly is how a version constraint goes missing. KAN-567 added `@codemirror/autocomplete` — an
  official CodeMirror package extending a dependency already accepted, imported only from
  `lib/codemirror.ts` like the other five and measured the same way (below). Everything else in
  `package.json` is still a devDependency, and the next addition that actually costs bytes is a
  decision of the same size as KAN-553's — measure it the same way (`npm run build`, then `gzip -9`).

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

**KAN-767 made the library lazy and deliberately left that effect synchronous**, because those two
sentences are the reason the obvious lazy implementation is wrong. Put the `await import()` at the top
of the mount effect and two runs of it can be in flight at once: a cleanup firing while run A is still
awaiting sees `view === undefined`, destroys nothing, and then A resolves and builds into a container
run B is also building into — two views in one host, or an orphan whose `destroy()` will never be
called. So the `import()` lives in the *second* effect, the one that reads nothing, which therefore
runs exactly once per component; the mount effect only **reads** the resulting rune, and returns early
while it is `null` exactly as it already did while `host` was `undefined`. There is nothing to cancel
because nothing races. `tests/editor-lazy-mount.test.ts` acts inside that gap — navigating and
unmounting before the module lands — and `tests/editor-chunk-failure.test.ts` covers the chunk that
never arrives, which is a state the entry bundle could not be in.

### Saving

`Save` (or `Mod-s`) `PATCH`es the body with `if_updated_at` set to the `updated_at` this edit was based
on — ADR 0009's precondition, carried as an **opaque string** and never near a `Date`, because the
backend's comparison is exact to the microsecond. The precondition is never *fetched*: it comes from
the note that was opened and then from each save's own response. Fetching it would look safer and
would disable the guarantee.

A `409` is shown with both timestamps and both whole notes held in state; `conflictVersions()` reads
`attempted` / `stored` out of `ApiError.details`.

### The conflict banner (KAN-556)

`ConflictBanner.svelte` is markup and two callbacks. Everything that can be wrong lives elsewhere on
purpose:

- **`lib/conflict.ts`** holds `keepMinePatch()` — `body` from `attempted`, `if_updated_at` from
  **`stored`**, both verbatim. That crossing *is* the resolution mechanism, and it is a pure function
  because it is the second place in this SPA a precondition is built; `tests/conflict.test.ts` asserts
  the stamp is not `new Date(stamp).toISOString()`, which would round `.881903` to `.881` and refuse
  every correct write.
- **`EditorPane.svelte`** owns the write path, so both buttons come back to it. "Keep mine" is one
  more `PATCH` through the same function the Save button uses. "Keep theirs" makes **no request** —
  the stored version already is what the server holds — and puts the stored body in through
  `syncDocument` as a transaction carrying `isolateHistory.of('full')`, because the discarded text's
  only copy is CM6's undo and without the isolation CM6 merges the discard into the typing group it
  interrupted, so one undo would throw the user's own text away as well.
- **The banner is a sibling of the editor container, never a child** (PLAN §S9). Both S9 guards cover
  it: the source-level one would name `<ConflictBanner />` as a template child, and
  `tests/conflict-banner.test.ts` asserts the rendered banner is outside the container with the live
  view's DOM node unchanged across both resolutions.

The side-by-side is **a bound, not a diff**. `splitOnChange()` trims the lines the two bodies share at
each end and marks the region between them; the unmarked parts are byte-identical strings, so no
difference can hide there, and it aligns nothing so it cannot mis-align anything. An LCS line diff
would mark less and would be the first thing here that can be *wrong* about what changed while looking
authoritative — ADR 0009's own objection to auto-merging prose, one step down.

It costs **786 B raw / 260 B gzip -9** across both assets (JS 368,294 → 368,984 raw and 121,309 →
121,553 gzip; CSS 6,197 → 6,293 and 1,721 → 1,737), measured by building with the three segments
collapsed back to one — `{split.mine.before}<mark>…` → `{versions.attempted.body}`, `splitOnChange`
deleted — and diffing the assets. That is 0.2% of the entry chunk, and it is the whole of the
"highlighting" this card does. Both bodies render whole and byte for byte either way, because the three
segments are slices of the original.

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

KAN-555 and KAN-556 then added the landing state and the conflict banner. Measured the same way, on
the same tree, against `origin/main` at `82f867f`:

| | before (KAN-555) | after (KAN-556) | delta |
|---|---|---|---|
| JS raw | 363,513 B | 368,984 B | **+5,471 B (+1.5%)** |
| JS gzip -9 | 119,796 B | 121,553 B | **+1,757 B (+1.5%)** |
| CSS raw | 4,769 B | 6,293 B | +1,524 B (+32.0%) |
| CSS gzip -9 | 1,466 B | 1,737 B | +271 B (+18.5%) |

KAN-554 then added the folder tree, the note list and live preview. Measured the same way, against
`origin/main` at `8f0dc9c` (KAN-556's tip, which is also this branch's baseline once merged):

| | before (KAN-556) | after (KAN-554) | delta |
|---|---|---|---|
| JS raw | 368,984 B | 381,926 B | **+12,942 B (+3.5%)** |
| JS gzip -9 | 121,553 B | 125,862 B | **+4,309 B (+3.5%)** |
| CSS raw | 6,293 B | 10,590 B | +4,297 B (+68.3%) |
| CSS gzip -9 | 1,737 B | 2,421 B | +684 B (+39.4%) |

Those are the figures **after** review, and the JS number went *down* by 376 B raw / 188 B gzip when
`lib/livedoc.ts` was replaced by `EditorPane`'s `ondocument` prop: a published callback costs less than
a `MutationObserver`, a `WeakMap` and a `StateEffect.appendConfig` attach. The better seam was also the
cheaper one, which is not always how that goes and is worth writing down when it is.

**The markdown parser is free, and that is measured rather than argued.** `lib/markdown.ts` walks
`@lezer/markdown`'s syntax tree, which `@codemirror/lang-markdown` already imports to build
`markdownLanguage` — the extension `EditorPane.svelte` mounts. Two proofs: `package-lock.json`'s diff
adds **zero packages**, and a measurement build with the import deleted and the parse call stubbed out
comes back **376,851 B raw / 124,331 B gzip -9** against **376,838 / 124,319** with it — thirteen bytes
*larger*, i.e. noise from the stub. (Both measured pre-merge, against `82f867f`; the *difference* is
what the claim rests on and it does not move.) What that reuse is worth, and what the alternatives cost (esbuild,
minified, `gzip -9`):

| Option | raw | gzip -9 | Note |
|---|---|---|---|
| `@lezer/markdown` reused | **0** | **0** | already shipped for the editor |
| `@lezer/markdown`, were it not already there | 60,092 B | 19,913 B | what the reuse is worth |
| `marked` alone | 42,796 B | 12,982 B | emits an HTML **string**; no sanitiser |
| `marked` + `DOMPurify` | 72,171 B | 24,069 B | the honest comparison |
| `markdown-it` + `DOMPurify` | 142,747 B | 59,002 B | |

A sanitiser is not optional for any of the three, because each hands you HTML as a *string* built from
note content. `lib/markdown.ts` returns a `DocumentFragment` instead — `createElement` with literal tag
names, `createTextNode` for every byte of source — so there is no string to sanitise and no escaping
function to get wrong. Cheaper *and* one fewer class of bug.

So the whole JS delta is this repo's own code: the renderer, `lib/tree.ts`, two components,
`EditorPane`'s `ondocument` seam and `svelte/reactivity`'s `SvelteSet`. CSS moves proportionally more again, for the same
reason the banner's did — the preview needs a typographic stylesheet for markup Svelte did not create,
so every rule in it is `:global` under a scoped `.rendered`.

CSS moves proportionally more than JS because the banner is the first component with a real layout of
its own (a two-column grid, two scrolling `<pre>`s, a highlight) and the baseline stylesheet is small —
1.7 kB gzip is still less than 1.5% of what the page fetches. No new dependency: the comparison is
about forty lines of stdlib string work, and CodeMirror is still the only runtime dependency.

### KAN-767: the editor is its own chunk, because the landing page paid for it

Everything above was **one** JS chunk, and that became a defect the moment KAN-555 landed rather than
when KAN-553 did. A visitor with **no credential** sees the landing page and pastes a pandan PAT into
a password field; with CM6 in the entry chunk they downloaded a markdown grammar, a view layer and an
undo history first, possibly without having an account yet. So `lib/codemirror.ts` holds every runtime
CodeMirror value and `EditorPane.svelte` reaches it through one `import()`. Measured the same way,
against `origin/main` at `2adfe99`:

| | before (KAN-554) | after (KAN-767) | delta |
|---|---|---|---|
| Entry JS raw | 381,926 B | 134,770 B | **−247,156 B (−64.7%)** |
| Entry JS gzip -9 | 125,862 B | 47,581 B | **−78,281 B (−62.2%)** |
| Editor chunk raw | — | 248,645 B | new, on demand |
| Editor chunk gzip -9 | — | 79,553 B | new, on demand |
| CSS raw | 10,590 B | 10,590 B | 0 |
| CSS gzip -9 | 2,421 B | 2,421 B | 0 |

CSS does not move at all, for the reason this whole section has always given: CM6 injects its own
styles through `style-mod` at runtime, so the editor's theme is JavaScript.

What the two *pages* actually fetch, which is the number the card is about rather than the chunk list:

| Page | before | after | delta |
|---|---|---|---|
| **Landing** (no credential) — entry JS + CSS | 392,516 raw / 128,283 gzip -9, 2 requests | 145,360 / **50,002**, 2 requests | −247,156 raw / **−78,281 gzip (−61.0%)** |
| **Editor** — entry + editor chunk + CSS | 392,516 / 128,283, 2 requests | 394,005 / **129,555**, 3 requests | +1,489 raw / **+1,272 gzip (+1.0%)** |

**So an editor page fetches 1,272 B gzip more than it did, and that is the trade stated plainly.**
Splitting a bundle costs a little — a second chunk carries its own module preamble and loses some
cross-module minification — and it buys 78 KB gzip on the page where a person has not decided to use
kaya yet. The visitor the card exists for pays 61% less; the visitor who opens a note pays 1% more,
having already paid nothing for the landing page they came through. There is **no `modulepreload`** for
the editor chunk in `dist/index.html` — checked rather than assumed, because Vite emits one for
statically imported chunks and that would have made the whole split invisible at the network layer.

**One number KAN-767 did *not* fix, measured rather than guessed.** Its entry chunk was still 47,581 B
gzip and **20,585 B of that was `@lezer/markdown`** — the live preview's parser, which
`PreviewPane.svelte` imported statically. That became **KAN-836**, one section down.

The guard is `tests/editor-chunk-is-lazy.test.ts`, and it exists because this regression is silent:
one `import { EditorView } from '@codemirror/view'` at the top of any file in `src/` re-merges the
chunk with every other test still green, and the only witness would be this table, which nobody
re-measures on an unrelated card. It asserts over parsed ASTs — `svelte/compiler` for components,
`typescript` for modules, never a grep, because there are six prose mentions of `@codemirror` in
`src/` arguing about exactly this — that `lib/codemirror.ts` is the only file value-importing
`@codemirror/*` **and** that nothing static-imports it. Either alone re-merges the chunk. Type-only
imports are allowed everywhere, because `verbatimModuleSyntax` erases them and `lib/editor.ts`
legitimately has two.

One consequence for anybody writing a test: **`mount()` + `flushSync()` no longer leaves an editor in
the container.** The mount effect returns early until the module lands and then runs again, so a DOM
test has to `await editorArrived(host)` (`tests/editor-arrival.ts`) first. It polls rather than
awaiting a fixed number of microtask ticks, because the first `import()` in a worker really loads the
module while later ones resolve from the registry — a tick count would pass in whichever position the
file happened to run in.

`markdownLanguage.extension` is installed rather than `markdown()`, and that is where 187,820 B raw /
69,497 B gzip went **un**spent: `markdown()` wires `@codemirror/lang-html` in for raw-HTML blocks, and
that drags `lang-javascript` and `lang-css` behind it. The component's comment carries the measurement.
The remaining cost is CodeMirror's core (state + view + commands ≈ 268 kB raw on its own) and the
markdown grammar, and there is no version of a real editor that does not pay it.

### KAN-836: the preview's parser is its own chunk too, because signing in paid for it

KAN-767 left one number behind, and the section above records it: **20,585 B gzip — 43% of what was
left in the entry chunk — was `@lezer/markdown`**, the grammar `lib/markdown.ts` walks to build the
live preview's DOM. Same argument as KAN-767 one layer down. A visitor with no credential pays it on
the landing page, and so does a signed-in user sitting on `/`; neither can see a rendered byte, because
there is no note open. (`@lezer/markdown` costing **zero new bytes against `marked`+`DOMPurify`** is
still true and is a different question — that is the *marginal* cost of this parser against an
alternative, and this card is about the *arrival time* of bytes the app has already decided to ship.
One does not undo the other.)

So `PreviewPane.svelte` reaches `lib/markdown.ts` through one `import()`, exactly as `EditorPane.svelte`
reaches `lib/codemirror.ts`. Measured the same way, against `origin/main` at `6beaba6`:

| | before (KAN-767) | after (KAN-836) | delta |
|---|---|---|---|
| Entry JS raw | 135,663 B | 67,618 B | **−68,045 B (−50.2%)** |
| Entry JS gzip -9 | 47,883 B | 25,385 B | **−22,498 B (−47.0%)** |
| Editor chunk raw | 248,645 B | 248,644 B | −1 B |
| Editor chunk gzip -9 | 79,550 B | 79,553 B | +3 B |
| Grammar chunk raw | — | 62,042 B | new, **shared** |
| Grammar chunk gzip -9 | — | 20,362 B | new, **shared** |
| Preview chunk raw | — | 6,220 B | new, on demand |
| Preview chunk gzip -9 | — | 2,479 B | new, on demand |
| CSS raw | 11,013 B | 11,168 B | +155 B (the notice's rule) |
| CSS gzip -9 | 2,468 B | 2,476 B | +8 B |

**The grammar is shared between the two lazy chunks rather than duplicated into both, and that was
measured rather than reasoned about.** `@codemirror/lang-markdown` builds `markdownLanguage` out of
`@lezer/markdown`, so once *both* consumers are dynamic entries the grammar is reachable from two
chunks and Rollup hoists it into a third. `grep -o 'from"\./[^"]*"' dist/assets/*.js` on the built
output says so directly: `codemirror-*.js` and `markdown-*.js` each carry exactly one such edge and it
is the same file. Rollup names that chunk after the module's own directory, so it appears as
`dist-*.js` — an ugly name for the markdown grammar, left alone rather than papered over with a
`manualChunks` entry, because build configuration added for cosmetics is configuration nobody can
delete later.

What the **three** page states actually fetch, which is the number the card is about rather than the
chunk list. These are cold loads driven through CDP against `make up` on :8022 with a real PAT, with
the browser cache disabled — so the request sets below are observed, not derived:

| Page | before (KAN-767) | after (KAN-836) | delta |
|---|---|---|---|
| **Landing** (no credential) — entry + CSS | 146,676 raw / **50,351** gzip -9, 2 requests | 78,786 / **27,861**, 2 requests | −67,890 raw / **−22,490 gzip (−44.7%)** |
| **Note list at `/`** (signed in, nothing open) | 395,321 / **129,901**, 3 requests | 395,692 / **130,255**, 5 requests | +371 raw / **+354 gzip (+0.3%)** |
| **Note open, preview showing** | 395,321 / **129,901**, 3 requests | 395,692 / **130,255**, 5 requests | +371 raw / **+354 gzip (+0.3%)** |

**The last two rows are identical, and that is a fact about the app rather than a rounding.**
`EditorPane` sits **outside** the preview toggle's `{#if}` (see `App.svelte`, and `tests/preview.test.ts`
for why), and `previewing` starts `true`, so a signed-in user on `/` already mounts both panes with
`note === null`. Every cold load that has a credential fetches all five assets; every cold load that
does not fetches two. There is no fourth state to quote — toggling the preview off after the fact
cannot un-fetch a chunk, and `previewing` is not persisted, so "preview off" is not a page a visitor
can land on.

**So the trade is: −22,490 B gzip on the page where a person has not decided to use kaya yet, against
+354 B gzip and two extra requests on every page where they have.** That is 0.3% more on a signed-in
load, and it buys 44.7% less on the landing page — the same shape of trade KAN-767 made (−61% / +1.0%),
one layer down and with a better ratio. Two things make the extra requests cheaper than the count
suggests: they are **parallel**, and they are not on the critical path — a note page's slowest asset is
the 79,553 B editor chunk, and the grammar (20,362) and the preview's own module (2,479) are fetched
alongside it. The preview also had nothing to render before the editor arrived, because its `source`
comes from `EditorPane`'s `ondocument` seam, so waiting for a second chunk costs it no frame it was
going to paint. There is still **no `modulepreload`** in `dist/index.html` — checked, because Vite emits
one for statically imported chunks and that would make the whole split invisible at the network layer.

One honest note about the numbers above, **updated by KAN-963**: at the time this paragraph was first
written, kaya's own origin served these assets uncompressed — the entry chunk arrived as 67,970 B on
the wire against 67,618 B on disk, and the `gzip -9` column was what a *compressing edge* would
deliver rather than what `make up` did. That gap was roughly 3x on every table on this page, and
KAN-963 closed it the cheap way: `backend/app/main.py` now wraps the app in Starlette's
`GZipMiddleware` (default 500-byte threshold, `compresslevel=9`, so `/health`'s tiny JSON is left
alone and a note body or a static asset is not), because there is no compressing edge in front of
`make up` and ADR 0010/KAN-722 is not building one soon. Re-measured against a real single-origin
`uv run uvicorn` process serving this build with `KAYA_SPA_DIST`: the entry chunk arrives as
**26,542 B on the wire** with `Content-Encoding: gzip`, against `gzip -9`'s 26,495 B on disk — a 47 B
difference (0.2%) from streaming the compression in chunks rather than over the whole file at once.
The `gzip -9` column is therefore, as of this measurement, **within a couple hundred bytes of what
`make up` actually sends** rather than merely what an edge would — checked, not assumed: uvicorn
implements no `http.response.pathsend` ASGI extension, so the static `FileResponse`s `app/spa.py`
serves go through GZipMiddleware exactly like a JSON body would. `vite build` prints gzip at a lower
level than `gzip -9`, so it says `25.69 kB` where `gzip -9` says `25,385 B` (an older build; see the
KAN-567 table above for the current entry chunk's numbers).

The guard is `tests/preview-chunk-is-lazy.test.ts`, and it is `tests/editor-chunk-is-lazy.test.ts`'s
twin because the regression is the same silent one: `lib/markdown.ts` is the only file under `src/` that
may value-import `@lezer/*`, **and** nothing may static-import `lib/markdown.ts`. Either alone
re-merges the grammar into the entry chunk with every other test still green. The AST scanner both
files use now lives in `tests/module-graph.ts`; two copies of it would be two instruments that can drift
apart while both look green, and each guard keeps its own positive controls. There is a third assertion
in that file which is not a bundle rule at all: `lib/markdown.ts` has to stay **under `src/`**, because
`tests/no-html-injection.test.ts` and `tests/markdown.test.ts` both sweep that tree, and the obvious
wrong turn on this card was moving the DOM-building code somewhere those globs stop reaching — the XSS
guard would narrow its scope silently and stay green.

**The hazard here is not the editor's hazard, and that distinction is the whole of the design.**
KAN-767's rule — put the `import()` in the effect that reads nothing, and have the consumer *read* the
resulting rune — is followed to the letter, but for a different reason. `EditorPane` builds a stateful
object into a host and owns a teardown, so an `await` at the top of its mount effect risks two views in
one container or an orphan whose `destroy()` is never called. `PreviewPane` builds nothing and tears
nothing down: `replaceChildren` is total and idempotent, so a second run cannot leak the first. What an
`await` costs *here* is the **subscription** — Svelte registers an effect's dependencies during its
synchronous pass only, so `source` read after an `await` is never a dependency, and the preview renders
the document it was mounted with and then never moves again. No error, no leak, nothing in the DOM to
look at. That was measured by building the naive version: `tests/preview-lazy-render.test.ts`'s
`keeps rendering every later document` and `renders inside the same flush` both go red, and so do six
tests in `tests/preview.test.ts`; the in-flight-navigation test stays **green**, for exactly the reason
KAN-767 recorded about its own navigation tests, because with one shared module promise the runs resolve
in queue order.

Two consequences for anybody writing a test. **`mount()` + `flushSync()` no longer leaves rendered
markup in the preview**, so a DOM test awaits `previewRendered(host)` (`tests/preview-arrival.ts`) —
one await per mounted preview, at the first point a non-empty document reaches it, because *after*
arrival the render effect only reads a rune and a keystroke is painted inside its own `flushSync`. It
polls rather than counting microtask ticks, for the same reason `editor-arrival.ts` does. And a chunk
that never arrives is a real state: `[data-testid="preview-unavailable"]` is a **sibling** of the
`.rendered` element, never a child of it, for the same reason `EditorPane`'s notice is a sibling of
PLAN §S9's container — the element whose children belong to `replaceChildren` cannot hold the sentence
explaining why `replaceChildren` never ran.

## The sidebar's two views, and what a search does to them (KAN-962)

The sidebar has a folder tree over `path` (KAN-554) and a flat list, toggled, and the tree is the
default. **A search is rendered by the flat list, whatever the toggle was set to**, and this is the
one place in the SPA where a rendering decision needed an argument written down.

`GET /api/v1/notes?q=` returns notes in relevance order — `ts_rank DESC, note.id DESC`, and KAN-558
went to real trouble over that tie-break because equal ranks are common rather than exotic. The tree
groups by the `path` column, so it *cannot* carry an arbitrary row order: a folder exists because
some note's path names it, folders sort before leaves, and notes with no path sit in a group below the
whole tree. Whatever order the server chose is destroyed by the grouping. The tree is not sorting
wrongly — it is answering a different question — and because it is the **default** view, the default
rendering of a search was the one that threw the ranking away, silently.

Measured in a browser against `make up` and a real PAT, on a seeded corpus where two notes tie at
`0.9910322` and the tie-break decides them:

| | order |
|---|---|
| API — `GET /api/v1/notes?q=reading list`, by `curl` | `NOTE-2, NOTE-1, NOTE-3` |
| Sidebar, **Tree** view (the default) — before | `NOTE-3, NOTE-1, NOTE-2` |
| Sidebar, **List** view — before | `NOTE-2, NOTE-1, NOTE-3` |
| Sidebar, either view — after | `NOTE-2, NOTE-1, NOTE-3` |

Three parts, each a decision rather than an implementation detail:

- **The chosen view is a rune of its own (`chosen`) and a search never writes it.** So clearing a
  search puts a person back in the view they picked. Switching the view *for* them — the card's
  option (a) — looks identical on screen and is not the same thing, because nothing would ever switch
  it back.
- **The view toggle leaves the screen while a search is active.** It is the other arm of the same
  `{#if}` that renders the notice, so "a toggle reading `Tree` above a flat list" is unreachable
  rather than merely untested. Disabling it instead would keep a highlighted `Tree` on screen over a
  flat list, which is the same lie with a layer of grey on top.
- **One line says what the ordering is**, in the toggle's place: *Ordered by relevance, not grouped by
  folder. The view toggle returns when you clear the search.* It is the honest half of the card's
  option (b), and it is also the only thing that says where the toggle went. It shows for a search
  that matched nothing too — the toggle has to be gone in that state for the same reason, so a
  sidebar with neither the toggle nor the sentence would explain less.

Not built, deliberately: ranking the *folders* by their best-matching note (option (c)). It is a real
algorithm needing its own invariant beside `countNotes(buildTree(xs)) === xs.length`, and it is a
different card.

Ordering and grouping records the caller already holds is **presentation, not payload shaping**, so
this is the SPA's decision to make (ADR 0004 §Decision, and `lib/api.ts`'s header). Nothing here
projects a field, cuts prose or counts anything.

`tests/sidebar.test.ts` asserts all of it over the rendered DOM, and its first assertion is a
**positive control**: the same three notes really do render in a different order in the tree, so the
order assertions below it cannot be passing against a corpus that fails to tell the two orders apart.

### The bundle

One `{#if}`, one `<p>` and one CSS rule, measured the same way as every table above (`npm run build`,
then `gzip -9`), against `origin/main` at `56464f0`:

| | before | after | delta |
|---|---|---|---|
| Entry JS raw | 67,618 B | 67,918 B | +300 B (+0.4%) |
| Entry JS gzip -9 | 25,385 B | 25,477 B | **+92 B (+0.4%)** |
| CSS raw | 11,168 B | 11,270 B | +102 B (+0.9%) |
| CSS gzip -9 | 2,476 B | 2,491 B | **+15 B (+0.6%)** |
| Editor chunk gzip -9 | 79,553 B | 79,553 B | 0 |
| Grammar chunk gzip -9 | 20,362 B | 20,362 B | 0 |
| Preview chunk gzip -9 | 2,479 B | 2,479 B | 0 |

The three lazy chunks come out byte-identical with the same content hashes, which is the check worth
making rather than the total: this card touches one component that was already in the entry chunk, so
anything moving in `codemirror-*.js` or `dist-*.js` would mean an import had migrated. A landing page
fetches **27,968 B gzip** against 27,861 (2 requests either way, **+107 B / +0.4%**); a signed-in load
fetches **130,362 B** against 130,255 across the same 5 requests.

## KAN-568: the backlinks rail

`GET /api/v1/notes/{ref}/backlinks` (KAN-566) reaches the browser as `components/BacklinksPanel.svelte`:
every note whose body links to the one that is open, in the shell's **fourth** region.

Four decisions, each argued in the file that holds it.

**It is a region of the shell, not a third column of `.split`.** `App.svelte` was three layout regions
"and nothing else", so the fourth is a deliberate exception rather than drift. A rail inside `main`
would be a sibling of `{#if previewing}`, and KAN-554 and KAN-962 both paid for the rule that a command
about one pane must not disturb another's state. Outside `main` the preview toggle **cannot reach it at
all** — the structural form of the property rather than the carefully-placed one. It also is not a pane
of the document, so it does not want one of `.split`'s `minmax(0, 1fr)` tracks; the grid becomes
`minmax(12rem,18rem) 1fr minmax(11rem,16rem)`, and under 60rem the rail moves *below* the document
rather than becoming a third cramped column. `{#if railed}` and `class:railed` are **one expression**,
because a column with no rail is an empty stripe and a rail with no column overlaps `main`.

**Its state is a closed union, because the bug this card would otherwise ship is "nothing links here"
and "the request failed" sharing a sentence.** `lib/backlinks.ts`'s `panelState` returns one of
`closed | loading | failed | empty | listed`, so collapsing two of them into an `{:else}` stops
type-checking instead of merely reading badly, and the precedence — `closed` beats `loading` beats
`failed` beats the rows — is a pure function with a test naming each step rather than a chain of
`{#if}`s in markup. `empty` and `failed` **name the ref**, because the fetch is asynchronous and the
prop moves first, so a zero state that does not name its note is indistinguishable from the previous
note's left on screen. Same care as `Sidebar.svelte`'s `No notes match "…"`.

**`needsFetch` is the identity guard, and it is `lib/editor.ts`'s `needsRemount` one component over.**
Reading the `note` prop in an effect registers the *whole* prop, so a parent handing down a new object
re-runs that effect whichever field is read — `note.ref` and `note.body` are one signal. So the rail
compares the incoming ref against the ref it already asked about, and that comparison is a pure
function in `node`. Two consequences that are not obvious:

- **The abort is not in that effect's cleanup.** Svelte runs a cleanup before every re-run, and the
  re-run is the no-op the guard returns out of, so an `AbortController` cancelled there kills a live
  request nobody replaced and the panel sits on `Loading…` for ever. The supersede is in `load()`,
  beside the request it replaces; the per-component abort is the second effect, which reads nothing.
  **That was found by a mutation coming back green** — every assertion in the file waited for the
  request to settle before touching the prop, so nothing stood in the window. It has its own test now.
- **There is deliberately no automatic refresh.** Inbound links change when *another* note's body
  changes — in another tab, another session, or an agent's `kaya note edit` — and this app is not told.
  A panel refetching on save would be right about exactly one of the ways it goes stale (the open note
  linking to its own title, which `app/api/links.py` documents as a real backlink) and silently wrong
  about the rest, while *looking* live. A **Refresh** button that says what it does is the honest
  version, and it doubles as the way out of `failed`.

**A backlink's title is prose somebody else wrote, so the rail is the app's second user-content
surface.** It reaches the DOM through Svelte text interpolation and nothing else: no `{@html}`, no
attribute value derived from the payload — the only `href` in the rail is a route built from a ref, so
the preview's protocol allow-list has no analogue to need here. Driven in a real browser against a note
whose title concatenates a `<script>` element, an `<img src=x onerror=…>` and a markdown link with a `javascript:` target: **0** elements created from the
payload, the title in exactly **one** `Text` node holding it byte for byte, **0** attributes whose name
starts with `on`, the serialized HTML carrying `&lt;script&gt;` and not `<script>`, and
`globalThis.KAYA_XSS === false`.

**What a click does about unsaved changes: nothing, on purpose.** Clicking a backlink navigates through
`interceptClick`, exactly as a sidebar row does — and, exactly as a sidebar row does, it discards an
unsaved edit silently (driven and confirmed: typed text gone, no dialog). That is a **pre-existing
property of every link surface in this app**, not something this card introduces, and guarding only the
rail would make one of three navigation surfaces behave differently from the other two. Guarding all of
them is a router-level card with a `beforeunload` in it.

Two things this rail is deliberately **not**. It does not show `/links`: outbound wikilinks are
KAN-567's, rendered as pills *in the document* where the resolved title and column decorate the link a
person typed, and a second listing here would be that card's data with worse words. It also matters for
what this panel demonstrates — `/links` resolves `KAN-`/`EPIC-` refs against pandan and degrades when
pandan is away, `/backlinks` is a join over two of kaya's own tables and cannot, and one heading over
both is how R5.1 stops being observable. And it does **not** shape a payload (ADR 0004): the number
beside the heading is `panel.notes.length`, a label on rows already on screen, which is the call
`Sidebar.svelte` already made for its `no path` group. Worth being exact about, because it would be easy
to assume the count came over the wire: it did not and could not — `NoteList` is `{"notes": [...]}` and
`backend/app/api/schemas.py` records that `summary` is deliberately absent, since the aggregate is
attached inside `render()` and is therefore `kaya-client`'s.

### The bundle

Measured the same way as every table above (`npm run build`, then `gzip -9`), against `origin/main` at
`fcc09ec`:

| | before | after | delta |
|---|---|---|---|
| Entry JS raw | 67,918 B | 71,138 B | +3,220 B (+4.7%) |
| Entry JS gzip -9 | 25,477 B | 26,329 B | **+852 B (+3.3%)** |
| CSS raw | 11,270 B | 13,219 B | +1,949 B (+17.3%) |
| CSS gzip -9 | 2,491 B | 2,708 B | **+217 B (+8.7%)** |
| Editor chunk raw / gzip -9 | 248,644 / 79,553 B | 248,644 / 79,553 B | 0, **same content hash** |
| Grammar chunk raw / gzip -9 | 62,042 / 20,362 B | 62,042 / 20,362 B | 0, **same content hash** |
| Preview chunk raw / gzip -9 | 6,220 / 2,479 B | 6,220 / 2,479 B | 0, **same content hash** |

**The three unchanged content hashes are the check worth making, more than the totals.**
`codemirror-BTCbquzj.js`, `dist-BF334o2X.js` and `markdown-CaOVSkpt.js` are byte-identical filenames
before and after, which is what says no import migrated: a stray `import { EditorView } from
'@codemirror/view'` anywhere in `src/` re-merges ~80 kB gzip with every test still green, and the hash
is the only witness that does not depend on somebody re-reading this table.

What the two page states actually fetch:

| Page | before | after | delta |
|---|---|---|---|
| **Landing** (no credential) — entry + CSS | 79,188 raw / **27,968** gzip -9, 2 requests | 84,357 / **29,037**, 2 requests | +5,169 raw / **+1,069 gzip (+3.8%)** |
| **Signed-in note** — entry + CSS + all three chunks | 396,094 / **130,362**, 5 requests | 401,263 / **131,431**, 5 requests | +5,169 / **+1,069 (+0.8%)** |

Both rows move by the same 1,069 B because only the entry chunk and the stylesheet changed. CSS moves
proportionally more than JS for the reason the banner's and the preview's did — the rail is a fourth grid
region with a responsive fallback, and the baseline stylesheet is small.

**The rail is not its own chunk, and that is a measurement rather than an omission.** It is 852 B gzip in
the entry, paid by a visitor with no credential. KAN-767 measured the standing cost of one more chunk
boundary at **+1,272 B gzip** on the page that fetches it (a second module preamble, plus the
cross-module minification a split gives up), so a chunk here would cost the signed-in page more than it
saves the landing page. The thresholds that justified `lib/codemirror.ts` (79,553 B) and
`lib/markdown.ts` (20,362 B) are two orders of magnitude away.

## KAN-567: wikilink pills and `[[` autocomplete

`[[KAN-501]]` and `[[Some Note Title]]` now render as a pill in the editor, and typing `[[` opens
autocomplete over existing note titles. This is the last card in V5.

**The pill is `Decoration.mark`, not a widget that replaces the raw text.** `lib/wikilinks.ts` mirrors
`backend/app/wikilinks.py`'s two regexes (a pandan ref, a note title, fences excluded) as pure
functions, tested in `node`; `lib/codemirror.ts` turns a match against `/links`' answer into a CSS
class and a native tooltip carrying the demo's `KAN-501 · in_progress · "…"` string. The underlying
`[[KAN-501]]` stays exactly what the caret can select and edit — nothing about the document changes,
only how it is painted — which is the same convention `lib/markdown.ts`'s `unlinked()` already uses
for a refused preview link (an explanation in `title`, not a rewrite of what is on screen). Resolved
gets the accent-tinted rounded badge `App.svelte`'s `.toggle.on` already uses; unresolved gets
`.unlinked`'s muted, dotted-underline treatment, so a link that could not be confirmed reads the same
way in the editor as it does in the preview beside it.

**`EditorPane.svelte` fetches `/links` itself, keyed on the `note` prop — a sibling of
`BacklinksPanel.svelte`'s state machine rather than a value threaded down from `App.svelte`.** Reusing
`lib/backlinks.ts`'s `needsFetch` for the identity guard is deliberate: the comparison it makes (the
incoming ref against the ref already asked about) is exactly the same question asked about the same
prop, so a third use is reuse rather than the kind of coincidence this repo usually duplicates on
purpose. A fresh answer reaches an already-live view through `setWikilinks`, dispatched as a
`StateEffect` outside any transaction the caller has in flight — `createView`'s `links` seeds only the
first paint.

**Typed-but-unsaved links render unresolved, and that is a decision rather than a gap.** `/links`
reflects the note's last *saved* body (`note_link` reconciles on save, KAN-562, not on keystroke), so
a `[[...]]` typed since the last save has no row yet and looks identical to one the API genuinely
could not resolve — both collapse to the same muted pill, because guessing a resolution kaya's own
database does not have would show a caller something it cannot back up. The window narrows on every
successful save: `EditorPane.svelte`'s `write()` re-fetches `/links` right after `updateNote` returns,
since that is the moment the reconciler has just run against the body that was written.

**Autocomplete is `@codemirror/autocomplete`'s own `autocompletion()`, scoped to note titles only.**
There is no browser-reachable search over pandan's `KAN-`/`EPIC-` cards, so a `[[KAN-501]]` reference
is still hand-typed; the source only ever calls `lib/notes.ts`'s `listNotes` — the same unshaped call
every other reader of `/api/v1/notes` makes (ADR 0004 exempts the SPA from shaping entirely) — and
selecting a suggestion inserts `Title]]` after the `[[` already on screen. This is the one place the
"CM6 extensions read data handed to them, they do not fetch it" rule (the pill's rule) deliberately
does not apply: an async source is exactly what `autocompletion()` is built for, `context.aborted` is
how it tells a stale request from a live one, and calling `listNotes` directly from inside it is the
idiomatic use of the API CM6 offers rather than a rule bent to fit a card.

### The new dependency

`@codemirror/autocomplete` is the sixth `@codemirror/*` package this project takes, and it is not a
new *decision* the way KAN-553's first crossing was — it is an official CodeMirror package extending
a dependency already accepted, imported only from `lib/codemirror.ts` exactly like the other five.
`tests/editor-chunk-is-lazy.test.ts` covers it with no changes: the guard counts "at least five"
CodeMirror value imports out of that file and asserts nothing else in `src/` names one, so a sixth
package lands inside the same two assertions rather than needing a new one.

### The bundle

Measured the same way as every table above (`npm run build`, then `gzip -9`), against `origin/main` at
`6a97d7f`:

| | before | after | delta |
|---|---|---|---|
| Entry JS raw | 71,138 B | 71,613 B | +475 B (+0.7%) |
| Entry JS gzip -9 | 26,329 B | 26,495 B | **+166 B (+0.6%)** |
| CSS raw / gzip -9 | 13,219 / 2,708 B | 13,219 / 2,708 B | 0, same content hash |
| Editor chunk raw | 248,644 B | 286,852 B | **+38,208 B (+15.4%)** |
| Editor chunk gzip -9 | 79,553 B | 91,732 B | **+12,179 B (+15.3%)** |
| Grammar chunk raw / gzip -9 | 62,042 / 20,362 B | 62,042 / 20,362 B | 0, same content hash |
| Preview chunk raw / gzip -9 | 6,220 / 2,479 B | 6,220 / 2,479 B | 0, same content hash |

**The new bytes landed in the existing editor chunk, not a new one** — checked against the built
output rather than assumed. `lib/codemirror.ts` is still the only file that names `@codemirror/*`
values and is still reached through exactly one `import()`, so `@codemirror/autocomplete` is pulled
into `codemirror-*.js` alongside the five packages already there; the grammar and preview chunks come
out byte-identical (same content hashes), and `dist/index.html` still references only the entry chunk
and the stylesheet — no `modulepreload` for any of the three lazy chunks, exactly as before.

What the two page states actually fetch:

| Page | before | after | delta |
|---|---|---|---|
| **Landing** (no credential) — entry + CSS | 84,357 raw / **29,037** gzip -9, 2 requests | 84,832 / **29,203**, 2 requests | +475 raw / **+166 gzip (+0.6%)** |
| **Signed-in note** — entry + CSS + all three chunks | 401,263 / **131,431**, 5 requests | 439,946 / **143,776**, 5 requests | +38,683 / **+12,345 (+9.4%)** |

**The landing page barely moves, and the editor page pays the whole cost, on the day it is first
opened rather than before.** That is the same shape every split on this page has made since KAN-767,
carried one layer further: the bytes a visitor downloads are gated on having a note open, not on
having a credential. 12.3 kB gzip is a real number and it is paid once per session (the browser caches
the chunk across every note opened afterward), on the page that was already fetching the 79.5 kB
CodeMirror core and the 20.4 kB markdown grammar alongside it.
