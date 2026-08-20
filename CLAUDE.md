# CLAUDE.md: agent brief for `kaya`

## Build status

**V1, V2a and V2b are complete.** A pandan PAT creates, reads, edits and deletes notes over
`/api/v1/notes`, and **`kaya` drives all of it from a shell** — `note
{list,get,create,edit,move,delete}` and `config {set,show,path}` — in `human`, `json` or `toon`,
with `--fields a,b,c` selecting columns on a list, prose cut to `KAYA_MAX_TEXT_CHARS` (default 500)
unless `--full`, a list carrying `{"count": n}` over the rows it returned — a trailing `3 notes` for
a person, a `summary` key for everything else — and `help:` next-step templates under every `human`
render. **Bare `kaya` is content-first** (KAN-549): three banner lines and your five most recently
updated notes, exit `0`; with no token, exit `1` and the structured `no_credential` row.
`make up` runs the whole stack on
`:8000` from the image, and `make k3d` applies `deploy/k8s/` to a throwaway cluster and then makes
requests against it, because an `apply` that succeeds only proves the API server liked the YAML
(ADR 0010). Pushing a `v*` tag cuts a public GitHub Release carrying one asset,
`kaya-linux-x86_64` (KAN-545). **V3's skeleton is in too** (KAN-552): the SPA is a browsable
three-region app — a router over `/` and `/notes/:ref`, a typed API layer and a credential seam —
driven against a real stack with a real PAT, and still without an editor in it.

**There is no hosted kaya, so `make up` is the only origin that exists** (ADR 0010, and KAN-722 is
where that was **decided** rather than deferred: no deploy, and the honest README paragraph
instead). That matters less than it sounds for correctness work: `make up` already points
`KAYA_PANDAN_URL` at the **live** pandan, so a local stack plus a real PAT exercises the genuine
authentication path. All nine V2b verbs were driven that way on 2026-08-09 and every one works —
including ADR 0009's precondition surviving a real Postgres `timestamptz` round trip to the
microsecond, which no fixture could have proven. What is still unproven is only what needs a remote
origin, and **[ADR 0010 §Amendment (2026-08-20)](docs/adr/0010-no-hosted-deploy-until-the-homelab.md)
is the one place that list lives** — three items, with the argument for each; do not restate it here
or in the README, and do not rediscover it. If `5432` or `8000` are busy on your machine,
`KAYA_DB_PORT=5434 KAYA_APP_PORT=8010 make up`.

**The published binary is `v0.5.0` and `kaya-cli` is at `0.11.0`, so the download is a V2a
read-only client** — `note list` and `note get`, no `config`, no `--fields`, no bare `kaya`; its own
`--help` epilogue says so. Verified against the real asset on 2026-08-20 (KAN-722). Everything the
table below describes is on `main` and reaches an artifact at the next `v*` tag. Nothing on board 18
tracks that lag as of that date, which is a cadence question rather than a deploy one; what KAN-722
fixed is only that `README.md` no longer describes the checkout's CLI as though it were the file it
tells a reader to `curl`.

