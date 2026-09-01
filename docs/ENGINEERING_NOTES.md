# Engineering notes: the full account behind CLAUDE.md

`CLAUDE.md` states the current rules and hidden constraints in one or two lines each, on purpose —
it is loaded into every agent session, so it stays under the agent-brief skill's size ceiling. This
file is where the *why* lives in full: the slice-by-slice build history, the measured numbers, the
KAN-card provenance, and the mutation-testing stories that justify each rule. Nothing here is
authoritative over the code; if this file and the repository disagree, the repository is right.

Reading this file is optional for day-to-day work. Read it when you need to understand *why* a rule
in `CLAUDE.md` exists, when you're about to touch code a rule protects and want the full incident
history first, or when you're deciding whether a rule still applies.

## Part 1 — Build history, slice by slice

**V1, V2a and V2b (backend + CLI core) are complete.** A pandan PAT creates, reads, edits and
deletes notes over `/api/v1/notes`, and `kaya` drives all of it from a shell — `note
{list,get,create,edit,move,delete}` and `config {set,show,path}` — in `human`, `json` or `toon`,
with `--fields a,b,c` selecting columns on a list, prose cut to `KAYA_MAX_TEXT_CHARS` (default 500)
unless `--full`, a list carrying `{"count": n}` over the rows it returned — a trailing `3 notes` for
a person, a `summary` key for everything else — and `help:` next-step templates under every `human`
render. **Bare `kaya` is content-first** (KAN-549): three banner lines and your five most recently
updated notes, exit `0`; with no token, exit `1` and the structured `no_credential` row. `make up`
runs the whole stack on `:8000` from the image, and `make k3d` applies `deploy/k8s/` to a throwaway
cluster and then makes requests against it, because an `apply` that succeeds only proves the API
server liked the YAML (ADR 0010). Pushing a `v*` tag cuts a public GitHub Release carrying one asset,
`kaya-linux-x86_64` (KAN-545).

There is no hosted kaya, so `make up` is the only origin that exists (ADR 0010, and KAN-722 is where
that was decided rather than deferred: no deploy, and the honest README paragraph instead). That
matters less than it sounds for correctness work: `make up` already points `KAYA_PANDAN_URL` at the
live pandan, so a local stack plus a real PAT exercises the genuine authentication path. All nine V2b
verbs were driven that way on 2026-08-09 and every one works — including ADR 0009's precondition
surviving a real Postgres `timestamptz` round trip to the microsecond, which no fixture could have
proven. What is still unproven is only what needs a remote origin, and
[ADR 0010 §Amendment (2026-08-20)](adr/0010-no-hosted-deploy-until-the-homelab.md) is the one place
that list lives — three items, with the argument for each.

**Release lag, corrected 2026-09-01.** Earlier drafts of this project's docs claimed the published
binary was `v0.5.0` (read-only, V2a only). That was accurate on 2026-08-20 but is stale now: the
actual latest GitHub release is **v0.12.0** (2026-08-20, commit `8f0d0ff`), and by that tag the CLI
already has the full write verb set, `config`, `links`/`backlinks`, `--q`, `--fields`, `--full`, and
bare `kaya` — verified by reading `git show v0.12.0:kaya-cli/src/kaya_cli/__main__.py`'s `EPILOGUE`.
On `main` (unreleased), `kaya-cli` is at `0.13.0` (one behavioural bump ahead: KAN-839, a malformed
`--if-updated-at` now exits `2` instead of `1`), `kaya-client` is at `0.14.0`, `mcp` is at `0.4.0`.
Check `gh release list --repo leejianrong/kaya` and each package's `pyproject.toml` before trusting
any specific version number quoted anywhere else in the docs — including this file.

### Package map, in full

