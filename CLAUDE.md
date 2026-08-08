# CLAUDE.md: agent brief for `kaya`

## Build status

**V1 is complete.** A pandan PAT creates, reads, edits and deletes notes over `/api/v1/notes`.
`make up` runs the whole stack on `:8000` from the image, and `make k3d` applies `deploy/k8s/` to a
throwaway cluster and then makes requests against it, because an `apply` that succeeds only proves
the API server liked the YAML (ADR 0010).

| Package | What's in it |
|---|---|
| `backend/` | The whole of V1: migration `0001`, `app/auth/` (principal resolver, `authorize_note`), `app/api/` (`/api/v1/notes` CRUD, the central ref resolver, ADR 0009's `409`), `app/spa.py`, `app/observability/` |
| `kaya-client/` | KAN-540: `KayaClient` over httpx (`list_notes`, `get_note`) and the `render()` seam as four composable steps. Only the `fmt` dimension is implemented — `human`/`json` user-facing, `data` adapter-only; `fields` and `text_limit` are **pinned no-ops**. No `toon`, no write verbs. KAN-543: `provenance.version_line()` and the `_build_stamp.COMMIT` a release rewrites. KAN-542: the failure half of the layer — `error_payload()` / `render_error()`, and a `code` on every exception class so a raise site names a meaning |
| `kaya-cli/` | The `kaya` console script, one entry point, **no verbs**. KAN-543: an argparse parser with `--version` and `--help` on it. KAN-542: that parser subclassed so it raises instead of exiting, plus `failures.py` (ADR 0005's exit table, and the only place a meaning becomes a number) and `parsing.py` (`usage:` on stderr *and* the structured row on stdout, from one event) |
| `mcp/` | A package and ADR 0006's frozen tool-name tuple. No server, no tools |
| `frontend/` | Svelte 5 + Vite + TS, a shell page, the dev proxy for `/api` |
| *root* | `Dockerfile` (bases pinned by digest), `docker-compose.yml`, `deploy/k8s/`. KAN-544: `scripts/check-version-bump.sh` (+ `lib/pyproject_diff.py`), `scripts/build-cli-artifact.sh`, `scripts/check-release-artifact.sh`, `.github/workflows/release.yml` |

Next: KAN-541 puts the CLI verbs (`kaya note list`, `kaya note get`), `--format` and the `toon`
encoder on top of that seam — it adds `toon` to `_SERIALIZERS`, `_ERROR_SERIALIZERS` and `Format`,
and hangs its subparsers off `build_parser()`, which already fails correctly. KAN-545 cuts the first
release: KAN-544's `.github/workflows/release.yml` builds and gates the artifact but deliberately
publishes nothing. Still unbuilt anywhere are `?q=` search (KAN-558/559), `/links` and `/backlinks`
(KAN-566), and the SPA's real UI (V3).

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
   local optimisation. Pandan put shaping in its CLI, so its MCP adapter inherited none of it and one
   `list_cards` call costs 44,902 tokens against 2,689 for the equivalent CLI read.
2. **Kaya has no token format and no prefix logic** ([ADR 0002](docs/adr/0002-identity-pandan-as-provider.md)).
   Authentication forwards the bearer to pandan's `GET /api/v1/me` and caches the answer keyed on
   `sha256(token)`. Do not add a `startswith` guard: pandan still accepts pre-rebrand `kanban_pat_…`
   tokens, and that exact guard is the bug pandan ADR 0018 had to correct.
3. **The output layer's signature lands before behaviour goes inside it** ([ADR 0005](docs/adr/0005-born-agent-conformant.md)).
   V2a builds the seam; V2b fills it. If a V2b-or-later change needs to alter `render()`'s signature,
   stop. That is the signal the sequencing was violated, not a reason to push through.
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
signature ADR 0005 freezes until V2b.

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
because the backend's code vocabulary grows without the client's knowledge. The `arg` slot is
**the first scalar extra a refusal carries**, which is unambiguous only while a refusal carries one;
`backend/tests/unit/test_error_extras_stay_addressable.py` is the alarm for that, because the client
may never import the backend and so cannot see a second one appear.

**`KayaClient` returns a `Payload`, never a response body, and `render()` refuses a raw `dict`.**
That is ADR 0004 at its sharpest point: the moment a dict crosses that boundary, whoever formats it
has to re-derive list-vs-entity, the field vocabulary and the prose allow-list, and the obvious
place to put that derivation is the adapter — which is pandan's 11.4×. The four steps are one module
each in ADR 0004's fixed order, and the order is **type-enforced**: `truncate` takes and returns a
`Payload`, `attach_summary` returns a `Shaped`, and `serialize` accepts only a `Shaped`, so ADR
0005's "the summary is structurally out of the truncator's reach" is a fact rather than a convention.
`fields` and `text_limit` are **no-ops until V2b** and `tests/test_passthrough_is_a_no_op.py` pins
that, so V2b arrives as a visible diff. The default human row is pinned byte-for-byte in
`tests/test_human_row_is_pinned.py`; if a later slice reddens it while `--fields` was omitted, that
is the guard working, not a stale test to update.

**A `--format` value is a published contract; a registered serializer is not.** `Format` holds only
what a person may type (`CLI_FORMATS` is that as a tuple, for argparse `choices`); `AdapterFormat`
holds `data`, which exists for MCP's `structuredContent` and is reachable in code only.
`_SERIALIZERS` is the full registry behind both, and `UnknownFormat` lists the user-facing set only,
because a suggestion in an error message is a contract too and that message reaches a shell. Adding
a format to the registry must not advertise it — ADR 0005 adopts pandan's exit codes verbatim rather
than improving them for exactly this reason, and pandan spent a whole card (KAN-442) withdrawing a
`pdn` alias. **KAN-541 adds `toon` to both**, and the literal pin in
`test_the_published_cli_vocabulary_is_pinned` makes that a conscious edit.

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
