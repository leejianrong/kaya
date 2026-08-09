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
`kaya-linux-x86_64` (KAN-545).

| Package | What's in it |
|---|---|
| `backend/` | The whole of V1: migration `0001`, `app/auth/` (principal resolver, `authorize_note`), `app/api/` (`/api/v1/notes` CRUD, the central ref resolver, ADR 0009's `409`), `app/spa.py`, `app/observability/` |
| `kaya-client/` | KAN-540: `KayaClient` over httpx and the `render()` seam as four composable steps. KAN-551: the full CRUD set (`create_note`, `update_note`, `move_note`, `delete_note`) — `move_note` *is* `update_note` because ADR 0008 makes a move a `PATCH` to one column, and every ref-taking method shares one `_note_path` that percent-encodes the ref as a single segment. ADR 0009's `if_updated_at` is forwarded as an **opaque string**, so nothing here can lose a microsecond. Same card: the config *file* tier (JSON at `$XDG_CONFIG_HOME/kaya/config.json`, consulted per key after the environment) and the three `config` verbs as `Payload` builders — `settings_payload()`, `path_payload()`, `write_settings()`, which read-modify-writes so a hand-set `max_text_chars` survives a `config set --api-url`. `human`/`json`/`toon` user-facing, `data` adapter-only. KAN-548: `aggregates.py` is live — a collection gets `{"count": len(records)}` and an entity gets nothing, rendered as a blank-line-separated `2 notes` footer under `human` and as a `summary` key beside the envelope everywhere else, both out of the one mapping via `summary_line()`. KAN-547: `truncation.py` is live — `text_limit` cuts the fields `Payload.prose_fields` names and appends a hint carrying the **true** total **in-band**, so the total reaches `json`/`toon`/`data`; `0` disables, and `config.max_text_chars()` resolves `KAYA_MAX_TEXT_CHARS` (default 500, a non-number is a `UsageError`). KAN-546: `projection.py` is live — `fields` narrows `records` *and* `columns` uniformly for every format, via `Payload.narrowed_to()`, with the vocabulary read from `field_names()` before anything narrows. KAN-550: `hints.py` — ADR 0005 §contract 8's `help[]` templates, keyed on `(kind, noun)` and never on a verb name, placeholders left unfilled, and **human-only** (the reverse of KAN-547's hint, because a template is advice about the tool and a total is a fact about the payload). KAN-549: `overview.py` — the three banner lines a bare `kaya` prints, which take three `str`s and **no `Payload`** so they cannot format a result — plus `RECENT_NOTES` (5), `KayaClient.recent_notes()` and `Payload.limited_to()`, the rows-wise twin of `narrowed_to`. KAN-541: `toon.py`, a stdlib-only **encode-only** TOON encoder registered in `Format`, `_SERIALIZERS` and `_ERROR_SERIALIZERS`, plus `config.py` (PLAN §Config's `KAYA_API_URL`/`KAYA_TOKEN` and `open_client()`) and `MissingCredential`. KAN-543: `provenance.version_line()` and the `_build_stamp.COMMIT` a release rewrites. KAN-542: the failure half of the layer — `error_payload()` / `render_error()`, and a `code` on every exception class so a raise site names a meaning. KAN-716: `DEFAULT_TIMEOUT` split by phase (`DEFAULT_CONNECT_TIMEOUT` 5 s, `DEFAULT_READ_TIMEOUT` 40 s) so the client outlasts the backend's authentication budget |
| `kaya-cli/` | The `kaya` console script, one entry point. KAN-541: `note list` and `note get <ref>` (`verbs.py`, a dispatch table), `--format {human,json,toon}` with `--json` as an alias and `--format` winning if both are given. KAN-551: the other seven verbs — four writes in `VERBS` and three `config` words in a second table, `LOCAL_VERBS`, because `config show` must answer with no credential at all. `parsing.resolve_body()` turns `--body`/`--body-file` into one string; there is **no `-`** for the standard input, so `tests/test_no_prompting.py` keeps proving ADR 0005 §contract 9 structurally. KAN-549: bare `kaya` is `verbs.BARE`, a row in the same dispatch table as every other verb, so `render` is still called in **exactly one place** in the package; the banner is `kaya_client.overview` joined on by `BLOCK_GAP`, and `executable_path()` — `argv[0]` resolved through `PATH`, or `sys.executable` when frozen — is this package's only new logic. KAN-547: `--full` on `output_flags()`, and `resolve_text_limit()` — a flag-beats-environment precedence and nothing else, since the number and the cut are both the client's. KAN-546: `--fields` on `output_flags()`, and `resolve_fields()` — one `split(",")`, which is the entire projection logic this package is allowed to contain. KAN-543: an argparse parser with `--version` and `--help` on it. KAN-542: that parser subclassed so it raises instead of exiting, plus `failures.py` (ADR 0005's exit table, and the only place a meaning becomes a number) and `parsing.py` (`usage:` on stderr *and* the structured row on stdout, from one event) |
| `mcp/` | A package and ADR 0006's frozen tool-name tuple. No server, no tools |
| `frontend/` | Svelte 5 + Vite + TS, a shell page, the dev proxy for `/api` |
| *root* | `Dockerfile` (bases pinned by digest), `docker-compose.yml`, `deploy/k8s/`. KAN-544: `scripts/check-version-bump.sh` (+ `lib/pyproject_diff.py`), `scripts/build-cli-artifact.sh`, `scripts/check-release-artifact.sh`, `.github/workflows/release.yml`'s `build` job. KAN-545: that workflow's `publish` job — the only `contents: write` in the repository, and it runs for a pushed `v*` tag and nothing else |

Next: **V3, the editor** — `frontend/` is still a shell page, so nothing in this repository has a
UI. After it, V4/V5 are `?q=` search (KAN-558/559) and `/links` / `/backlinks` (KAN-566), neither
of which exists at any layer, and V6 is the MCP server: `mcp/` holds ADR 0006's frozen tool-name
tuple and no server and no tools, and every one of those tools is meant to call the `render()` seam
V2a and V2b just finished. PLAN §Config's **third** tier, the nearest `.mcp.json`, is deliberately
not built and arrives with V6: choosing which server entry in an MCP host's file is kaya's is a
guess until there is a server to name, and a host launching one usually exports the `env` block
anyway, so tier one covers the common case (see `config.py`). Also unbuilt: `make test-e2e` is a
stub (KAN-552), and ADR 0005 §Consequences defers ambient session context (pandan's V48)
post-MVP.

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
MCP tool has no process to exit — `0` ok · `1` runtime · `2` usage · `3` 401 · `4` 403 · `5` 404,
**add-only** and pinned by literal-value tests. A raise site picks a class, and the class carries the
`code`; nobody writes a number. A refusal is keyed on its **status**, not on the API's code string,
because the backend's code vocabulary grows without the client's knowledge. **`2` means the
caller's input was rejected — by argparse *or* by the API**: KAN-718 added `400 → 2` to
`EXIT_FOR_STATUS` and widened ADR 0005 §contract 4's wording to match, because ADR 0008 makes
`#NOTE-12` a `400` by design and exit `1` reported the caller's own typo as kaya failing, which a
script branching on the number would retry forever. That was an *addition* — no shipped number
moved, and `invalid_note_ref` is deliberately **not** in `EXIT_FOR_CODE`, so the next `400` code
exits `2` without anybody remembering to add it. Unknown statuses still default to `1`. The `arg`
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

`make measure-auth` is a measurement rather than a gate, and the only target that reads a
credential: it takes the PAT from `KAYA_MEASURE_PAT` or `~/.config/pandan/config.toml`, never prints
it, and exits 0 having done nothing when there is none, so CI never needs a secret.
`make test-e2e` is still a stub (KAN-552).

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
  migration that drops your tables.

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

**Measurements go in the PR body.** Several slices need a number rather than an assertion:
introspection latency (V1), the `toon` delta (V2a), the CodeMirror bundle size (V3), the MCP
per-read payload cost (V6). "It's fast" is not an acceptance criterion; a number is.

**Docs.** Ban the phrase **"full parity"** from this repo. State the direction (`MCP ⊆ CLI`) and cite
the test that proves it. Pandan's skill asserted full parity in bold while contradicting itself forty
lines below, and the false claim reached a roadmap card where it nearly justified deleting a working
surface.

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