| Package | What's in it |
|---|---|
| `backend/` | The whole of V1: migration `0001`, `app/auth/` (principal resolver, `authorize_note`), `app/api/` (`/api/v1/notes` CRUD, the central ref resolver, ADR 0009's `409`), `app/spa.py`, `app/observability/`. Plus KAN-555's `app/api/meta.py`: `GET /api/v1/meta`, the one unauthenticated route under `/api/v1`, returning one key — `pandan_url` from `KAYA_PANDAN_URL`. Plus KAN-557's migration `0002`: `note.search_vector`, a `tsvector` `GENERATED ALWAYS AS (...) STORED` over `title` + `body` with weights `A`/`B`, and `ix_note_search_vector` over it in GIN. Declared in `app/models/note.py` as `Computed(..., persisted=True)` and `deferred`, and absent from `NoteRead`. Plus KAN-558's query over it: `notes_matching` in `app/auth/authorization.py` — the only module `Note` may reach a `select()` from — which composes `websearch_to_tsquery` and `ts_rank DESC, id DESC` onto `notes_owned_by`'s `WHERE owner_id = :caller`, and `app/api/search.py`, which owns the one decision `?q=` needed: an absent `q` is not a search, a present-but-blank one is a `400 empty_search_query`. `GET /api/v1/notes?q=` returns the same `NoteList` and gains no `rank` key |
| `kaya-client/` | KAN-540: `KayaClient` over httpx and the `render()` seam as four composable steps. KAN-551: the full CRUD set (`create_note`, `update_note`, `move_note`, `delete_note`) — `move_note` *is* `update_note` (ADR 0008), and every ref-taking method shares one `_note_path` that percent-encodes the ref as a single segment. ADR 0009's `if_updated_at` is forwarded as an opaque string. Same card: the config *file* tier (JSON at `$XDG_CONFIG_HOME/kaya/config.json`) and the three `config` verbs as `Payload` builders — `settings_payload()`, `path_payload()`, `write_settings()`, which read-modify-writes. KAN-548: `aggregates.py`. KAN-547: `truncation.py`. KAN-546: `projection.py`. KAN-550: `hints.py` — ADR 0005 §contract 8's `help[]` templates. KAN-549: `overview.py` — the three banner lines a bare `kaya` prints, plus `RECENT_NOTES` (5), `KayaClient.recent_notes()` and `Payload.limited_to()`. KAN-541: `toon.py`, plus `config.py` and `MissingCredential`. KAN-543: `provenance.version_line()`. KAN-542: `error_payload()` / `render_error()`. KAN-716: `DEFAULT_TIMEOUT` split by phase. KAN-566: `links()` and `backlinks()` — `links()` gets a new noun (`link`) and empty `prose_fields`; `backlinks()` returns the note noun/columns/prose fields because `/backlinks` answers with the same `NoteList` a plain list does, so `backlinks` is `list_notes` at a different URL |
| `kaya-cli/` | The `kaya` console script. KAN-541: `note list`/`note get <ref>`, `--format {human,json,toon}`. KAN-551: the other seven verbs (four writes in `VERBS`, three `config` words in `LOCAL_VERBS`). KAN-549: bare `kaya` as `verbs.BARE`. KAN-547/KAN-546: `--full`/`--fields` on `output_flags()`. KAN-543/KAN-542: the argparse parser, `failures.py`, `parsing.py`. KAN-724: `EXIT_CONFLICT = 6`. KAN-566: `links`/`backlinks`, the first top-level verbs |
| `mcp/` | KAN-569: a real server — `src/kaya_mcp/server.py` registers ADR 0006's frozen six, each a thin call into `kaya-client`'s `render()`. KAN-964: all six work (see "The last broken MCP tool" below). KAN-570: the freeze and the `MCP ⊆ CLI` direction are tests (`test_frozen_tool_set.py`, `test_cli_parity.py`). KAN-571: ADR 0006 §3's schema compaction (`src/kaya_mcp/schema.py`). KAN-574: the per-read payload measurement |
| `frontend/` | Svelte 5 + Vite + TS. KAN-552: the app skeleton (`App.svelte`, `lib/router.ts`, `lib/api.ts`, `lib/notes.ts`, `lib/types.ts`, `lib/auth.ts`). KAN-553: `components/EditorPane.svelte`, CodeMirror 6. KAN-767/KAN-836: lazy-loaded CodeMirror and markdown-preview chunks. KAN-554: `components/Sidebar.svelte`, the folder tree. KAN-962: search bypasses the tree. KAN-556: `components/ConflictBanner.svelte`. KAN-555: `components/Landing.svelte`, the PAT paste. KAN-568: `components/BacklinksPanel.svelte`. KAN-567: wikilink pills and `[[` autocomplete in the editor. KAN-723/KAN-704: the hard-coded package table deleted; TypeScript pinned to `^6.0.3` |
| *root* | `Dockerfile` (bases pinned by digest), `docker-compose.yml`, `deploy/k8s/`. KAN-544: `scripts/check-version-bump.sh`, `scripts/build-cli-artifact.sh`, `scripts/check-release-artifact.sh`, the release workflow's `build` job. KAN-545: the `publish` job |

### V3 — the editor (complete)

KAN-552 landed the skeleton, KAN-553 the editor, KAN-555 the way in, KAN-556 the conflict banner,
KAN-554 the sidebar and the preview, and KAN-767 the chunk split, so `frontend/` is a browsable app
with a router, a typed API layer, a credential seam, a real landing page that takes a one-time PAT
paste (and walks a `401` out rather than reloading through it), a CodeMirror 6 pane that opens a
note, edits it, saves it under ADR 0009's precondition and offers keep mine / keep theirs / side by
side when that precondition fails, a folder tree over the `path` column beside the flat list, and a
live preview that follows the document without the editor's `$effect` re-running.

KAN-767 closed the slice by moving the editor's ~80 kB gzip onto its own chunk (entry chunk
381,926 → 134,770 B raw / 125,862 → 47,581 B gzip -9, **−62.2%**), so a visitor with no credential no
longer downloads one. KAN-836 did the same for the live preview's `@lezer/markdown` grammar (43% of
what KAN-767 left in the entry): entry 135,663 → 67,618 B raw / 47,883 → 25,385 B gzip -9
(**−47.0%**), landing page **27,861 B gzip** against 50,351 (**−44.7%**), signed-in load **+354 B
gzip (+0.3%)** across five requests against three.