| Package | What's in it |
|---|---|
| `backend/` | The whole of V1: migration `0001`, `app/auth/` (principal resolver, `authorize_note`), `app/api/` (`/api/v1/notes` CRUD, the central ref resolver, ADR 0009's `409`), `app/spa.py`, `app/observability/`. Plus KAN-555's `app/api/meta.py`: `GET /api/v1/meta`, the **one unauthenticated route** under `/api/v1`, returning **one key** — `pandan_url` from `KAYA_PANDAN_URL`. Unauthenticated by necessity (its whole caller is a visitor with no token), and one key on purpose: `tests/unit/test_meta.py` fails on a second one, because a meta endpoint that accumulates keys is a config dump with a friendly name. Plus KAN-557's migration `0002`: `note.search_vector`, a `tsvector` `GENERATED ALWAYS AS (...) STORED` over `title` + `body` with weights `A`/`B`, and `ix_note_search_vector` over it in GIN. Declared in `app/models/note.py` as `Computed(..., persisted=True)` and `deferred`, and **absent from `NoteRead`** — see §"Rules the code already enforces". Plus KAN-558's query over it: `notes_matching` in `app/auth/authorization.py` — the only module `Note` may reach a `select()` from — which composes `websearch_to_tsquery` and `ts_rank DESC, id DESC` onto `notes_owned_by`'s `WHERE owner_id = :caller`, and `app/api/search.py`, which owns the one decision `?q=` needed: an absent `q` is not a search, a present-but-blank one is a `400 empty_search_query`. `GET /api/v1/notes?q=` returns the same `NoteList` and gains **no** `rank` key |
| `kaya-client/` | KAN-540: `KayaClient` over httpx and the `render()` seam as four composable steps. KAN-551: the full CRUD set (`create_note`, `update_note`, `move_note`, `delete_note`) — `move_note` *is* `update_note` because ADR 0008 makes a move a `PATCH` to one column, and every ref-taking method shares one `_note_path` that percent-encodes the ref as a single segment. ADR 0009's `if_updated_at` is forwarded as an **opaque string**, so nothing here can lose a microsecond. Same card: the config *file* tier (JSON at `$XDG_CONFIG_HOME/kaya/config.json`, consulted per key after the environment) and the three `config` verbs as `Payload` builders — `settings_payload()`, `path_payload()`, `write_settings()`, which read-modify-writes so a hand-set `max_text_chars` survives a `config set --api-url`. `human`/`json`/`toon` user-facing, `data` adapter-only. KAN-548: `aggregates.py` is live — a collection gets `{"count": len(records)}` and an entity gets nothing, rendered as a blank-line-separated `2 notes` footer under `human` and as a `summary` key beside the envelope everywhere else, both out of the one mapping via `summary_line()`. KAN-547: `truncation.py` is live — `text_limit` cuts the fields `Payload.prose_fields` names and appends a hint carrying the **true** total **in-band**, so the total reaches `json`/`toon`/`data`; `0` disables, and `config.max_text_chars()` resolves `KAYA_MAX_TEXT_CHARS` (default 500, a non-number is a `UsageError`). KAN-546: `projection.py` is live — `fields` narrows `records` *and* `columns` uniformly for every format, via `Payload.narrowed_to()`, with the vocabulary read from `field_names()` before anything narrows. KAN-550: `hints.py` — ADR 0005 §contract 8's `help[]` templates, keyed on `(kind, noun)` and never on a verb name, placeholders left unfilled, and **human-only** (the reverse of KAN-547's hint, because a template is advice about the tool and a total is a fact about the payload). KAN-549: `overview.py` — the three banner lines a bare `kaya` prints, which take three `str`s and **no `Payload`** so they cannot format a result — plus `RECENT_NOTES` (5), `KayaClient.recent_notes()` and `Payload.limited_to()`, the rows-wise twin of `narrowed_to`. KAN-541: `toon.py`, a stdlib-only **encode-only** TOON encoder registered in `Format`, `_SERIALIZERS` and `_ERROR_SERIALIZERS`, plus `config.py` (PLAN §Config's `KAYA_API_URL`/`KAYA_TOKEN` and `open_client()`) and `MissingCredential`. KAN-543: `provenance.version_line()` and the `_build_stamp.COMMIT` a release rewrites. KAN-542: the failure half of the layer — `error_payload()` / `render_error()`, and a `code` on every exception class so a raise site names a meaning. KAN-716: `DEFAULT_TIMEOUT` split by phase (`DEFAULT_CONNECT_TIMEOUT` 5 s, `DEFAULT_READ_TIMEOUT` 40 s) so the client outlasts the backend's authentication budget. KAN-566: `links()` and `backlinks()`, and the **pair is the clearest illustration in that file of what attaching schema knowledge at the call buys** — `links()` gets a new noun (`link`), a new envelope, its own five columns and an **empty** `prose_fields` (nothing in a link record is unbounded `TEXT`; a card title is a bounded column and cutting it is what KAN-547 already refuses to do to `note.title`), while `backlinks()` returns the **note** noun, the note columns and the note prose fields, because the API answers it with the very same `NoteList` a plain list does. So `backlinks` is `list_notes` at a different URL and its human render is byte-identical to one, asserted. `hints.py` gained **no row**: a `link` collection is silent, exactly as that module predicted by name, and `backlinks` gets the note templates because its rows genuinely are notes — the derivation working in both directions rather than an exception |
| `kaya-cli/` | The `kaya` console script, one entry point. KAN-541: `note list` and `note get <ref>` (`verbs.py`, a dispatch table), `--format {human,json,toon}` with `--json` as an alias and `--format` winning if both are given. KAN-551: the other seven verbs — four writes in `VERBS` and three `config` words in a second table, `LOCAL_VERBS`, because `config show` must answer with no credential at all. `parsing.resolve_body()` turns `--body`/`--body-file` into one string; there is **no `-`** for the standard input, so `tests/test_no_prompting.py` keeps proving ADR 0005 §contract 9 structurally. KAN-549: bare `kaya` is `verbs.BARE`, a row in the same dispatch table as every other verb, so `render` is still called in **exactly one place** in the package; the banner is `kaya_client.overview` joined on by `BLOCK_GAP`, and `executable_path()` — `argv[0]` resolved through `PATH`, or `sys.executable` when frozen — is this package's only new logic. KAN-547: `--full` on `output_flags()`, and `resolve_text_limit()` — a flag-beats-environment precedence and nothing else, since the number and the cut are both the client's. KAN-546: `--fields` on `output_flags()`, and `resolve_fields()` — one `split(",")`, which is the entire projection logic this package is allowed to contain. KAN-543: an argparse parser with `--version` and `--help` on it. KAN-542: that parser subclassed so it raises instead of exiting, plus `failures.py` (ADR 0005's exit table, and the only place a meaning becomes a number) and `parsing.py` (`usage:` on stderr *and* the structured row on stdout, from one event). KAN-724: `EXIT_CONFLICT = 6` and a `409` row in `EXIT_FOR_STATUS`, so ADR 0009's refusal stops reporting as a runtime failure — the whole card is that number and the ADR 0005 amendment arguing for it. KAN-566: `links` and `backlinks`, the first **top-level** verbs and therefore the first `VERBS` rows keyed on `(word, None)` — argparse's own value, since only the two groups declare a `subcommand` dest, so `verbs.run` dispatches them through the same lookup with no branch. `tests/test_verbs.py`'s `_parser_words` was widened from "two levels deep" to "a command with subparsers contributes its children, one without contributes itself", which is the drift guard covering the shape it was widened for rather than being told to ignore it; `kaya note links` is still a usage error and there is a test saying so |
| `mcp/` | KAN-569: a real server, not a skeleton — `src/kaya_mcp/server.py` registers ADR 0006's frozen six (`list_notes`, `get_note`, `create_note`, `edit_note`, `search_notes`, `get_backlinks`), each a thin call into `kaya-client`'s `render()`. KAN-964: **all six work.** `get_backlinks` had refused every call since KAN-569 — ADR 0006 froze the name before KAN-566 built the layers behind it — and once KAN-566 landed the route, `KayaClient.backlinks` and `kaya backlinks`, that refusal became a **false statement about the repository** rather than an honest gap, in the one canonical place `MCP ⊆ CLI` is stated. Three things it cost. `src/kaya_mcp/errors.py` is **deleted, not edited**: its single class existed for that one refusal, nothing else in the repository ever imported it, and this package now **invents no failure of its own** — every failure a tool can raise is a `kaya_client` one, which is what ADR 0004's arrow predicts of a thin adapter. `tests/test_get_backlinks.py`'s assertions **inverted rather than being deleted** ("refuses, and no request is made" → "returns the shaped payload, and the request went to `/backlinks`"), with the account in its docstring, the same convention `frontend/tests/shell.test.ts` set for KAN-553 — a suite that simply lost them would say nothing about the tool that used to be the one broken member of the six. And **the signature did not move**, which KAN-569 predicted in `server.py`'s docstring and which held with room to spare: the whole change is one function body in `tools.py`, and `fields`, truncation and the `{"count": n}` aggregate arrived with no line written for them anywhere in `mcp/`, because `KayaClient.backlinks` returns the note noun and the note columns — `/backlinks` answers with the very same `NoteList` a plain list does, so the tool is `list_notes` at a different URL. The `MCP ⊆ CLI` direction and the rest of the honest state live in [`mcp/README.md`](mcp/README.md) — the one canonical place for it, per ADR 0006 §4, and KAN-964 is what that canonicality is *for*: nothing else re-reads it, so a claim there has to be re-read when the thing it describes changes. KAN-570: ADR 0006 §2's freeze and §4 rule 2's direction are now **tests**, and both are test-only — `mcp/src/` is untouched, so `scripts/check-version-bump.sh` reports `mcp: changed, nothing behavioural`. `tests/test_frozen_tool_set.py` holds `FROZEN_TOOLS` and `FROZEN_TOOL_COUNT` as literals **separate from** `kaya_mcp.TOOL_NAMES` (a pin living in the module it pins is the module agreeing with itself) and the count **twice** — off `server.py`'s `@server.tool()` decorators in the AST, and off what `server.list_tools()` returns — because a registration that never becomes a listing counts in one and not the other, and `@server.tool(name=…)` counts in both while naming two different things. Its failure message is the deliverable ADR 0006 §2 asks for: why the pin exists, that adding a tool amends the ADR rather than appending a decorator, and the four-step check a **removal** passes first. `tests/test_cli_parity.py` is the direction, and the trap it exists to avoid is that **a parity test keyed on tool names is wrong on the sixth tool** — `search_notes`' CLI spelling is `kaya note list --q`, there is no `kaya search_notes`, and a derived check would pass five times and need a hand-written exception for the sixth, which is the parity test not holding. So the mapping is **data** (`CLI_EQUIVALENT`, argv rather than a verb word, so `--q` is *in* the row and deleting that flag reddens) and the mapping is what is guarded: the words are checked against `kaya-cli/src/kaya_cli/verbs.py`'s two dispatch tables and the flags against `__main__.py`'s parser construction, both read as **ASTs**. Not imported, because ADR 0004's arrow forbids one adapter depending on the other — the same technique and the same argument as `backend/tests/unit/test_client_deadline_outlasts_auth.py`. Two readers over two files, cross-checked against each other, which is what keeps a reader that goes blind from turning the guard green: a renamed CLI verb reddens `mcp/`'s suite, which is the assertion that makes this a parity check rather than a copy of one |
| `frontend/` | Svelte 5 + Vite + TS, the dev proxy for `/api`, and — KAN-552 — the **app skeleton** the rest of V3 is built inside. `App.svelte` is three layout regions plus the route and the two reads the regions need, and nothing else. `lib/router.ts` is ~40 hand-written lines over `pathname`/`pushState`/`popstate` for `/` and `/notes/:ref`, with `parseRoute` a pure function so it tests without a DOM; no router library, because CodeMirror is the **only** runtime dependency this project has ever taken and the bar for the second one is that high (KAN-553). `lib/api.ts`'s `apiRequest` is the one place a request happens and the only reader of the credential seam; it turns `{"error": {code, message}}` into a typed `ApiError` carrying `status` **and** `code` apart. `lib/notes.ts` is the five calls (`moveNote` delegates to `updateNote`, same as `kaya-client`), `lib/types.ts` mirrors `backend/app/api/schemas.py` with `updated_at` as an **opaque string**, and `lib/auth.ts` is **the** credential seam. KAN-553: `components/EditorPane.svelte` is **CodeMirror 6**, mounted once per note in the `$effect` KAN-552 rehearsed, with `lib/editor.ts` holding the two guards as pure predicates — `needsRemount` (the *identity* guard, in) and `needsDispatch`/`syncDocument` (the *echo* guard, back in) — plus `conflictVersions()`, where KAN-556 reads ADR 0009's two whole notes. It saves with `if_updated_at` and surfaces a `409` rather than swallowing it. Five MIT runtime dependencies (`@codemirror/state`, `view`, `commands`, `language`, `lang-markdown`) cost **+313,729 B raw / +100,506 B gzip -9** — measured, per ADR 0001 §2's obligation, with the table in `frontend/README.md`. KAN-767: those bytes are **their own chunk**, because one chunk meant KAN-555's landing page shipped an editor to a visitor who had not signed in yet. `lib/codemirror.ts` holds every runtime CodeMirror value — the extension set, the theme, `new EditorView` and `isolateHistory` — and `EditorPane.svelte` reaches it through one `import()`, so the **component** is still statically imported and both S9 guards parse and mount exactly what they always did. The entry chunk goes **381,926 -> 134,770 B raw / 125,862 -> 47,581 B gzip -9 (-62.2%)**, a landing page fetches **50,002 B gzip** against 128,283, and an editor page fetches **1,272 B gzip more** across three requests than it used to across two — the trade is stated rather than buried. KAN-836: the 20,585 B gzip of `@lezer/markdown` that was left in the entry — 43% of it — is lazy too, because `PreviewPane.svelte` now reaches `lib/markdown.ts` through one `import()`. The entry goes **135,663 -> 67,618 B raw / 47,883 -> 25,385 B gzip -9 (−47.0%)**, a landing page fetches **27,861 B gzip** against 50,351 (**−44.7%**, two requests either way), and a signed-in load fetches **+354 B gzip (+0.3%)** across five requests against three. Rollup put the grammar in a chunk **shared** by the editor's and the preview's rather than duplicating it — measured off the built assets, not reasoned about — and the preview's hazard is *not* the editor's: it builds nothing and tears nothing down, so what an `await` in its render effect would cost is the **subscription** (`source` read after an `await` is never a dependency, so the preview renders once and never moves again), which is why the same shape is used for a different reason. KAN-554: `components/Sidebar.svelte` is the **folder tree over `path`** plus the flat list, toggled — `lib/tree.ts` groups notes into `{roots, unpathed}` with no folder table and none possible (a folder exists because a note's path names it), and `path: ''` goes in the **named `unpathed` field rather than a folder called `''`**, so forgetting the two seeded notes that have one is a type error; `countNotes(buildTree(xs)) === xs.length` is the invariant, asserted over leading/trailing/doubled slashes, no slash, whitespace-only, a shared path and a file-and-folder name collision, and `tests/sidebar.test.ts` asserts the *rendered* twin because a value-level count stays green while a component renders half of it. `components/PreviewPane.svelte` is **live preview**, a *sibling* of the editor pane. `lib/markdown.ts` walks `@lezer/markdown`'s tree — **already in the bundle**, since `@codemirror/lang-markdown` builds `markdownLanguage` out of it, so the parser costs **zero new bytes** against `marked`+`DOMPurify` at 72,171 B raw / 24,069 gzip -9, which is a claim about its *marginal* cost and not about *when* the bytes arrive (KAN-836 is the second question and does not undo the first) — and builds **DOM nodes, never an HTML string**: one `createElement` call taking literal tag names, `createTextNode` for every byte of source, and the only source-derived attribute value a URL through an `http`/`https`/`mailto` allow-list on the **parsed** protocol. Raw HTML in a note is *visible text*, so nothing is lost and nothing is interpreted; `tests/no-html-injection.test.ts` asserts over parsed **ASTs** (svelte/compiler for templates, `typescript` for scripts, because a grep went red on four docstrings warning against `{@html}`) that no `{@html}` and no `innerHTML`-family write exists anywhere in `src/`. A refused link renders **the markdown that was typed**, marked `span.unlinked`, for the same reason raw HTML does — a relative path, a fragment and a protocol-relative `//evil.com` are all refused (there is no path→note resolver and ADR 0008 forbids building one; wikilinks are V5), and an earlier version dropped them to bare label text, which is the tree-losing-an-empty-path bug in another costume. The document reaches the preview through **`EditorPane`'s `ondocument` prop** into `App.svelte`'s `liveDocument` rune — a published seam, replacing the `EditorView.findFromDOM` reach the card shipped while KAN-556 held that file; V5's wikilink pills and backlinks panel read the same prop. Two facts keep that from re-running the editor's `$effect`: the live document is a rune of its **own** and is never written into `note`, and the callback is read through **`untrack`**, so a parent handing down a fresh closure per render cannot make the mount effect depend on its own output — `tests/document-seam.test.ts` asserts that over the parsed script, because an effect re-running harmlessly is invisible from the DOM. The preview toggle keeps `EditorPane` **outside** its `{#if}`, which is what stops a command about one pane discarding the other's unsaved work. KAN-556: `components/ConflictBanner.svelte` is ADR 0009's affordance — **keep mine / keep theirs / side by side**, a sibling of the editor container and never a child — over `lib/conflict.ts`, which holds `keepMinePatch()` (the resolution, and the **crossing**: body from `attempted`, precondition from `stored`), `splitOnChange()` (the shared head and tail trimmed off, so the marked middle provably contains every difference — a bound, not a diff) and `compareMetadata()` (fields the write did not send, named once as shared rather than as an empty two-column diff). KAN-555: `components/Landing.svelte` is the no-credential state and the **one-time PAT paste** — `lib/meta.ts` reads `GET /api/v1/meta` through `api.ts`'s new `publicRequest` (the one request that sends **no** `Authorization`, even when a token is in the tab) and `pandanHref()` refuses anything but `http(s)`; the link goes to pandan's **origin** with no path, because pandan's SPA keeps its Tokens tab in component state and gives it no URL to deep-link to. `App.svelte` owns the credential *lifecycle* (`authed` is a rune, so a paste reaches the list with no reload; a `401` calls `discard()`, which clears the token and returns to the landing state; a **Clear token** button in the header is the way out of a `503` or a wrong-account token). The input is `type="password"`, `autocomplete="off"`, `spellcheck="false"` and — the strongest guard, because it needs no handler to run — carries **no `name`**, so a form submission that escaped `preventDefault()` would serialize nothing; the form is `method="post"` for the same reason and the field is cleared on **every** path out of submit. `tests/landing.test.ts` sweeps four-character fragments over the **rendered DOM**, every `href` and every request URL, on all four states. Component tests get a DOM **per file** (`// @vitest-environment jsdom`) over Svelte's own `mount`/`unmount`/`flushSync` and no testing library, so `tests/dev-proxy.test.ts` keeps evaluating `vite.config.ts` in node. KAN-723: the hard-coded package table is **deleted, not corrected**. KAN-704: TypeScript is pinned to **`^6.0.3`**, and the ceiling is upstream rather than taste (Q43) |
| *root* | `Dockerfile` (bases pinned by digest), `docker-compose.yml`, `deploy/k8s/`. KAN-544: `scripts/check-version-bump.sh` (+ `lib/pyproject_diff.py`), `scripts/build-cli-artifact.sh`, `scripts/check-release-artifact.sh`, `.github/workflows/release.yml`'s `build` job. KAN-545: that workflow's `publish` job — the only `contents: write` in the repository, and it runs for a pushed `v*` tag and nothing else |

Now: **V3, the editor, is complete** — KAN-552 landed the skeleton, KAN-553 the editor, KAN-555 the
way in, KAN-556 the conflict banner, KAN-554 the sidebar and the preview, and KAN-767 the chunk
split, so `frontend/` is a browsable app with a router, a typed API layer, a credential seam, a real
landing page that takes a **one-time PAT paste** (and walks a `401` out rather than reloading
through it), a CodeMirror 6 pane that opens a note, edits it, saves it under ADR 0009's precondition
and offers **keep mine / keep theirs / side by side** when that precondition fails, a **folder tree
over the `path` column** beside the flat list, and a **live preview** that follows the document
without the editor's `$effect` re-running — all driven against a real stack and a real PAT. KAN-767
closed the slice by moving the editor's ~80 kB gzip onto **its own chunk**, so the visitor who has
not signed in yet no longer downloads one, and **KAN-836** did the same for the live preview's
`@lezer/markdown` grammar, which was 43% of what KAN-767 left in the entry: a landing page is now
**27,861 B gzip** against 50,351. **V4, search, is complete** (KAN-557, KAN-558, KAN-559):
`note.search_vector` is a stored generated `tsvector` over `title` + `body` with a GIN index, and
`GET /api/v1/notes?q=` is the query over it — owner-scoped in SQL, ranked by `ts_rank` with `id` as
the documented tie-break, and refusing a present-but-blank `q`. **KAN-559 closed the slice**: `--q`
on `note list` (`parsing.QUERY_FLAG`, on that verb alone rather than on `output_flags()`) and the
sidebar's search box, one flag and one input because the API returns the same `NoteList` a plain
list does. What is still open against V4 is KAN-962, a bug rather than a gap: a ranked result
rendered in the folder tree loses the ranking, and TREE is the default view. **`/links` and
`/backlinks` are in** (KAN-566): `GET /api/v1/notes/{ref}/links` is a note's outbound wikilinks,
each resolved as far as it can be — a `NOTE` edge through the `resolved_id` KAN-563 recorded, a
`KAN-`/`EPIC-` edge through KAN-564's resolver with the caller's own PAT — and `GET
/api/v1/notes/{ref}/backlinks` is every note whose body links to this one, which is a **join over
two of kaya's own tables and therefore answerable with pandan stopped**. `kaya links <ref>` and
`kaya backlinks <ref>` are the two verbs, and they are **top-level words rather than `note`
subcommands**, because SLICES §V5 spells them that way and because `backlinks` is the one verb whose
namespace is still open (the demo's `kaya backlinks KAN-501` is a `400 invalid_note_ref` today — the
note case is what shipped). `/backlinks` returns the same `NoteList` a plain list does, so
`--fields`, `--full`, the `{"count": n}` aggregate and the `help:` templates all arrived with
nothing written for them. **V6
is complete** (KAN-569, KAN-964, KAN-570): the MCP server is real, six tools registered against ADR
0006's frozen set, each calling the `render()` seam V2a and V2b built, **all six work**, and the
freeze and the `MCP ⊆ CLI` direction are both **tests** rather than inspection. KAN-964 closed the
last broken tool: `get_backlinks` had refused every call since KAN-569, which stopped being an honest
sequencing gap the moment KAN-566 landed the route, the client method and the two CLI verbs, and
became a false claim in the one canonical place `MCP ⊆ CLI` is stated. It was deliberately left for
its own card rather than folded into KAN-566 — and its own card is also what had to come **before
KAN-570**, since a parity test asserting every frozen tool name has a CLI verb would have gone green
over a tool that refused every call. KAN-570 then landed the pin and the parity test — see
[`mcp/README.md`](mcp/README.md) for the current, canonical statement of the direction and the three
files behind it. What is *not* automated, and is worth knowing before trusting any of it, is the
truth of that README's prose: nothing in `make check` reads it. KAN-570 closes one corner (names to
verbs) and ADR 0006 §4's "state it once and link" rule carries the rest. PLAN §Config's
**third** tier, the nearest `.mcp.json`, is deliberately not built and arrives once V6 closes: choosing
which server entry in an MCP host's file is kaya's is a guess until there is a server to name, and a
host launching one usually exports the `env` block anyway, so tier one covers the common case (see
`config.py`). Also unbuilt: `make test-e2e` is still a stub, and **it is no longer blocked on any
card** — KAN-552 moved its blocker off the shell and onto the behaviour SLICES §V3's demo describes,
and every one of those cards has now landed, so what the target waits on is somebody writing it.
ADR 0005 §Consequences defers ambient session context (pandan's V48) post-MVP.

**Trust the code over the docs.** When this file and the repository disagree, the repository is
right and this file is stale. Fix it in the same PR.

## What this project is

A cloud-hosted markdown notes app, API-first and agent-drivable, and the docs half of the `kayatoast`
suite. Its sibling is [pandan](https://github.com/leejianrong/pandan), the kanban board. Read
[`docs/PLAN.md`](docs/PLAN.md) before doing anything substantial; it is the live spec.

Work is tracked on **pandan board 18**, 7 epics matching the 7 slices in
[`docs/SLICES.md`](docs/SLICES.md). Use the `pandan` CLI to read and move cards.

## How the docs relate

A deliberate chain, not scratch notes. Treat it as the spec for intended behaviour:

[`docs/kaya-vision.md`](docs/kaya-vision.md) (settled intent) → [`docs/PLAN.md`](docs/PLAN.md) +
[`docs/adr/`](docs/adr/) → [`docs/SLICES.md`](docs/SLICES.md), with
[`docs/QUESTIONS.md`](docs/QUESTIONS.md) as the decision register.

- **`PLAN.md`** is one narrative document rather than the five pandan splits this across, so nothing
  can drift between them.
- **`QUESTIONS.md`** tells a **decision** from a **default**. A row marked `ASSUMED` was taken on
  the maintainer's behalf; correct it if it's wrong rather than treating it as settled.
- **`docs/adr/`** (0001–0010) is the *why*. Do not re-litigate an accepted ADR; amend it.
- **"pandan ADR NNNN"** always means an ADR in the pandan repo. Bare "ADR NNNN" means this repo's.

## The five decisions you will trip over if you don't know them

Each one is a place where the obvious implementation is wrong.

1. **Payload shaping lives in `kaya-client`, never in an adapter** ([ADR 0004](docs/adr/0004-shaping-lives-in-the-shared-client.md)).
   Projection, truncation, aggregates and serialization go through one `render()` seam. The CLI and
   the MCP server both call it. A projection rule appearing in `kaya-cli/` or `mcp/` is a bug, not a
   local optimisation. `kaya_cli.verbs` is what a verb is allowed to be — open a session, call one
   client method, return the `Payload` — and `__main__.main` calls `render()` on exactly one line.
   Pandan put shaping in its CLI, so its MCP adapter inherited none of it and one `list_cards` call
   costs 44,902 tokens against 2,689 for the equivalent CLI read.
2. **Kaya has no token format and no prefix logic** ([ADR 0002](docs/adr/0002-identity-pandan-as-provider.md)).
   Authentication forwards the bearer to pandan's `GET /api/v1/me` and caches the answer keyed on
   `sha256(token)`. Do not add a `startswith` guard: pandan still accepts pre-rebrand `kanban_pat_…`
   tokens, and that exact guard is the bug pandan ADR 0018 had to correct.
3. **The output layer's signature lands before behaviour goes inside it** ([ADR 0005](docs/adr/0005-born-agent-conformant.md)).
   V2a built the seam; V2b filled it, in six cards, and the signature never moved. If a change from
   here on needs to alter `render()`'s signature, stop. That is the signal the sequencing was
   violated, not a reason to push through — and it now has six precedents for finding the other
   answer, the most recent being KAN-549's "recent" slice, which became `Payload.limited_to()`
   applied at the *call* rather than a fifth parameter.
4. **Nothing in kaya may block on pandan** ([ADR 0003](docs/adr/0003-cross-linking-one-way-soft.md)).
   A note must save, render and appear in search with pandan completely down. Wikilink resolution is
   a cached read that degrades to an unresolved link. Authentication is the one exception ADR 0002
   accepts knowingly.
5. **A note's identity is its `NOTE-n` ref, never its path or title** ([ADR 0008](docs/adr/0008-note-identity.md)).
   `path` is mutable metadata; moving a note is a `PATCH` to one column with no link rewriting.

## Rules the code already enforces

These have tests. You will meet them as a failing build, so meet them here first.

**Every identifier goes through `backend/app/api/refs.py`.** `NOTE-12`, `note-12` and `12` resolve in
one place, so a missing note is the same `404` byte for byte whichever spelling asked for it, and
`#NOTE-12` is a `400`. A route never sees a string: it depends on `NoteFromRef` and is handed a
`Note`. Parsing an identifier inside a route is the bug ADR 0008 exists to prevent.

**A note list is scoped in SQL.** Compose onto `app.auth.notes_owned_by`, which already carries
`WHERE owner_id = :caller`. `tests/unit/test_no_unscoped_note_query.py` fails if `Note` reaches a
`select()` anywhere else under `app/`. A *single* note is fetched unscoped on purpose, because
`authorize_note` cannot answer `403` for someone else's note if the fetch never found it, which is
why `note_addressed_as_ref` and `note_addressed_as_id` also live in `app/auth/authorization.py`. Put
new queries in that module; never widen the allow-list.

**Postgres maintains `note.search_vector`, and nothing else may** (KAN-557, migration `0002`,
`app/models/note.py`). `GENERATED ALWAYS AS (setweight(to_tsvector('english', coalesce(title,'')),
'A') || setweight(to_tsvector('english', coalesce(body,'')), 'B')) STORED` — recomputed inside every
INSERT and every UPDATE touching a source column, so SLICES §V4's "no application-level reindex step"
is structural rather than remembered, and `app/api/notes.py` neither mentions the column nor can.
Four things about it the next person would otherwise get wrong. **The regconfig is a literal because
it has to be**: bare `to_tsvector(text)` is STABLE, not IMMUTABLE, and Postgres refuses it in a stored
generated column, so a per-note language is impossible *inside this mechanism* rather than merely
unbuilt. **The weights are in already, and that was KAN-558's decision to inherit rather than make**:
`ts_rank` reads them out of the stored vector, so weighting is a storage choice — KAN-558 owns only
the tie-break (`note.id`, since equal ranks must order deterministically). **`path` is deliberately
not in the vector**: ADR 0008 makes it mutable metadata, and matching a folder name would make it a
search key. And **`coalesce` is a no-op today, kept because `tsvector || NULL` is `NULL`** — a later
`DROP NOT NULL` on `body` would null the *whole* vector and the note would vanish from search, title
and all. The measured surprise: `Computed` does **not** make SQLAlchemy drop an explicit write.
Assigning the attribute on a persistent `Note` puts it in the UPDATE and Postgres answers
`psycopg.errors.GeneratedAlways`, which is the better outcome — there is no layer here where
maintaining the column by hand looks like it worked.

**`alembic revision --autogenerate` does not compare a generated column's expression, so the second
inherited trap only covers half of this one** (KAN-557,
`backend/tests/unit/test_search_vector_declaration.py`). Both halves were watched. Delete the
`search_vector` **column** from `app/models/note.py` and autogenerate emits `op.drop_index` +
`op.drop_column` — the trap works as written. Delete only the `Computed(...)`, leaving the column
declared, and autogenerate emits **`pass`**: Alembic diffs columns, types, nullability and indexes and
not the generation expression, so a model that has forgotten the column is generated is
indistinguishable from one that has not, and `test_autogenerate_would_not_drop_anything` stays green.
So does the whole integration suite, because the *database* is still right — and the database being
right is exactly the trap, since the model is what the application acts on. Without `Computed`
SQLAlchemy believes it may write the column, and the only thing left between that and a corrupt index
is Postgres refusing at runtime: a `500` on somebody's save instead of a red build. The guard is
therefore its own unit test, reading migration `0002`'s expression literal out of the file's **AST**
(a revision is a script with an identity, so it is never imported for a constant) and comparing it
with the model's, plus asserting the `Computed` construct exists, is `persisted`, and carries that
same string. Same technique as `test_client_deadline_outlasts_auth.py`: put the alarm where the
breaking change gets made.

**A generated revision is reflowed by `ruff format`, wired into `alembic.ini`'s
`[post_write_hooks]`, and it is `format` rather than `check --fix` for a measured reason** (KAN-692,
`backend/alembic.ini`, `backend/tests/unit/test_alembic_post_write_hooks.py`,
`backend/tests/integration/test_alembic_autogenerate.py`). KAN-665 made the *template* lint-clean;
autogenerate's renderer emits each `sa.Column(...)`, `sa.ForeignKeyConstraint(...)` and
`sa.UniqueConstraint(...)` on **one line**, which no template edit can reach — measured through the
real command, **nine E501s** in a revision nobody had typed a character into, which is why 0001's
and 0003's columns are hand-wrapped. Four things the next person would otherwise get wrong. **`ruff
check --fix` does not fix E501 and `ruff format` does**: E501 has no autofix, so `--fix` reports the
long line and rewrites nothing — the operation whose name contains "fix" is the wrong one. **One
hook, not two**: a `check --fix` pass beside it would silently sort or delete the imports
`script.py.mako` *guesses* at, and that template's comments say in as many words that ruff
*reporting* a wrong guess (I001/F401/F821) is the wanted outcome. **`type = module`, because ruff
ships no `console_scripts` entry point at all** — no `entry_points.txt` in its dist-info, the binary
is a script in the venv's `bin/` — so `console_scripts` cannot resolve it, and `module` runs
`sys.executable -m ruff`, which resolves in the interpreter alembic is already running under rather
than in whatever `PATH` holds (`exec`'s dependency). *That last one came out of a green mutation and
now has its own test*: swapping `module` for `exec` passed every other assertion, because the suite
runs under `uv run` and so happens to have the venv's `bin` on `PATH` — while `env
PATH=/usr/bin:/bin .venv/bin/alembic revision --autogenerate`, a perfectly normal invocation, dies
under `exec` with an uncaught `FileNotFoundError: 'ruff'` *after* the revision file is written.
`test_the_hook_does_not_depend_on_path` runs the configured hooks with `PATH` pointed at an empty
directory, which only an interpreter-resolved hook survives. And **alembic swallows a hook that
exits non-zero**: `write_hooks._run_hook` calls `subprocess.run` with no `check=`, so a wrong
sub-command or a bad flag prints ruff's complaint and generates the revision anyway,
indistinguishable from no hook at all. A missing *module* is the loud case (`CommandError`, before
any subprocess starts). That asymmetry is why the guard is behavioural rather than "assert the
section exists" — the fast one runs the hooks the real `alembic.ini` declares over a rendered wide
revision, the integration one drives `alembic revision --autogenerate` against a real Postgres in
**its own database** and asserts the un-hooked generation fails E501 *first*, because "clean with
the hook" is a green test about nothing unless the before is dirty. **The honest limit: no formatter
can break a long string literal.** `note.search_vector` renders as a 224-character
`sa.Computed("setweight(to_tsvector(…)) || …", persisted=True)` whose excess is one string; `ruff
format` reflows the call around it and E501 still names it, so that revision wants a hand wrap.
Pinned against a verbatim fixture, never against the live expression, so the guard's verdict is not
a function of how long somebody's SQL is. Two findings worth not rediscovering: KAN-665 predicted
that wiring this hook would empty `test_alembic_template.py`'s `== {"E501"}` boundary and that the
test should then be deleted — it **stayed green**, because `template_to_file` sits a layer below the
`ScriptDirectory` that runs hooks, so that test is now the hook's positive control rather than dead;
and the hook normalises the template's `repr()` single quotes to double, so the *shipped* revision
matches repo style even though `script.py.mako` deliberately still emits upstream's.

**`search_vector` must never reach the wire, and that guard is a unit test on purpose** (KAN-557,
`backend/tests/unit/test_note_payload_keys.py`). `NoteRead` is `from_attributes=True`, so a model
column not leaking is a property of pydantic's explicitness rather than of a decision anybody here
made — which is exactly the kind of thing that stops being true quietly. The payload's key list is
pinned, in order, and a second test serializes a `Note` that is *carrying* a vector so the pin cannot
pass for want of anything to leak. Three costs if it ever lands there: storage internals in a
published contract, in a shape (`'runbook':1A 'step':2B`) nothing outside Postgres can act on;
roughly the size of the note again on **every** read by **every** consumer, which is what ADR 0004's
projection and truncation exist to stop paying; and `--fields search_vector` becoming a thing a user
can type, because `kaya_client`'s `field_names()` builds its vocabulary from the keys the API
returned. A third test pins the *difference* between the table and the payload (`owner_id`,
`search_vector`), so the next column added to `note` has to be decided about rather than skipped. The
column is also `deferred` in the model, which is a second, independent reason it stays out: every
list read is `select(Note)`. KAN-558 is the card that names the column twice — in a `WHERE` and
inside `ts_rank` — and it stays unloaded through both: `tests/unit/test_note_search_query.py` asserts
over the **columns clause** rather than the SQL (the column is in the statement by construction), and
the integration twin asserts `inspect(note).unloaded` on a real row, because a `DISTINCT` or a union
added later *would* pull an order-by expression into the select list.

**A search result's order is `ts_rank DESC, note.id DESC`, and the tie-break is not optional**
(KAN-558, `app/auth/authorization.py`::`notes_matching`). Equal ranks are common rather than exotic:
on the live ten-note corpus `plainto_tsquery('english','reading list')` scores "A reading list" and
"Reading list" at **0.9910 each**, so a ten-note corpus ties on a two-word query and without a second
key Postgres may return those two in either order — exactly what SLICES §V4's "identical queries
return results in a deterministic order" forbids. `updated_at` **cannot serve**: `now()` is
transaction start time, so two notes written in one transaction share a stamp and the tie merely
moves. `id` is unique, immutable and never reused (ADR 0008). It lives in the same `order_by` as the
rank so relevance cannot be added without the tie-break travelling with it, and the fixture that
proves it (`tests/integration/test_note_search_api.py`::`a_genuine_rank_tie`) **asserts the two ranks
are equal before pinning the order** — a tie-break asserted against data that never ties is not
asserted. `DESC` rather than pandan's ascending `id`, because kaya's unfiltered list is `updated_at
DESC, id DESC`: matching a sibling's direction while breaking your own consistency is the worse trade.
The two orders **differ on purpose** and `app/api/notes.py` says so — relevance is the only useful
order for a search and a meaningless one for a list, and `KayaClient.list_notes`' docstring depends on
the other one.

**`websearch_to_tsquery`, because the input is a human's — and `?q=` present-but-blank is a `400`**
(KAN-558, `app/api/search.py`). Measured against Postgres 17 on that card: `to_tsquery('english',
'&|!()')` and `to_tsquery('english', 'foo &')` both **raise**, which reaches a caller as a `500`, so
the strict parser is unusable on a search box; `plainto_tsquery` never raises but cannot express a
quoted phrase or a `-exclusion`. `websearch_to_tsquery` raised on none of eleven hostile inputs, and
where it has nothing to work with it returns the *empty* tsquery — `anything @@ ''::tsquery` is false,
so a stopword-only or punctuation-only search is **zero notes**, not an error and not the whole
corpus. The term is a **bound parameter**, which is what makes `%` and `_` inert; if they ever behave
like wildcards the implementation has stopped being full-text search, and there is a test whose only
job is to say so. Separately: an absent `q` lists everything, a present `q` with no non-whitespace
character is a `400 empty_search_query`. Pandan makes that a no-op and is right to, because its `q`
arrived on a shipped endpoint with clients that always send it; kaya has no such client yet, and
`kaya note list --q "$TERM"` with `TERM` unset returning the whole corpus is a wrong answer that looks
like a right one. Plus KAN-566's `app/api/links.py`: `GET /api/v1/notes/{ref}/links` and
`/backlinks`, the **only routes under `app/api/` that take a bearer and an upstream client as well as
a session** — which is why they are a second route module rather than two more functions in
`notes.py`. The route body is three phases and the order is the contract: read the local rows, **let
go of the Postgres connection** (`_release_the_connection`, a `commit` on a read-only transaction),
then ask pandan. The resolution phase takes plain dataclasses and no session, so "it cannot reach the
database" is a fact about what is in scope rather than a rule; `notes_linking_to` and
`notes_named_by_id` are the two queries, in `app/auth/authorization.py`, because a backlinks query
names `Note`; and `app/integrations/dependencies.py` is the resolver's `Depends()` lifecycle plus
`caller_bearer`, which reuses `app/auth/dependencies.py`'s `bearer_scheme` so that module's "the only
place anything about the `Authorization` header is parsed" survives a second consumer ADR 0005's table maps `400` → exit `2` and `invalid_note_ref` is deliberately not
keyed on its code string, so the refusal inherits the number with nothing in `kaya-cli` changing. The
refusal is on the **input**, never on the parse: refusing an empty *tsquery* would make the status
code a function of the dictionary, so `the` would be a `400` under `english` and a hit under a
configuration with no stopword list.

**A backlink is found by `resolved_id`, never by the title — and that is the rename criterion, not
a preference** (KAN-566, `app/auth/authorization.py`::`notes_linking_to`). `note_link.target_ref`
holds the title **as it was typed** in the linking note's body; `resolved_id` holds the id KAN-563
recorded when the edge first found its target. Keyed on the string, `/backlinks` works right up until
somebody renames the target and then returns nothing — the exact failure Q19 recorded the id *for*,
arriving at the one layer that reads it back. An edge whose `resolved_id` is still `NULL` is
deliberately **not** a backlink to anything: it is a link to a *title*, and
`resolve_pending_note_links` is the thing that makes it a link to a note, on create and on rename. A
`Note.title` fallback for those rows would reintroduce the bug through the back door, firing for
exactly the rows the id exists to protect. Two tests, and the second is what makes the first
trustworthy: the rename test is green under an implementation keyed on *either* column, because before
a rename the two agree — so its **positive control** NULLs one `resolved_id` while leaving
`target_ref` matching the target's title exactly, and asserts the backlink is gone. The
`target_kind == 'NOTE'` filter beside it is unreachable today and load-bearing anyway: `resolved_id`
is not a `ForeignKey` precisely because which table it points at depends on that column, so without
the filter a KAN-kind row whose pandan card id happened to equal a note's id would surface as a
backlink from a note that never mentioned it. There is a test that manufactures exactly that row.

**`/links` may talk to pandan; it may not hold a database connection while doing it** (KAN-566,
`app/api/links.py`). This is the one route in kaya that reaches an upstream outside identity, and
ADR 0003 permits it because a failed resolution renders unresolved rather than failing the read —
`CardEpicResolver.resolve` never raises for a network reason, so there is **no `try`/`except` in that
file and there must not be one**. What ADR 0003 does not permit is the second-order failure: sync
handlers run in Starlette's 40-thread pool and the engine has SQLAlchemy's default pool (5 + 10
overflow), so about fifteen concurrent `/links` reads against a merely *slow* pandan would exhaust it
and the next note **save** would block on a connection — ADR 0003's own rule broken from inside kaya,
by a decoration, for a request that never touches the note being saved. So the route is three phases:
read the local rows, `_release_the_connection` (a `commit`, because `app/db.py` sets
`expire_on_commit=False` and `rollback`/`close` would both expire the objects and turn a later
attribute read into the checkout this exists to avoid), then resolve. The resolution phase takes
frozen dataclasses and **no session**, so "it cannot reach Postgres" is a property of what is in
scope. `tests/integration/test_note_links_api.py` asserts the engine's checked-out count is `0` at
the instant the upstream is called, with an open transaction in the same test as the positive control
so a metric that never moved could not satisfy both halves. Nothing resolved is written back:
KAN-564's cache is keyed on `(sha256(bearer), ticket_number)` because an answer about a ticket is only
true for the caller who asked, and a column on a shared table is that leak with a longer TTL.

**Never log a header, a request object, or anything built from a bearer** (Q41/Q42,
`app/observability/`). The access line carries `ACCESS_FIELDS` and nothing else, and redaction sits
at *serialization*, so any call site is covered whether its author knew the rule or not. ADR 0002
buys one property with everything it costs, that kaya holds no replayable credential, and a log line
is the cheapest way to give it away. The tests assert against every contiguous *fragment* of a fake
token, because a truncated token is still a token.

**The SPA fallback must never answer for `/api`.** History fallback is needed so `/notes/NOTE-12`
loads the app, and both obvious implementations (`StaticFiles(html=True)` at `/`, or a `404`
handler) swallow the API: `/api/v1/notes/NOTE-9999` comes back `200 text/html` and the byte-identical
`404` is gone. `app/spa.py` refuses a fixed list of reserved namespaces instead. Note that every
other API test passes with the fallback mounted wrong, because they stand the app up with no build
directory and therefore no fallback at all.

**Svelte owns the editor's container element and never its children** (PLAN §S9, ADR 0001 §2,
`frontend/src/components/EditorPane.svelte`). This is PLAN §Open risks' only frontend unknown with
teeth: bind a rune naively to the document while Svelte also emits DOM inside CM6's subtree and you
get an update loop that reads as a performance problem and is a correctness one. KAN-552 fixed the
shape before the editor existed, which is most of what made KAN-553 safe — one `div`, no `{#if}`,
no `{#each}`, no `{@html}` and no interpolation inside it, everything in there created imperatively.
`frontend/tests/editor-container.test.ts` parses the component and asserts the container has **zero**
template children; `tests/shell.test.ts` asserts over `childNodes` that every node in it was made by
the `$effect`. Even the "No note open." zero state is CM6's own `placeholder()` extension rather than a
Svelte node, which is why the container needs no children to say it. KAN-553 changed exactly one line
of the DOM guard, the selector, and inverted exactly one assertion: "the note body renders *outside*
the container" was true of a `<pre>` beside a placeholder and is precisely false of an editor holding
the document, so that test now says the body reached CM6's document and appears nowhere else. That
inversion is the card landing, and `shell.test.ts` records why — a pin quietly edited is a pin
destroyed.

**KAN-553's two guards are not interchangeable, and the teardown is not where KAN-552 rehearsed it.**
The **identity guard** (`needsRemount`) is on the way in: reading the `note` prop registers it, so a
parent handing down a new object per keystroke re-runs the effect *whichever field you read* —
`note.ref` and `note.body` are one signal — so "depend on identity" means **compare** the incoming ref
against the ref the view was built for, and a new document for the same note goes in as a
**transaction**. The **echo guard** (`needsDispatch`, applied by `syncDocument`) is on the way back in:
CM6's `updateListener` fires for every transaction including the ones our own code dispatched, so
`updateListener → set rune → effect → dispatch → updateListener` cycles unless the incoming string is
compared against `view.state.doc.toString()` first — un-guarded it is a `RangeError: Maximum call stack
size exceeded`, not a slow render. Both live in `frontend/src/lib/editor.ts` as **pure predicates**, so
they are tested in vitest's `node` environment where jsdom's missing measurement APIs cannot obscure
them, and again against a real `EditorView`. Beside them sits one piece of bookkeeping that is not a
guard: the incoming body is only offered to the echo guard when the *prop* moved, because a parent
re-rendering an unchanged note while you type produces a body that differs from the document and the
echo guard would let it through. And `view.destroy()` is **not** in that effect's cleanup: Svelte runs
a cleanup before every re-run, so it would destroy the view on exactly the content change the identity
guard exists to survive. The per-note destroy is in the effect body; the per-component destroy is a
second effect that reads nothing.

**KAN-767 made CodeMirror lazy and the mount effect is still synchronous, which is the whole of that
card's correctness** (`frontend/src/lib/codemirror.ts`, `tests/editor-lazy-mount.test.ts`). The library
is behind one `import()` so KAN-555's landing page does not ship an editor to a visitor with no
credential — and the obvious implementation of that, `await import()` at the top of the mount effect, is
wrong for exactly the reason the paragraph above gives one layer down. Awaiting means two runs of that
effect can be in flight at once, and Svelte runs a cleanup **before every re-run**: a cleanup firing
while run A is still awaiting sees `view === undefined` and destroys nothing, then A resolves and builds
into a container run B is also building into. Two views in one host, or an orphan whose `destroy()` is
never called, and both are invisible from a green suite. So the `import()` is in the **second** effect —
the one that reads nothing and therefore runs exactly once per component, and which already owned the
teardown, so its `live` flag and its `view.destroy()` are one lifetime in one closure. The mount effect
only **reads** the resulting rune, returning early while it is `null` exactly as it already did while
`host` was `undefined`, with all three dependencies read *above* the guard so the note stays
subscribed. Nothing races, so there is nothing to cancel — a generation counter here would be a
decoration. Two consequences: a lazy chunk can fail to arrive, so there is an `editor-unavailable`
notice **beside** S9's container (never in it), and **`mount()` + `flushSync()` no longer leaves an
editor in the container**, so every DOM test awaits `tests/editor-arrival.ts`'s `editorArrived(host)`
— which polls rather than counting microtask ticks, because the first `import()` in a worker really
loads the module while later ones resolve from the registry. **KAN-836 repeated all of this one layer
down for the preview's parser, and the hazard there is a different one** — see the paragraph after next.

**Nothing under `frontend/src/` may value-import `@codemirror/*` except `lib/codemirror.ts`, and
nothing may static-import that** (KAN-767, `frontend/tests/editor-chunk-is-lazy.test.ts`). This is a
**bundle** guard and it exists because its regression is silent in every other way: one
`import { EditorView } from '@codemirror/view'` at the top of any file re-merges the chunk, the app
works perfectly, every test stays green, and the only witness is `frontend/README.md`'s table, which
nobody re-measures on an unrelated card. Two rules rather than one, because they are two ways for the
same 80 kB gzip to come back — a static import of the lazy module keeps the first rule true while
undoing all of it. Over parsed **ASTs** and never a grep, the same lesson as
`tests/no-html-injection.test.ts`: there are six prose mentions of `@codemirror` in `src/` and every one
of them is a comment arguing about this. `import type` and `import { type X }` are allowed everywhere,
because `verbatimModuleSyntax` erases them and `lib/editor.ts` legitimately has two — which is what
keeps its guards loadable in vitest's `node` environment. KAN-836 added the twin,
`tests/preview-chunk-is-lazy.test.ts`, in the same shape and for the same silent regression, and moved
the AST scanner both files use into `tests/module-graph.ts` — two copies of it would be two instruments
that can drift apart while both look green — leaving each guard its own positive controls.

**KAN-836 made the preview's parser lazy too, and its hazard is not the editor's — that difference is
the whole of the design** (`frontend/src/components/PreviewPane.svelte`,
`tests/preview-lazy-render.test.ts`). `lib/markdown.ts` is behind one `import()` from
`PreviewPane.svelte`, because `@lezer/markdown` was **20,585 B gzip -9, 43% of what KAN-767 left in the
entry chunk**, and it is paid by a visitor with no credential and by a signed-in user on `/` — neither
of whom has a note open. The **rule** is KAN-767's, verbatim: the `import()` is in the effect that reads
nothing, so it runs once per component, and the render effect only *reads* the resulting rune with all
three of its dependencies read above the guard. The **reason** is not. `EditorPane` builds a stateful
object into a host and owns a teardown, so an `await` there risks two views in one container or an
orphan; `PreviewPane` builds nothing and tears nothing down, because `replaceChildren` is total and
idempotent. What an `await` costs *here* is the **subscription** — Svelte registers an effect's
dependencies during its synchronous pass only, so a `source` read after an `await` is not a dependency
at all and the preview renders the document it was mounted with and then never moves again, with no
error, no leak and nothing in the DOM to look at. Measured by building the naive version: two tests in
`tests/preview-lazy-render.test.ts` and six in `tests/preview.test.ts` go red, while the
in-flight-navigation test stays **green** for exactly the reason KAN-767 recorded about its own. Three
more facts. Rollup put the grammar in a chunk **shared** by the editor's chunk and the preview's rather
than duplicating it, which was read off the built assets (`grep -o 'from"\./[^"]*"' dist/assets/*.js`)
rather than reasoned about; the notice for a chunk that never arrives is a **sibling** of the
`.rendered` element, because the element whose children belong to `replaceChildren` cannot hold the
sentence explaining why `replaceChildren` never ran; and `lib/markdown.ts` had to stay **under `src/`**,
since `tests/no-html-injection.test.ts` and `tests/markdown.test.ts` both sweep that tree and a lazy
import that also moved the file would have narrowed the XSS guard's scope while staying green — there is
an assertion in the new guard whose only job is to say so. The trade, stated rather than buried: a
landing page fetches **50,351 -> 27,861 B gzip -9 (−44.7%)** across the same two requests, and a
signed-in load fetches **+354 B gzip (+0.3%)** across five requests against three, in parallel and off
the critical path (the 79,553 B editor chunk is still the slowest asset on that page).

**The conflict banner's resolution crosses the two versions, and "keep theirs" writes nothing**
(KAN-556, ADR 0009's clarification of the same date, `frontend/src/lib/conflict.ts`). `keepMinePatch()`
takes `body` from `attempted` and `if_updated_at` from **`stored`** — sending the attempted stamp back
would be refused identically, forever — and it is a pure function because it is the **second** place in
the SPA a precondition is built, so it needs its own microsecond assertion rather than leaning on the
save path's. "Keep theirs" makes **no request at all**: the stored version already is what the server
holds, so it is a client-side discard, and the discarded text's only copy is CM6's undo history. That
is why it goes in through `syncDocument` as a **transaction** carrying `isolateHistory.of('full')` —
without the isolation CM6 merges the discard into the typing group it interrupted and one undo throws
the user's own text away too, which is ADR 0009's silent-loss failure re-entering through the button
that promised to prevent it. Both resolutions stay guarded, so a third writer landing while the banner
is open produces a *second* `409`; the banner refreshes in place against the newer version and says it
moved **again** only when the two `stored` stamps actually differ, because a plain Save after a refusal
re-sends the same stale precondition and being refused identically is correct rather than news. The
side-by-side is a **bound, not a diff** (`splitOnChange`: the shared head and tail trimmed, the middle
marked), the two `<pre>`s are the bodies byte for byte because the three segments are slices, and the
fields the write did not send are named **once** as shared — `attempted_version` fills them from the
stored note, so identical on both sides is correct and a two-column rendering of it invites a choice
that does not exist.

**The SPA is a direct consumer of complete records, and it may not shape one** (ADR 0004 §Decision,
`frontend/src/lib/api.ts`'s header). The obvious reading — "the SPA is another adapter, so it goes
through `render()`" — is wrong twice over: `kaya-client` is Python, and ADR 0004 already exempted
this consumer in writing ("the API does not use `render` … a browser client that wants everything").
So no `--fields`-style projection, no truncation-with-a-hint and no `{"count": n}` in `frontend/`;
those are agent ergonomics, and a copy here is the second implementation ADR 0004 exists to prevent.
The line that is easy to blur, stated so KAN-554 does not have to guess: **rendering markdown to
HTML for preview is presentation, not payload shaping**, and belongs in the SPA. Shaping decides
which bytes a caller receives; presentation decides what a person sees of bytes they already hold.

**One module owns "the bearer for a request", and the browser never says more than `set`**
(KAN-552, ADR 0002, Q7/Q41/Q42, `frontend/src/lib/auth.ts`). Every fetch takes its `Authorization`
from `authorization()` there, so the day a cookie becomes possible it is one module and not every
call site. The token lives in **`sessionStorage`** — not `localStorage`, not in memory — and the
reasoning is specific: it is a *pandan* PAT, so exfiltration hands over the kanban board too, and
KAN-554's live preview will render user markdown to HTML in this same origin. `sessionStorage` dies
with the tab. There is deliberately no cookie scaffolding to grow into, because Q7 defers browser
SSO on a hard fact (`fly.dev` is on the Public Suffix List, so two `*.fly.dev` origins cannot share
a cookie at all). **The token never enters a URL, a log line, an error message, or the DOM**, and
the only thing allowed to describe it is `credentialState()`, which returns `set` or `not set` —
never a length, never a mask, since a mask is a fragment with asterisks in front of it. That is
`kaya config show`'s lesson ported to a browser, where a screenshot is one keystroke away;
`frontend/tests/auth.test.ts` sweeps every contiguous **four**-character fragment of a fake token,
and `tests/shell.test.ts` sweeps the rendered `document.body`.

**A `PATCH` is guarded only if it asks to be, and only over the body** (ADR 0009,
`app/api/concurrency.py`). Send `if_updated_at` and a stale value is a `409` carrying `attempted` and
`stored`, two whole notes, so a client can diff them. Omit it and the write is a plain overwrite *by
specification*. A write touching only `title` or `path` is unguarded even with a stale precondition;
one touching `body` as well is refused whole. The comparison is exact to the microsecond, so a token
that loses precision anywhere in the round trip refuses *every* correct write.

**The CLI's half of that is one flag, and there is no `--force`** (KAN-551). `kaya note edit <ref>
--if-updated-at <the updated_at you read>` is the guarded write; **omitting the flag is the plain
overwrite**, so the unguarded form is spelled by not typing something and a second flag meaning the
same thing never existed. The value is carried as an **opaque string** from argv to the JSON body —
nothing in `kaya-client` parses or reformats it — which is what makes "no microsecond is lost"
a property of the code rather than of a datetime format. The client also **never fetches the
precondition itself**: a read-before-write would look safer and would disable the guarantee, because
the token would then name a version read microseconds ago instead of the version the caller's edit
was based on, so the `409` would fire only on a race inside that window. `409` has no row in ADR
0005's exit table and takes the unmapped default, `1`; both whole notes reach stdout under
`--format json`.

**`kaya note move` is sugar and must stay sugar.** ADR 0008 says moving a note *is* a `PATCH` to
`path`, so `KayaClient.move_note` delegates to `update_note` rather than making its own call, and
`kaya-client/tests/test_writes.py` pins that `move` and `edit --path` put **identical bytes** on the
wire. The word earns its place because "move this note" is the sentence a person says; the
delegation is what stops the next person "backing it properly" with a `POST /notes/{ref}/move`. It
takes **no** `--if-updated-at`, because ADR 0009 guards only writes that touch `body`, so a
precondition on a path-only write is accepted and ignored — a flag that silently does nothing is
worse than one that does not exist.

**A config write is a read-modify-write, and `config show` prints `set` and never a fragment**
(KAN-551, `kaya-client/src/kaya_client/config.py`). PLAN §Config resolves each key independently,
environment then user config file, so a shell that exports only `KAYA_TOKEN` does not discard the
`api_url` in the file. `config set` has flags for `api_url` and `token` and **deliberately none for
`max_text_chars`** — which is exactly why the merge matters: a writer that serialized only its own
flags would delete a hand-tuned key silently, on a command about something else. The file is JSON
rather than pandan's TOML because `config set` has to round-trip keys it does not understand and
Python 3.12 can read TOML but not write it; a hand-rolled writer meeting a hand-written table is how
a `set` verb destroys the file. A malformed file is a **refusal**, before the write, so a syntax
error cannot cost you the only copy. And the token row says `set` or `not set` — not a prefix, not a
suffix, not a length. `pandan config show` prints `set (…c_DE)`, and those four characters are a
contiguous fragment of a live credential in a command documented as safe to paste; the tests check
every fragment of **four** characters or more, in every format. Four rather than
`test_log_redaction.py`'s eight because the shape being refused here is a specific one — a mutation
that leaked exactly pandan's four characters walked straight through a six-character window, which
is also why the redaction fixtures use a high-entropy fake token rather than a readable one (a fake
containing the word `token` collides with this payload's own key names).

**The browser has the same rule and two more surfaces, and the sweep runs over the rendered DOM**
(KAN-555, `frontend/tests/landing.test.ts`). `frontend/tests/auth.test.ts` sweeps the credential
*seam*, which stays green while a component renders the token into a `<p>` — the structural-guard
trap CLAUDE.md §Conventions warns about, met in the one place it costs a credential. So the paste
form's tests sweep `document.body.innerHTML`, every `href` in the page and every URL handed to
`fetch`, in all four states (landing, mid-paste, after submit, after a `401`). Mid-paste the token is
in the input's **value property**, which is unavoidable and is *not* in the serialized HTML, because
`bind:value` writes the property and never the attribute — and the serialized HTML is what a devtools
copy, a snapshot and a bug report all carry, so both halves are asserted. Three decisions on the
element itself: `type="password"`; **no `name`**, because an unnamed field is not serialized at all
and so a submission that escaped `preventDefault()` carries nothing (the only guard here that does
not depend on a handler running); and `method="post"` on the form, because a form with no method
submits as GET and puts the credential in the address bar, in history and in the backend's request
line. The field is cleared on **every** path out of submit, including the rejection path. Two
findings worth not rediscovering: HTML's value sanitization strips CR and LF from a single-line
input, so header injection is not reachable *through the field* and the seam's control-character
refusal is a backstop there rather than the guard; and the fake token's real `kanban_pat_` prefix
means the **word "kanban" is a four-character fragment**, so the landing copy says "the board" — a
collision is the sweep working, and narrowing the sweep to dodge it would be the wrong repair.
**A hand-run sweep with a live PAT will report hits and they are not leaks**: a real token is
prefixed `pandan_pat_` and the page has to say the word *pandan*, so `pand`/`anda`/`ndan` appear by
construction. Measured 2026-08-11 against the live credential: six hit ranges on the landing page and
six mid-paste, **all inside the 11-character published prefix**, and **zero** over the 43-character
secret portion, which is the slice worth sweeping by hand
(`PAT.slice(PAT.indexOf('_pat_') + 5)`).

**A visitor with no credential can be told exactly one thing** (KAN-555, `backend/app/api/meta.py`).
`GET /api/v1/meta` returns `{"pandan_url": …}` and is the only unauthenticated route under
`/api/v1` — necessarily, since its whole caller is a browser that has no token yet. The SPA cannot
read `KAYA_PANDAN_URL` any other way: a literal in the source breaks the self-hosted pandan ADR 0002
supports, and a build-time `VITE_PANDAN_URL` is the per-environment bundle `frontend/src/lib/api.ts`
refuses in prose and ADR 0001's one-artifact promise forbids. It returns **one key** and
`tests/unit/test_meta.py` fails on a second, because the next person always wants to add the version
or a build sha, and a public route that accumulates keys is a config dump nobody re-reads before
putting a secret in it. On the client side `publicRequest()` sends **no** `Authorization` header at
all rather than the one in the tab — the `401` recovery path reaches this route holding a credential
the API has just refused, and attaching it would be sending a live PAT the caller did not authorise.

**No verb prompts, and `note delete` takes no confirmation flag** (ADR 0005 §contract 9). Nothing in
`kaya-cli` reads the standard input at all — `tests/test_no_prompting.py` asserts that
*structurally*, over the package's AST, which is why `--body-file` has no `-`: the shell already
spells it `--body-file /dev/stdin`, and the stronger guard is worth more than the sugar. `delete`
has no `--yes` because the only available confirmation is a flag, a flag that must always be passed
is a prefix rather than a confirmation, and it would not catch the mistake it exists for (typing the
wrong ref). There is no glob and no bulk form; the card that adds one is the card that adds `--yes`.

**A build that can't identify itself says so; it never invents a sha** (ADR 0007,
`kaya_client/provenance.py`). `--version` prints `kaya X.Y.Z (a1b2c3d)` or
`kaya X.Y.Z (source checkout, not a released build)`, and there is no third form — a bare number is
the pandan bug this exists to avoid. The sha comes from `_build_stamp.COMMIT`, **always empty in the
repository** and rewritten by `scripts/stamp-build.sh` immediately before packaging; both ends
validate it, so an unexpanded `${GITHUB_SHA}`, a sentinel word or the null sha degrades to the
source-checkout wording rather than being printed as provenance. Stamp *after* the tests: a test
asserts the committed stamp is empty, because a committed sha makes every checkout claim to be a
release. `version_line()` lives in `kaya-client` and not in the CLI because V6's MCP server reports
provenance through the same function (ADR 0004) — and deliberately *not* through `render()`, whose
signature ADR 0005 freezes. `kaya_client.overview` (KAN-549) takes the same door for the same
reason: shaping lives in that package, and it does not all live in one function.

**Base images are pinned by digest, never by tag.** A tag is a mutable pointer, so provenance labels
on a floating base describe nothing (pandan's KAN-475). `scripts/check-image-pins.sh` runs in the
pre-push hook and in CI, and `scripts/image-build.sh` is the only build path that produces true
labels.

**The API error shape is `{"error": {"code", "message", …}}`**, flat and identical for every failure
including Starlette's own `404`/`405` and body validation. `error_body` is the single builder;
`detail` is FastAPI's word and never reaches the wire.

**One error shape reaches the adapters too, and the exit number is the only CLI-local part.**
`kaya_client.error_payload` is `error_body`'s mirror on the client side and `render_error()` is the
only thing that formats a failure — `error<TAB>code<TAB>message<TAB>arg` on **stdout**, four fields
always, or the same object under a structured format with `code`/`message`/`arg` always present. The
row goes to stdout so an agent never merges two streams; only argparse's human `usage:` text goes to
stderr, and `kaya_cli.parsing` intercepts `ArgumentParser.error()`/`exit()` so both are emitted from
one event and no `SystemExit` escapes `main()`. Exit codes live in `kaya_cli/failures.py` because an
MCP tool has no process to exit — `0` ok · `1` runtime · `2` usage · `3` 401 · `4` 403 · `5` 404 ·
`6` 409, **add-only** and pinned by literal-value tests. A raise site picks a class, and the class carries the
`code`; nobody writes a number. A refusal is keyed on its **status**, not on the API's code string,
because the backend's code vocabulary grows without the client's knowledge. **`2` means the
caller's input was rejected — by argparse *or* by the API**: KAN-718 added `400 → 2` to
`EXIT_FOR_STATUS` and widened ADR 0005 §contract 4's wording to match, because ADR 0008 makes
`#NOTE-12` a `400` by design and exit `1` reported the caller's own typo as kaya failing, which a
script branching on the number would retry forever. That was an *addition* — no shipped number
moved, and `invalid_note_ref` is deliberately **not** in `EXIT_FOR_CODE`, so the next `400` code
exits `2` without anybody remembering to add it. **`6` means the note moved under a guarded write**:
KAN-724 added `409 → 6`, the first number this repository chose rather than inherited, because ADR
0009 puts `attempted` and `stored` on that refusal as two whole notes so a caller can merge and
retry — and `1` makes that unreachable, since a script must read `1` as "kaya failed" and so either
re-sends the same stale precondition forever or abandons a conflict it was handed everything to
resolve. Not `2`: the precondition was correct when it was read, so sending the caller back to their
own command line is wrong in the other direction. `422` deliberately did **not** get a row — a body
the API validated and rejected has no action a number could name that its `code` does not name
better, which is the test `409` passes and `422` does not — and `note_conflict` is not in
`EXIT_FOR_CODE` for the same reason `invalid_note_ref` isn't. It is a seventh number and not the
thing ADR 0005 warned against, because that warning is about *reusing* a meaning that already had a
number; pandan returns `409`s too and maps them to its own unmapped `1`, so the divergence is real,
temporary and tracked as **pandan KAN-831**. Unknown statuses still default to `1`. The `arg`
slot is **the first scalar extra a refusal carries**, which is unambiguous only while it carries one;
`backend/tests/unit/test_error_extras_stay_addressable.py` is the alarm for that, because the client
may never import the backend and so cannot see a second one appear.

**`KayaClient` returns a `Payload`, never a response body, and `render()` refuses a raw `dict`.**
That is ADR 0004 at its sharpest point: the moment a dict crosses that boundary, whoever formats it
has to re-derive list-vs-entity, the field vocabulary and the prose allow-list, and the obvious
place to put that derivation is the adapter — which is pandan's 11.4×. The four steps are one module
each in ADR 0004's fixed order, and the order is **type-enforced**: `truncate` takes and returns a
`Payload`, `attach_summary` returns a `Shaped`, and `serialize` accepts only a `Shaped`, so ADR
0005's "the summary is structurally out of the truncator's reach" is a fact rather than a convention.
`tests/test_passthrough_is_a_no_op.py` used to pin that both shaping parameters did nothing; KAN-546
spent its `fields` half and KAN-547 its `text_limit` half, so the file is **gone** and its
assertions live in `tests/test_projection.py` and `tests/test_truncation.py`. The default human row
is pinned byte-for-byte in `tests/test_human_row_is_pinned.py`. **KAN-548 is the one card that has
reddened it on purpose** — contract 5 required a summary footer under every human collection, so
each collection literal gained `\n\n<count> <noun>` and *nothing else moved*: `SINGLE_NOTE`, the
`no notes` zero state, the columns, the widths and the no-trailing-whitespace rule are all
unchanged and still asserted. That file's docstring records what moved and why, because a pin
quietly edited is a pin destroyed. For every other slice the old rule stands: if it reddens while
`--fields` was omitted and the prose is under the limit, that is the guard working, not a stale
test to update. **A bare `kaya` prints through that same one call** (KAN-549): the banner beside it
is `kaya_client.overview`, which takes three `str`s and no `Payload` and therefore cannot format a
result, and `kaya-cli/tests/test_bare_invocation.py` counts `render`'s call sites over the package's
AST so "exactly one place in `kaya-cli`" stays a fact rather than a habit.

**`--fields` narrows the shaped dict *uniformly*, and that settled a contradiction rather than
inheriting one** (KAN-546, ADR 0005's amendment of the same date). ADR 0004 §Decision describes
projection as narrowing the payload — pandan's 44,902 tokens → 7,204 — while ADR 0005 §contract 2
described it as widening the human row and "not affecting structured output". One operation does
both, because the default row (`ref`/`title`/`path`) is narrower than the record: the same `fields`
adds a column to the table and removes keys from the JSON. What contract 2 protects is that
**omitting** `--fields` leaves a record complete enough to feed back to the API, and `fields=None`
returns the very same payload object, so that is true by identity. Do **not** make projection depend
on `fmt` — the CLI's `--fields` and MCP's `fields` are one parameter through one seam, and a
format-conditional projection puts a difference between the two adapters inside the step they share.
Measured on kaya's own corpus (40 notes, `o200k_base`,
`kaya-client/scripts/measure_toon_delta.py`): `--fields ref,title,path` is **−79.5%** against
complete records in JSON and **−81.3%** in `toon`; `--fields ref,title` is **−89.5%** / **−90.7%**.
The vocabulary comes from `Payload.field_names()` read *before* narrowing, an unknown name is a
`UsageError` naming it (exit `2`), and `--fields` on a `note get` is a `UsageError` too — never a
silent no-op. Duplicates collapse first-seen (a record is a dict); `fields=[]` is refused, because
"select nothing" and "do not project" are different requests; `prose_fields` survives narrowing
whole, because it describes the API's schema and not the caller's selection.

**Truncation is an allow-list, and the hint is in-band** (KAN-547, ADR 0005's amendment of the same
date). The list is `payload.prose_fields` — `NOTE_PROSE_FIELDS = {"body"}`, the one unbounded `TEXT`
column in migration `0001` — and never a length heuristic, because "any string over N" eventually
cuts a `next_cursor` and silently breaks pagination, or mangles a URL; `title` and `path` are
`String(255)`/`String(1024)` and pass through at any length. A cut value is the original's first
`text_limit` characters **verbatim**, then a blank line, then
`(truncated, 2847 chars total — use --full to see complete body)` carrying the length *before* the
cut. **The hint is part of the string**, so no key is added, removed or retyped and the total
reaches `json`/`toon`/`data`, where a consumer would otherwise have no way to know it was cut — that
placement is a decision with an argument, in `truncation.py`'s docstring and in the ADR, not an
implementation detail. `--full` is `text_limit=0` and there is deliberately **no `full=True`**: two
spellings of one state is how a config layer ends up disagreeing with a flag. Under the limit the
payload comes back as *the same object*, which is what makes the byte-identity pin structural. The
guarantee on multi-byte text is **code points, not grapheme clusters** — a ZWJ emoji or a combining
accent can be split and the tests say so, because closing that needs a UAX #29 table and
`kaya-client` has exactly one runtime dependency. Measured on kaya's own corpus (40 notes,
`o200k_base`): at a mean body of 1,351 chars the default 500 takes a `note list` **−41.7%** in JSON
and **−44.1%** in `toon`, and a `note get` **−49.7%**; at 3,495 chars it is **−72.8%** /
**−74.6%** / **−80.0%**. Honest counter-result: at a mean body of 266 chars *nothing* is over the
limit, and forcing it to 200 makes a `note list` **+1.0%** larger, because the hint costs about
twenty tokens. Truncation pays on documents, not on one-line notes.

**The aggregate is one key, and it describes the returned set because it cannot see anything else**
(KAN-548, ADR 0005's amendment of the same date). `attach_summary` takes **one** parameter — the
payload — so there is no corpus in scope and no total to pass in; "the returned set, not the whole
corpus" is a property of what is *reachable* rather than a rule somebody follows, and the mutation
that breaks it has to widen a signature first. The summary is `{"count": len(records)}` and nothing
more. Do not add a second key without an argument for it: a key here is paid on **every** list read
by every consumer, the opposite of a `--fields` narrowing the caller opts into, and a date range or
a path breakdown is derivable from records the caller already holds. Measured (40 notes,
`o200k_base`) against the same render with no summary attached: **+0.1%** on complete records,
**+2.4%** on `--fields ref` in JSON and **+3.9%** in `toon` — six tokens flat, so the percentage is
a statement about what it is added to. `summary_line()` renders the *mapping*, never a second count,
which is contract 5's "both from the same dict" made mechanical. A **single entity gets no summary
at all** (one note is not a returned set), an empty list keeps `no notes` as its human zero state
and gains no `0 notes` footer, and the structured formats still carry `{"count": 0}` there because a
missing key cannot be told apart from a kaya that predates the feature. The footer is separated by a
blank line so it reads as a block rather than as one more row to anything splitting on newlines.

**A `--format` value is a published contract; a registered serializer is not.** `Format` holds only
what a person may type (`CLI_FORMATS` is that as a tuple, for argparse `choices`); `AdapterFormat`
holds `data`, which exists for MCP's `structuredContent` and is reachable in code only.
`_SERIALIZERS` is the full registry behind both, and `UnknownFormat` lists the user-facing set only,
because a suggestion in an error message is a contract too and that message reaches a shell. Adding
a format to the registry must not advertise it — ADR 0005 adopts pandan's exit codes verbatim rather
than improving them for exactly this reason, and pandan spent a whole card (KAN-442) withdrawing a
`pdn` alias. **KAN-541 added `toon` to both**, plus `_ERROR_SERIALIZERS`, and the literal pin in
`test_the_published_cli_vocabulary_is_pinned` is what made that a conscious edit rather than a side
effect. The encoder (`toon.py`) is **encode-only**: nothing in the product reads TOON back, so the
round-trip contract is proven by a decoder that lives in `kaya-client/tests/toon_decode.py`. Do not
promote it out of `tests/`. Measured against compact JSON on 40 notes (`o200k_base`,
`kaya-client/scripts/measure_toon_delta.py`): `note list` **−11.3%**, `note get` **+1.4%** — it pays
for uniform rows and costs a little on a single object, which is the shape pandan's V47 found.

**A cold pandan used to `503` a valid PAT. KAN-666 split the deadline and coalesced the misses.**
KAN-539 measured (`make measure-auth`) a cache hit at 1.6 µs, a warm miss at 387 ms and a cold miss
at **21.8 s** — against what was then a single 10 s deadline, which is why a good credential failed.
There are now two, `KAYA_PANDAN_CONNECT_TIMEOUT_SECONDS` (5 s) and
`KAYA_PANDAN_READ_TIMEOUT_SECONDS` (30 s), built by `split_timeout` in `app/auth/upstream.py`. The
old single knob is **gone, not aliased**: one number conflated "pandan is down" with "pandan is
asleep", and that conflation *was* the bug. Do not reintroduce it, and do not simply raise it — a
genuine outage would then take 30 s to report.

`make measure-auth MEASURE_ARGS=--split-only` is the experiment that justifies the split. It times
one introspection at the socket and reports connect (DNS + TCP + TLS) apart from read (the wait for
the first response byte). Connect is **67–105 ms [n=8]** while read varies over 392–662 ms, and the
part of connect that actually touches fly — TCP + TLS, excluding local DNS — is **48.6–56.7 ms**, an
8 ms spread against the read's 270 ms. The `*.fly.dev` **wildcard** certificate arrives from fly's
shared edge two `fly.io` proxy hops in front of pandan, which no per-app machine could hold, so
pandan's machine is not a participant in the handshake and cannot make it slow.
**Honest limit: all eight KAN-666 samples came back warm**, because pandan would not stay idle long
enough, so the cold *connect* figure is inferred from that mechanism rather than measured. The split
is still safe, because it cannot be worse than the single deadline it replaces: a slow connect would
fail at 5 s where it used to fail at 10 s, and a fast one succeeds where it used to fail outright.
If you ever do catch pandan genuinely cold, take a `--split-only` sample and settle it.

**A long read budget is only affordable because of `app/auth/single_flight.py`.** Sync
`get_principal` runs in Starlette's 40-thread pool, so without coalescing, 40 concurrent requests on
one uncached PAT hold 40 workers for the whole read budget and note *saving* stalls behind an
upstream that saving never uses — ADR 0003's rule, broken from inside kaya. `SingleFlight` turns
those 40 misses into one upstream call and one held worker, and every waiter sees the leader's
*failure* rather than its `None`, so an outage stays Q9's `503` for all of them instead of a `401`
for 39. It dedupes **per token**: many *distinct* cold PATs at once would still hold a worker each,
accepted because kaya's shape is one agent with one PAT. No Postgres connection is held during
introspection; the session is lazy and the mirror write happens after the upstream returns.

**`kaya-client` has to outlast that budget, and a guard in `backend/` says so** (KAN-716). The
invariant: the client's read deadline exceeds *connect + read* plus a margin for the request kaya
was actually asked to serve — today `DEFAULT_READ_TIMEOUT` 40 s against 5 + 30 + 5. A client that
gives up first abandons a request the backend was about to answer and reports a `TransportError` on
a working credential, which is the paragraphs above one layer out; it is how KAN-540's correct 30 s
silently stopped being correct when KAN-666 raised the other side. The two numbers live in different
packages and ADR 0004's arrow means neither may import the other, so the alarm sits where the
breaking change gets made: `backend/tests/unit/test_client_deadline_outlasts_auth.py` reads the
client's constant out of its AST and compares it against the live `Settings` defaults — the same
cross-package technique as `test_error_extras_stay_addressable.py`. Raise
`KAYA_PANDAN_READ_TIMEOUT_SECONDS` and that test names the other number that has to move. The
client's deadline is **split by phase** for the same reason the backend's is: 40 s is what it will
wait for an *answer*, while an unreachable host is refused on a 5 s connect budget, so nothing
spends the long number discovering that nothing is listening.

## Commands

`make help` is the source of truth. Python packages use **`uv`** (3.12), the SPA uses **`npm`**
(Node 20.19+). Every target runs from the repo root.

```bash
make hooks             # install the pre-push gate; run this once after cloning
make install           # uv sync every Python package + npm ci
make dev               # db, then backend :8000 and SPA :5173 together
make up                # db + migrate + the app image, one origin on :8000
make k3d               # deploy/k8s to a local cluster, then prove the pod serves
make test              # the fast, no-infra layer (what pre-push runs)
make test-integration  # real Postgres via testcontainers (needs Docker)
make check             # docs-links + secret-scan + image-pins + lint + test
make audit             # npm audit + pip-audit over every lockfile (network; NOT in `check`)
make measure-auth      # re-measure introspection latency (Docker + a real PAT)
```

The `toon` delta is re-measurable the same way, and needs no credential:

```bash
cd kaya-client && uv run --with tiktoken python scripts/measure_toon_delta.py --markdown
```

`tiktoken` is supplied for the run only and must not become a dependency: `kaya-client` has exactly
one runtime dependency and the encoder is stdlib-only (SLICES §V2a).

So is the SPA bundle, and that is ADR 0001 §2's standing obligation rather than a one-off for
KAN-553 — re-measure whenever a CodeMirror package is added, and put the number in the PR:

```bash
cd frontend && npm run build
for f in dist/assets/*; do echo "$f $(stat -c%s "$f") $(gzip -9 -c "$f" | wc -c)"; done
```

`vite build` prints gzip at a lower level than `gzip -9`, so the two disagree by ~1.5%. Quote either
and say which. The current numbers and their breakdown are the table in `frontend/README.md`. Since
KAN-767 there are **two** JS chunks, so quote the entry chunk, the editor chunk **and** what each of the
two pages actually fetches — a change that shrinks the entry while making an editor page fetch more bytes
across more requests is not obviously a win, and the PR has to say which it is.

`make measure-auth` is a measurement rather than a gate, and the only target that reads a
credential: it takes the PAT from `KAYA_MEASURE_PAT` or `~/.config/pandan/config.toml`, never prints
it, and exits 0 having done nothing when there is none, so CI never needs a secret.
`make test-e2e` is still a stub, now blocked on KAN-553/556 rather than on the shell.

**The fastest loop for frontend work is the dev server against a stack you already have up.**
`vite.config.ts` exports both knobs for exactly this, so a worktree does not have to own :8000 or
:5173:

```bash
cd frontend && KAYA_BACKEND_ORIGIN=http://localhost:8010 KAYA_SPA_PORT=5180 npm run dev
```

The SPA needs a credential in `sessionStorage` under `kaya.token` (KAN-552; KAN-555 adds the paste
form). Set it from the browser console or from a driver, **never** from a shell command that echoes
it — it is a live pandan PAT.

To run the single-origin layout from a checkout without building the image:

```bash
cd frontend && npm run build
cd backend && KAYA_SPA_DIST=../frontend/dist uv run uvicorn app.main:app --port 8000
```

Leaving `KAYA_SPA_DIST` unset means the API serves alone, which is what `make dev` wants.

**`make k3d` names its kubectl context explicitly** (`kubectl --context k3d-kaya …`) and so should
anything else touching the cluster. The `k3d-<name>` context exists only while the cluster does, so
a target relying on "whatever is current" depends on state it did not establish, and the manifests
have to be appliable on the homelab by someone without this laptop's kubeconfig.

**Adding a package directory turns on its CI jobs**, gated on the directory existing rather than on
a changed-paths filter. A new package therefore needs, from its first commit: a committed `uv.lock`
(CI runs `uv sync --frozen`), ruff passing, and at least one real test, since `pytest` exits
non-zero on "no tests collected". The frontend equivalent is a committed `package-lock.json` and a
working `npm run build`.

## Two inherited traps, written down so they aren't rediscovered

Both cost the sibling project real time. Neither is hypothetical.

- **Keep every `import app.*` inside a test or fixture body in the integration layer, never at module
  top.** A top-level app import runs at pytest collection, before the database fixture sets
  `DATABASE_URL`, so the engines bind to the wrong database. It passes locally against a dev Postgres
  and fails in CI. This is pandan's "PR #17 trap".
- **Alembic autogenerate needs models imported in `env.py`**, or it will cheerfully generate a
  migration that drops your tables. It is also **narrower than it looks**: it diffs columns, types,
  nullability and indexes, and *not* a generated column's expression — see §"Rules the code already
  enforces" on `search_vector`, where a `Computed(...)` deleted from the model produced an
  autogenerate diff of `pass`. Do not treat "autogenerate is quiet" as "the model matches the
  database".

## Conventions

**Branching.** One branch per slice off fresh `main`. PR-only; `main` is protected and requires
branches to be up to date, so parallel PRs land one at a time (`gh pr update-branch` after each).

**Worktrees.** Use [treehouse](https://github.com/kunchenguid/treehouse) for parallel work
(`treehouse.toml` at the root): `treehouse get --lease` acquires a tree, `treehouse return <path>`
releases it. It recycles a bounded pool instead of leaving a full checkout behind per task. A fresh
tree needs `make install` before `make lint` or the pre-push gate will work. Hooks are shared with
the primary checkout, so `make hooks` there covers every tree. Only `make dev` and `make db` need a
per-tree database (`COMPOSE_PROJECT_NAME=kaya-x KAYA_DB_PORT=5433 make db`); the integration layer
provisions its own Postgres via testcontainers and is already isolated.

**Tests.** Layered by cost ([`docs/PLAN.md`](docs/PLAN.md) §Testing approach). A fast layer with no
infrastructure, a heavier layer on real Postgres, and e2e that boots the stack. A slow check never
gates a local push.

**Every bug and flake becomes a test**, written failing first. A fixed bug without a test is a bug
waiting to come back.

**Prove a guard by watching it fail.** For anything marked `[mutate]` in `SLICES.md`: break the
protected thing, confirm the failure names the right thing, then restore. Restore with
`git apply -R` or `git stash`, **never `git checkout -- <file>` or `git restore <file>`**, which
overwrite from the index and silently destroy uncommitted work no reflog can recover. Watch what the
mutation actually reaches: a guard that only fires through some *other* rule's success is not a guard
over the rule you meant to test.

**Commit the card's work *before* you mutate anything.** The obvious way to run the paragraph above
— edit the file, `git diff -- <file> > /tmp/mut.patch`, test, `git apply -R /tmp/mut.patch` — is
safe only against a **clean** tree. On a dirty one that `git diff` captures the whole slice as well
as the mutation, so reversing it deletes the card. KAN-549 lost its `__main__.py` that way and had
to rewrite it from context; the five cards before it were safe only because they happened to have
committed first. `git apply -R` is exactly as destructive as the `git restore` warned against above
when the patch is wider than you think. Commit first, then mutate, then reverse, then check
`git status --short` is clean before believing any of it.

**A structural guard does not cover a behavioural claim, even when it reads as though it does.**
`kaya-client/tests/test_aggregates.py` proves the summary cannot describe a corpus by proving
`attach_summary` takes one parameter, so no corpus can *enter* it — which stays green when a caller
hands that function a payload it sliced wrongly. KAN-549 needed its own end-to-end assertions on
both sides of the boundary for that. Before citing an existing guard as covering a new card, mutate
the new behaviour and watch that guard specifically: this is the rule above turned around, and it
catches the reviewer rather than the author.

**Versioning.** A behavioural change to a shipped package bumps its version in the same PR
([ADR 0007](docs/adr/0007-release-provenance-from-the-first-release.md)), enforced by
`scripts/check-version-bump.sh` in the pre-push hook and in CI's `version-bump` job — which runs on
**every** PR rather than only ones touching `kaya-cli`, because the guard's scope is all three
shipped packages. It diffs against the **merge-base with `main`**, never the remote tip: that is
pandan's open KAN-484, where a two-dot diff against a moved tip reports main's own commits as the
branch's, backwards, and reddens a docs-only PR.

It classifies a `pyproject.toml` change by **which table moved, not by the filename**
(`scripts/lib/pyproject_diff.py`), or every Dependabot PR into `kaya-client` / `kaya-cli` / `mcp`
becomes a red check someone hand-fixes. A `uv.lock`-only change is the dev environment and is not
behavioural; a `[project.dependencies]` change becomes `Requires-Dist` in the wheel and is; a `dev`
extra is the test toolchain and is not. `[build-system].requires` is not either — commit `84278e2`
is a merged Dependabot PR whose entire diff is that one line. The rule the table list encodes is
"could a consumer of the built wheel tell?", and an unrecognised key inside `[project]` fails closed.

**Cutting a release.** Land the version bump, then push the tag: `git tag v0.4.0 <merged-sha> &&
git push origin v0.4.0`, where the tag is exactly `v` + `kaya-cli`'s `[project].version`
(`.github/workflows/release.yml` fails the run if it isn't). That is the *whole* manual step. The
workflow builds, gates and publishes a public GitHub Release with `kaya-linux-x86_64` attached.

Three things about that file are decisions rather than layout. **`contents: write` lives on the
`publish` job, never on the workflow**, so the write token is out of scope while pytest and
PyInstaller run. **`publish` is gated on `github.event_name == 'push'` as well as on the tag
prefix**, because `workflow_dispatch` accepts a ref and `gh workflow run release.yml --ref v0.4.0`
would otherwise let a rehearsal cut a public release. A dispatch must stay a rehearsal — building
and gating without publishing is how the pipeline gets exercised, and is how KAN-544's gate was
proven in the first place. Never push a tag from a branch; a tag is how an unreviewed commit becomes
a public download.

And **`build` runs inside `quay.io/pypa/manylinux_2_28_x86_64` while `publish` does not** (KAN-719).
PyInstaller does not compile an interpreter, it copies the one uv resolved, so **the asset's glibc
floor is the floor of the `libpython` that got frozen**. On `ubuntu-latest` (now 24.04) uv picks the
runner's preinstalled CPython 3.12, whose `libpython3.12.so` requires `GLIBC_2.38` — that is v0.4.0,
which dies on Ubuntu 22.04, Debian 12, RHEL 9 and Amazon Linux 2023, most of the installed base.
Building in AlmaLinux 8 puts the floor at **`GLIBC_2.28`**: Ubuntu 20.04+, Debian 11+, RHEL 8+. Four
things follow that are easy to get wrong:

- **The container alone does not work.** In that image uv resolves `/opt/python/cp312-cp312`
  (`/usr/bin/python3` is a symlink into it) and it is built *static*, `Py_ENABLE_SHARED = 0`, which
  PyInstaller refuses. The job installs uv's managed CPython — python-build-standalone, shared
  libpython, nothing above `GLIBC_2.17` — and exports `UV_PYTHON_PREFERENCE=only-managed` through
  `$GITHUB_ENV` rather than a job-level `env:` so it reaches `uv sync` *and* the `uv run` inside
  `scripts/build-cli-artifact.sh`.
- **`scripts/check-freeze-interpreter.sh` guards the interpreter, before the freeze**, because that
  is the thing that decides the floor and because it fails in a second instead of after a build.
- **`strings dist/kaya | grep GLIBC_` is inert — do not add it back.** It is the obvious check and
  pandan ships it; measured here, it reports a maximum of `GLIBC_2.14` on the broken v0.4.0 asset
  and exactly the same on a good one, because PyInstaller ships a *prebuilt* bootloader whose
  symbols do not vary with the build host. A guard that cannot tell the defect from the fix is worse
  than no guard. The proof is that `scripts/check-release-artifact.sh` *runs* the binary and now
  runs it in a glibc-2.28 userland — the identity gate became the portability gate for free, which
  is the whole reason the container went on the job rather than into a new step.
- **Do not pin `runs-on: ubuntu-22.04` instead.** It buys a 2.35 floor rather than 2.28 and rots
  when GitHub retires the image, so it is a recurring decision instead of a fix.

**Dependencies.** Lockfiles committed, installs frozen, updates by **Dependabot** (not renovate;
`.github/dependabot.yml` says why), vulnerabilities by `make audit`. **Do not move the audit into the
pre-push hook or into `make check`.** `npm audit` exits non-zero on transitive dev advisories nobody
can fix, so gating on it teaches `--no-verify`. It runs weekly and reports into one issue that never
blocks a merge. Do not add a `docker` ecosystem to the bot either: base images are digest-pinned and
`check-image-pins.sh` would reject the tag a bot PR writes.

**The SPA's TypeScript ceiling is `^6.x`, and the thing holding it is upstream** (KAN-704, Q43).
TypeScript 7.0 is the Go-native compiler and ships **no programmatic API** — its `exports` map
resolves `"."` to `lib/version.cjs`, so `require('typescript')` returns a version and nothing else —
and kaya type-checks *through* two tools that embed the compiler. Both refuse 7 by name:
`svelte-check` throws from its own `bin/ts-version-check.js` and `typescript-eslint` throws citing
its issue 10940. So `npm run check` and `eslint .` are already the guard, which is why this has no
test of its own; a `typescript < 7` assertion would pin a version number where the real property is
"the type-checker runs", and it would be a thing to delete rather than a thing that helps.
Dependabot PR #20 (7.0.2) is **left open on purpose** — the card says it stays fresh, and it is
already red on `Frontend (lint + unit + build)`, so nothing can drift in on a green check. It
becomes mergeable when TS 7.1 ships the API *and* both tools widen their peer ranges. Do not reach
for the `--tsgo` dual-install escape hatch `svelte-check` suggests to force it early.

**There is a second, nearer wall at TS 6.1, and it is the same situation one minor earlier.** Every
`@typescript-eslint/*` package at 8.66.0 — `typescript-eslint`, `parser`, `eslint-plugin` and
`typescript-estree` — declares `typescript: >=4.8.4 <6.1.0`, which is *tighter* than
`svelte-check`'s `^5.0.0 || ^6.0.0`. `frontend/package.json` says `^6.0.3` and that caret is
deliberate, so **the lockfile is the only thing keeping CI on 6.0.3**; `npm ci` pins it and `npm
install` would not. When TypeScript 6.1 ships (it has not yet), Dependabot will open a PR that goes
red on `Frontend (lint + unit + build)` against that peer range until typescript-eslint cuts a
release. That is expected and already diagnosed — held, not declined, exactly like the 7.x row — so
it is not a new investigation. Do not force it with `--legacy-peer-deps`, and do not narrow the
caret to `~6.0.3` to hide the PR: the bot PR going red *is* the notification.

**Measurements go in the PR body.** Several slices need a number rather than an assertion:
introspection latency (V1), the `toon` delta (V2a), the CodeMirror bundle size (V3), the MCP
per-read payload cost (V6). "It's fast" is not an acceptance criterion; a number is.

**Docs.** Ban the phrase **"full parity"** from this repo. State the direction (`MCP ⊆ CLI`) and cite
the test that proves it — [`mcp/README.md`](mcp/README.md) is the one canonical place that does both
(ADR 0006 §4); link to it rather than restating it. Pandan's skill asserted full parity in bold while
contradicting itself forty lines below, and the false claim reached a roadmap card where it nearly
justified deleting a working surface.

## Board access

The `pandan` CLI drives board 18. **Never print or paste the PAT.** It lives in
`~/.config/pandan/config.toml` and `pandan` finds it on its own; `pandan config show` redacts it and
is safe to run.

```bash
pandan warmup                        # the API scales to zero; wake it first
pandan list --board 18 --column todo
pandan next --board 18               # highest-priority unblocked card
pandan get KAN-530
```