### V4 — full-text search (complete)

KAN-557, KAN-558, KAN-559: `note.search_vector` is a stored generated `tsvector` over `title` + `body`
with a GIN index, and `GET /api/v1/notes?q=` is the query over it — owner-scoped in SQL, ranked by
`ts_rank` with `id` as the documented tie-break, refusing a present-but-blank `q`. KAN-559 closed the
slice: `--q` on `note list` and the sidebar's search box. KAN-962 closed the slice's last open bug: a
ranked result rendered in the folder tree lost the ranking (TREE is the default view), so the
*default* rendering of a search discarded relevance. A search now renders as the flat,
relevance-ordered list whatever the toggle was set to, the toggle leaves the screen while one is
active, and one line says which ordering is on screen. What the slice's demo still describes and the
code does not do is *highlighting* the match in the browser.

### V5 — cross-linking (complete, including KAN-567)

KAN-566: `GET /api/v1/notes/{ref}/links` is a note's outbound wikilinks, each resolved as far as it
can be — a `NOTE` edge through the `resolved_id` KAN-563 recorded, a `KAN-`/`EPIC-` edge through
KAN-564's resolver with the caller's own PAT — and `GET /api/v1/notes/{ref}/backlinks` is every note
whose body links to this one, a join over two of kaya's own tables and therefore answerable with
pandan stopped. `kaya links <ref>` and `kaya backlinks <ref>` are top-level words, not `note`
subcommands (SLICES §V5). `/backlinks` returns the same `NoteList` a plain list does, so `--fields`,
`--full`, the `{"count": n}` aggregate and the `help:` templates all arrived free.

KAN-568 put the browser half in: the backlinks rail is `App.svelte`'s fourth region. Four notes
linking to a target by title kept every one of their backlinks across a rename of that target
(`resolved_id`, not the string), and with card resolution starved to a 1 ms connect and a 1 ms read,
`/backlinks` answered `200` in a median **8.5 ms** with every row present while `/links` degraded to
a present-but-unresolved KAN row — R5.1 measured at the layer a person looks at.

**KAN-567 (wikilink pills and `[[` autocomplete) landed the last card in the slice** — commit
`d23efa7`. Any earlier doc saying "what's left of V5 is KAN-567" is stale; V5 is fully closed.

### V6 — the MCP surface (complete)

KAN-569, KAN-964, KAN-570, KAN-571, KAN-574: the MCP server is real, six tools registered against
ADR 0006's frozen set, each calling the `render()` seam V2a and V2b built, all six work, the freeze
and the `MCP ⊆ CLI` direction are both tests rather than inspection, and the advertised schemas are
compacted.

**KAN-574** closed SLICES §V6 item 7, the per-read payload measurement — the number ADR 0006 §3 and
`mcp/README.md` both named as still owed, because the 84% those docs quoted was pandan's own,
inherited into kaya's ADR only as the argument for shipping `fields` on day one. Driven over a real
`kaya-mcp` stdio subprocess against an isolated stack and a real PAT, kaya's own `list_notes` call —
complete vs `fields=["ref","title","path"]` — goes **7,701 → 1,156 tokens (−85.0%, `o200k_base`)**;
`mcp/README.md` has the full tables, the corpus shape (40 notes, mean body 1,382 chars) and the
complementary `get_note` truncation figure (**−61.7%** at the default 500-character limit).

**The last broken MCP tool (KAN-964).** `get_backlinks` had refused every call since KAN-569 — ADR
0006 froze the name before KAN-566 built the layers behind it — and once KAN-566 landed the route,
that refusal became a false statement about the repository rather than an honest gap, in the one
canonical place `MCP ⊆ CLI` is stated. `src/kaya_mcp/errors.py` was deleted, not edited: its single
class existed for that one refusal, and this package now invents no failure of its own. The whole fix
was one function body in `tools.py` — `fields`, truncation and the `{"count": n}` aggregate arrived
free, because `KayaClient.backlinks` returns the note noun and the note columns.

**KAN-570** landed ADR 0006 §2's freeze and §4 rule 2's direction as tests: `test_frozen_tool_set.py`
holds `FROZEN_TOOLS`/`FROZEN_TOOL_COUNT` as literals separate from `kaya_mcp.TOOL_NAMES`, counted
twice (off `server.py`'s decorators via AST, and off `server.list_tools()`'s return). This had to
land *after* KAN-964: a parity test asserting every frozen tool name has a CLI verb would have gone
green over a tool that refused every call. `test_cli_parity.py`'s mapping is data
(`CLI_EQUIVALENT`), not a derived check — `search_notes`' CLI spelling is `kaya note list --q`, and a
derived check would pass five times and need a hand exception for the sixth.

**KAN-571** took ADR 0006 §3's schema compaction (`title` annotations stripped, `anyOf: [{T},{null}]`
collapsed), applied by `server.SchemaCompactingServer.list_tools`. Measured, `o200k_base`: input
schemas **428 → 265 tokens (−38.1%)**, the whole `tools/list` reply **948 → 785 (−17.2%)**. Compaction
is the small half by design — ADR 0006's Finding 1 is that the resident surface is a ~4%-of-window
line item beside a 22% one (the projection/truncation savings above).

**What's still deliberately unbuilt.** PLAN §Config's third tier, the nearest `.mcp.json`, is not
built and V6 closing is what settled that rather than what unblocked it: choosing which server entry
in an MCP host's file is kaya's is a guess, and a host launching one usually exports the `env` block
anyway. `make test-e2e` is a stub, no longer blocked on any card — every behaviour SLICES §V3's demo
describes has landed, so what the target waits on is somebody writing it.

## Part 2 — the rules, in full

Every rule in `CLAUDE.md`'s "Rules the code already enforces" section is condensed to one or two
lines there. This is the full account — the incident, the measurement, the mutation-testing story —
behind each one.

### Identifier resolution and note-list scoping

**Every identifier goes through `backend/app/api/refs.py`.** `NOTE-12`, `note-12` and `12` resolve in
one place, so a missing note is the same `404` byte for byte whichever spelling asked for it, and
`#NOTE-12` is a `400`. A route never sees a string: it depends on `NoteFromRef` and is handed a
`Note`. Parsing an identifier inside a route is the bug ADR 0008 exists to prevent.

**A note list is scoped in SQL, and since KAN-965 the guard says so about the module where the
queries live.** Compose onto `app.auth.notes_owned_by`, which already carries `WHERE owner_id =
:caller`. A single note is fetched unscoped on purpose, because `authorize_note` cannot answer `403`
for someone else's note if the fetch never found it, which is why `note_addressed_as_ref` and
`note_addressed_as_id` also live in `app/auth/authorization.py`.

`tests/unit/test_no_unscoped_note_query.py` is three rules. **Rule 1** (KAN-535): `Note` reaches a
`select()` in `app/auth/authorization.py` and nowhere else under `app/` — a guard about a query's
*place*, not its *scoping*. Measured twice (KAN-566, KAN-965): replacing `notes_owned_by(principal)`
with a bare `select(Note)` inside `notes_linking_to` left the whole file green under rule 1 alone.
**Rule 2** closes that against the statements rather than the source: every function in that module
returning a `Select` is discovered by its return annotation, called, and its `whereclause` read for
an `==` between `note.owner_id` and a bound value. `UNSCOPED_BY_DESIGN` is a two-entry allow-list
(ADR 0008's two spellings), each checked to *still* be unscoped. **Rule 2b**: every `select(… Note
…)` in the module must sit inside a function rule 2's sweep covers, or it's invisible to rule 2 and
exempt from rule 1 by address.

**Rule 3 guards `note_link`** (KAN-965; KAN-566 found the hole and declined to plug it by widening
the name list, because `note_link` has no owner column and a blunt ban reddens two correct queries).
`source_note_id` is that table's only path to an owner, so a `note_link` query that does not
constrain it has nothing that could scope it, whatever else it filters on. Rule 3 asserts that
necessary condition over the AST, with `update`/`delete`/`join` added to the builder list.

**Two behavioural tests KAN-965 added because a structural guard doesn't cover a behavioural claim:**
`test_the_backward_pass_never_crosses_an_owner_boundary_either` (Bob creating a note titled "Shared
Title" must not resolve Alice's pending link to it) and
`test_a_cross_owner_resolved_id_never_names_the_other_owners_note_in_links` (with `notes_named_by_id`
unscoped, `/links` hands back another owner's title).

### `search_vector` (KAN-557, KAN-558)

**Postgres maintains it, and nothing else may.** `GENERATED ALWAYS AS (setweight(to_tsvector('english',
coalesce(title,'')), 'A') || setweight(to_tsvector('english', coalesce(body,'')), 'B')) STORED` —
recomputed inside every INSERT/UPDATE touching a source column. Four things worth knowing: the
regconfig is a literal because bare `to_tsvector(text)` is STABLE, not IMMUTABLE, and Postgres refuses
it in a stored generated column; the weights are inherited rather than chosen (KAN-558 owns only the
`note.id` tie-break); `path` is deliberately excluded (ADR 0008: mutable metadata); `coalesce` is a
no-op today, kept because `tsvector || NULL` is `NULL`. Measured surprise: `Computed` does not stop
SQLAlchemy from writing the column — assigning it on a persistent `Note` puts it in the UPDATE and
Postgres answers `psycopg.errors.GeneratedAlways`.

**Alembic autogenerate doesn't compare a generated column's expression.** Deleting the column from
the model emits `op.drop_index`/`op.drop_column` (the trap works). Deleting only `Computed(...)`,
leaving the column declared, emits `pass` — the model believes it may write the column, and the only
thing between that and a corrupt index is Postgres refusing at runtime. The guard
(`test_search_vector_declaration.py`) reads migration `0002`'s expression literal out of its AST and
compares it against the model's.

**The generated-revision formatting hook** (KAN-692, `alembic.ini`'s `post_write_hooks`) is `format`,
not `check --fix`, because E501 has no autofix and autogenerate's renderer emits columns one line
each (measured: nine E501s in an untouched revision). One hook, not two, because a `check --fix`
alongside it would silently sort/delete the imports the template guesses at. `type = module` because
ruff ships no `console_scripts` entry point — `exec` would depend on `PATH`, which broke under a
green mutation (`env PATH=/usr/bin:/bin .venv/bin/alembic … ` died with `FileNotFoundError: 'ruff'`
under `exec`, survived under `module`). Alembic swallows a hook that exits non-zero (no `check=` on
the `subprocess.run`), so the guard is behavioural, not "assert the section exists."

**`search_vector` must never reach the wire** (`test_note_payload_keys.py`). `NoteRead` is
`from_attributes=True`, so not-leaking is a property of pydantic's explicitness. The payload's key
list is pinned in order, and a second test serializes a `Note` *carrying* a vector so the pin can't
pass for want of anything to leak. The column is also `deferred`, an independent reason it stays out.

**Search order is `ts_rank DESC, note.id DESC`** — the tie-break is not optional. On the live
ten-note corpus, `plainto_tsquery('english','reading list')` scores "A reading list" and "Reading
list" at 0.9910 each. `updated_at` can't serve as tie-break (`now()` is transaction start time, so
two notes written in one transaction share a stamp). `id` is unique, immutable, never reused.

**`websearch_to_tsquery`, because the input is a human's.** Measured against Postgres 17:
`to_tsquery('english', '&|!()')` and `'foo &'` both raise (→ `500`); `plainto_tsquery` never raises
but can't express a phrase or `-exclusion`. `websearch_to_tsquery` raised on none of eleven hostile
inputs. An absent `q` lists everything; a present `q` with no non-whitespace character is `400
empty_search_query` (pandan makes that a no-op and is right to for its own reasons — kaya has no
client yet that always sends `q`).

### `/links` and `/backlinks` (KAN-566)

**A backlink is found by `resolved_id`, never the title** — the rename criterion, not a preference.
`note_link.target_ref` holds the title as typed; `resolved_id` holds the id KAN-563 recorded when the
edge first found its target. Keyed on the string, `/backlinks` works until a rename, then returns
nothing — the failure Q19 recorded the id for. The rename test's positive control NULLs one
`resolved_id` while leaving `target_ref` matching the target's title exactly, and asserts the
backlink is gone.

**`/links` may talk to pandan; it may not hold a database connection while doing it.** Sync handlers
run in Starlette's 40-thread pool and the engine has SQLAlchemy's default pool (5 + 10 overflow), so
~15 concurrent `/links` reads against a slow pandan would exhaust it and the next note *save* would
block on a connection — ADR 0003's rule broken from inside kaya. The route is three phases: read the
local rows, `_release_the_connection` (a `commit`, since `expire_on_commit=False`), then resolve with
frozen dataclasses and no session. `test_note_links_api.py` asserts the engine's checked-out count is
`0` at the instant the upstream is called.

### Frontend rules (V3, in full)

**Svelte owns the editor's container element and never its children** (PLAN §S9, ADR 0001 §2,
`EditorPane.svelte`). KAN-552 fixed the shape before the editor existed: one `div`, no `{#if}`, no
`{#each}`, no `{@html}`, no interpolation, everything created imperatively. `editor-container.test.ts`
parses the component and asserts zero template children.

**KAN-553's two guards are not interchangeable.** The identity guard (`needsRemount`) compares the
incoming ref against the ref the view was built for. The echo guard (`needsDispatch`/`syncDocument`)
compares the incoming string against `view.state.doc.toString()` before dispatching, because CM6's
`updateListener` fires for transactions the component's own code dispatched too — unguarded, that's a
`RangeError: Maximum call stack size exceeded`. `view.destroy()` is not in the mount effect's cleanup
(Svelte cleans up before every re-run, which would destroy the view on exactly the content change the
identity guard exists to survive); it's in a second effect that reads nothing.

**KAN-767: CodeMirror is lazy, and the mount effect stays synchronous.** The obvious
`await import()` at the top of the mount effect is wrong: two runs could overlap, and Svelte's
pre-re-run cleanup would see `view === undefined` mid-await and destroy nothing, leaving two views in
one host or an orphan. The `import()` lives in the *second* effect (reads nothing, runs once), which
already owns the teardown. Bundle result: entry **381,926 → 134,770 B raw / 125,862 → 47,581 B gzip -9
(−62.2%)**.

**KAN-967: the arrival poll had its own hidden 1000ms deadline** (`vi.waitFor`'s default, unrelated
to any configured test timeout). Reproduced directly under three concurrent `npm test` runs on 16
cores. Fixed by passing `{ timeout: 20_000 }` to `editorArrived`/`previewRendered` — chosen to be a
no-op against the suite's real 5000ms per-test timeout, which is now the only deadline that actually
fires.

**The bundle-boundary guard** (`editor-chunk-is-lazy.test.ts`, `preview-chunk-is-lazy.test.ts`, both
using `tests/module-graph.ts`'s AST scanner): nothing under `frontend/src/` may value-import
`@codemirror/*` except `lib/codemirror.ts`, and nothing may static-import that file. A single stray
`import { EditorView } from '@codemirror/view'` re-merges the chunk silently — the app works, every
other test stays green, and only a bundle-size table nobody re-measures would catch it.

**KAN-836: the preview's parser is lazy too, for a different reason than the editor's.**
`EditorPane` builds a stateful object and owns a teardown, so an `await` there risks two views or an
orphan. `PreviewPane` builds nothing and tears nothing down (`replaceChildren` is total and
idempotent) — what an `await` costs there is the *subscription*: Svelte registers effect
dependencies during the synchronous pass only, so a `source` read after an `await` isn't a dependency
at all, and the preview would render once and never move again, silently. Measured: landing page
**50,351 → 27,861 B gzip -9 (−44.7%)**.

**KAN-568's two properties invisible to `flushSync`, both found by a green mutation.** Rendering the
backlinks rail's subject off the `note` prop instead of the `subject` rune passed all thirty
behavioural assertions and was still wrong (`note` moves one render earlier than `subject` in a real
browser, though never under `flushSync`, which runs effects and DOM update in one pass). Dropping the
`untrack` around the effect's rune read has the same shape. Both are asserted over the *parsed
script* in `document-seam.test.ts`. The abort for the panel's fetch is deliberately *not* in the
guarded effect's cleanup — that would kill a live request on the re-run the guard exists to make a
no-op — it's in `load()` beside the request it replaces.

**KAN-556's conflict banner crosses the two versions.** `keepMinePatch()` takes `body` from
`attempted` and `if_updated_at` from `stored` (sending the attempted stamp back would be refused
forever). "Keep theirs" makes no request — it's a client-side discard via `syncDocument` carrying
`isolateHistory.of('full')`, because without isolation CM6 merges the discard into the interrupted
typing group and one undo throws the user's own text away too.

**KAN-962: search is never rendered by the folder tree.** The tree groups by `path`, so it cannot
carry `ts_rank DESC, note.id DESC` — folders sort before leaves and unpathed notes sit below the
whole tree, destroying whatever order the server chose. Driven in a browser: the API returned
`NOTE-2, NOTE-1, NOTE-3` (a genuine tie at 0.9910322) and the tree rendered `NOTE-3, NOTE-1, NOTE-2`.
The chosen view is its own rune a search never writes; the toggle is hidden (not disabled) while a
search is active, because a greyed-out but still-highlighted `Tree` makes the same false claim as a
working one.

**One module owns "the bearer for a request"** (`lib/auth.ts`). The token lives in
`sessionStorage` — not `localStorage`, not in memory — because it's a pandan PAT (exfiltration hands
over the board too) and the live preview renders user markdown to HTML in the same origin.
`sessionStorage` dies with the tab. No cookie scaffolding, because `fly.dev` is on the Public Suffix
List so two `*.fly.dev` origins can't share a cookie anyway (Q7). `credentialState()` returns `set`
or `not set` — never a length or a mask.

**The landing page's credential sweep** (KAN-555, `landing.test.ts`) runs over the *rendered* DOM —
`innerHTML`, every `href`, every fetch URL — in all four states, because `auth.test.ts` sweeping only
the seam would stay green while a component rendered the token into a `<p>`. Three element-level
decisions: `type="password"`; no `name` (an unnamed field serializes nothing even if
`preventDefault()` is skipped); `method="post"` (a GET form puts the credential in the address bar
and history). A hand-run sweep with a *live* PAT will report hits inside the 11-character published
`pandan_pat_` prefix — that's the sweep working, not a leak; zero hits over the 43-character secret
portion is the thing that matters (measured 2026-08-11).

### CLI, client, and release rules

**A `PATCH` is guarded only if it asks to be, and only over the body** (ADR 0009). Send
`if_updated_at` and a stale value is `409` carrying `attempted` and `stored`, two whole notes. A
write touching only `title`/`path` is unguarded even with a stale precondition; one touching `body`
is refused whole, to the microsecond. The CLI's `--if-updated-at` is the only guard flag and there is
no `--force` — the client never fetches the precondition itself, because a read-before-write would
narrow the guarantee to a race inside that read window rather than the caller's actual edit basis.

**`kaya note move` is sugar and must stay sugar** — `KayaClient.move_note` delegates to
`update_note` (ADR 0008), and `test_writes.py` pins that `move` and `edit --path` put identical bytes
on the wire. Takes no `--if-updated-at` (ADR 0009 guards body-touching writes only).

**A config write is a read-modify-write** (`kaya_client/config.py`). `config set` has flags for
`api_url`/`token` and deliberately none for `max_text_chars`, so a naive writer serializing only its
own flags would silently delete a hand-tuned key. JSON, not TOML, because Python 3.12 reads TOML but
can't write it, and `config set` has to round-trip keys it doesn't understand. A malformed file is a
refusal *before* the write. `config show` prints `set`/`not set`, never a length or fragment — the
tests check every fragment of *four* characters or more (narrower than `test_log_redaction.py`'s
eight, because a real mutation once leaked exactly pandan's four-character fragment through a
six-character window).

**No verb prompts, and `note delete` takes no confirmation flag** (ADR 0005 §contract 9).
`test_no_prompting.py` asserts this structurally over the package's AST. `delete` has no `--yes`
because a flag that must always be passed is a prefix, not a confirmation, and wouldn't catch the
mistake it exists for (the wrong ref).

**A build that can't identify itself says so; it never invents a sha** (ADR 0007). `--version` prints
`kaya X.Y.Z (sha)` or `kaya X.Y.Z (source checkout, not a released build)` — no third form. The sha
comes from `_build_stamp.COMMIT`, always empty in the repo, rewritten by `scripts/stamp-build.sh`
immediately before packaging.

**The API error shape is `{"error": {"code", "message", …}}`**, identical for every failure including
Starlette's own `404`/`405`. The client mirrors it: `render_error()` emits
`error<TAB>code<TAB>message<TAB>arg` on stdout (never stderr, so an agent never merges streams), or
the structured object. Exit codes (`kaya_cli/failures.py`): `0` ok · `1` runtime · `2` usage · `3`
401 · `4` 403 · `5` 404 · `6` 409 — add-only, pinned by literal-value tests. `2` also covers a `400`
(KAN-718) and a `422` (KAN-839, since the only `422` origin — `RequestValidationError` on `NoteCreate`/
`NoteUpdate` — is the same *kind* of event as `400`, unretryable without changing what was sent). `6`
is a number this repo chose (KAN-724) rather than inherited, because ADR 0009 hands the caller
everything needed to merge and retry a `409`, and `1` would make that unreachable.

**`KayaClient` returns a `Payload`, never a raw dict** — the four `render()` steps
(`truncate`/`attach_summary`/project/`serialize`) are type-enforced in ADR 0004's fixed order, so the
moment a dict crosses the client→adapter boundary, whoever formats it has to re-derive
list-vs-entity, the field vocabulary and the prose allow-list. That's pandan's 11.4× (44,902 tokens
vs 2,689 for the same read).

**`--fields` narrows uniformly** (KAN-546) — settles a contradiction between ADR 0004 (projection
narrows) and ADR 0005 (projection widens the human row): one operation does both, because the default
row is narrower than the full record. Measured (`o200k_base`, 40-note corpus): `--fields
ref,title,path` is **−79.5%** in JSON / **−81.3%** in `toon`; `--fields ref,title` is **−89.5%** /
**−90.7%**.

**Truncation is an allow-list** (`prose_fields`, currently `{"body"}` only) — never a length
heuristic, because a length cut eventually mangles a `next_cursor` or a URL. The hint carrying the
true total is *in-band* (part of the string), not a new key, so it reaches every format. Measured:
default 500-char limit on a 1,351-char mean body is **−41.7%** JSON / **−44.1%** `toon` on `note
list`, **−49.7%** on `note get`.

**The aggregate is one key** (`{"count": len(records)}`), computed from a single-parameter function
so there's no corpus in scope to describe anything wider than the returned set. Measured cost:
**+0.1%** on complete records, **+2.4%**/**+3.9%** on a narrow `--fields` selection (six tokens
flat).

**Cold-start auth (KAN-539, KAN-666, KAN-717).** A single 10s introspection deadline used to `503` a
valid PAT on a cold pandan (measured: cold miss 21.8s). Split into `KAYA_PANDAN_CONNECT_TIMEOUT_SECONDS`
(5s) and `KAYA_PANDAN_READ_TIMEOUT_SECONDS` (30s). `make measure-auth --split-only` isolates connect
(67–105ms) from read (392–662ms) — connect is dominated by fly's shared-edge TLS handshake, not
pandan's own machine. KAN-717 found the actual keepalive mechanism: pandan's own
`.github/workflows/keepalive.yml` (`cron: "*/5 * * * *"`) pings `/api/health`, independent of
anything kaya does — so "a cold sample can be earned by waiting" isn't reliably true.

**`SingleFlight` coalesces concurrent introspection misses per token**, so 40 concurrent requests on
one uncached PAT cost one upstream call and one held worker instead of 40, and every waiter sees the
leader's failure (not its `None`), keeping an outage a `503` for all of them rather than a `401` for
39.

**`kaya-client`'s read deadline must outlast the backend's auth budget** (KAN-716): today 40s against
5+30+5. `backend/tests/unit/test_client_deadline_outlasts_auth.py` reads the client's constant out of
its AST and compares it against the live `Settings` defaults, cross-package, because ADR 0004's arrow
means neither package may import the other.

## Part 3 — release process detail

**The GLIBC floor (KAN-719).** PyInstaller copies the interpreter uv resolved rather than compiling
one, so the asset's glibc floor is the floor of the frozen `libpython`. `ubuntu-latest`'s preinstalled
CPython 3.12 requires `GLIBC_2.38`, which died on Ubuntu 22.04/Debian 12/RHEL 9/Amazon Linux 2023 —
most of the installed base — in `v0.4.0`. Building inside `quay.io/pypa/manylinux_2_28_x86_64` with
`UV_PYTHON_PREFERENCE=only-managed` (uv's own managed CPython, shared libpython, floor `GLIBC_2.17`)
puts the floor at `GLIBC_2.28`. `strings dist/kaya | grep GLIBC_` is inert as a check — measured, it
reports `GLIBC_2.14` on both the broken v0.4.0 asset and a fixed one, because PyInstaller's bootloader
is prebuilt and its symbols don't vary with the build host; `scripts/check-release-artifact.sh`
actually running the binary in a glibc-2.28 userland is what catches the regression.

**The TypeScript ceiling (KAN-704, Q43, and the nearer wall at 6.1).** TypeScript 7.0 ships no
programmatic API (its `exports` map resolves `"."` to a version string only), and both `svelte-check`
and `typescript-eslint` refuse it by name — that refusal *is* the guard, so there's no version-pin
test of kaya's own. A nearer wall exists one minor before that: every `@typescript-eslint/*` package
at 8.66.0 declares `typescript: >=4.8.4 <6.1.0`, tighter than `svelte-check`'s `^5.0.0 || ^6.0.0` —
the committed lockfile is the only thing keeping CI on 6.0.3, since `npm ci` pins it but `npm install`
wouldn't. Both Dependabot PRs (7.0.2 and any future 6.1.x) are left open on purpose, already red on
the frontend CI job, so nothing can drift in on a green check.

**The `git apply -R` incident.** KAN-549 lost its `__main__.py` and had to rewrite it from context
after mutating on a dirty tree: `git diff -- <file> > /tmp/mut.patch` on a tree that already had the
card's own unrelated changes captured the whole slice in the patch, and `git apply -R` reversed all
of it. The five cards before it were safe only because they happened to commit first. This is why
`CLAUDE.md`'s mutation-testing convention now says, in this order: commit the card's work, then
mutate, then reverse, then check `git status --short` is clean before believing any of it.
