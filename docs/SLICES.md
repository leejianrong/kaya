# kaya: Slices

Vertical increments. Each ends in something demonstrable, and no slice depends on a later one. The
end-to-end lines **are** the acceptance criteria, so each one is checkable by a person or a test rather
than by judgement.

Slice one confronts the riskiest mechanism, which here is the cross-deployment identity contract rather
than note CRUD. This departs from [`kaya-vision.md`](./kaya-vision.md) §"First steps", which proposed
CRUD plus a minimal editor first, then FTS, then `[[KAN-x]]`, then the CLI and MCP. Two reasons, agreed
in fork F3: note CRUD on a text column carries no risk worth confronting first, and putting the CLI
fourth would retrofit the output layer onto three slices of existing shapes — which is precisely the
Milestone 7 cost this plan exists to avoid (ADR 0005).

| Slice | Name | Delivers | Points |
|---|---|---|---:|
| **V1** | Walking skeleton + the identity contract | R0, R1, R1.1, R2, R9 | 8 |
| **V2a** | The output layer's signature | R3, R3.2, R3.7, R7, R7.1 | 5 |
| **V2b** | Agent ergonomics inside the layer | R3.1, R3.3, R3.4, R3.5, R3.6 | 5 |
| **V3** | The editor | R8, R2, R9 (UI) | 8 |
| **V4** | Full-text search | R4 | 3 |
| **V5** | Wikilinks, backlinks, and `KAN-` resolution | R5, R5.1 | 8 |
| **V6** | The MCP surface | R6 | 3 |

Per `/dev-playbook`: one branch per slice off fresh `main`, PR-only, protected `main`, pre-push running
lint plus the no-infra layer, CI running one job per concern. Every guard marked **[mutate]** is proven by
watching it fail and restored with `git apply -R`, never `git checkout --`.

---

## V1: Walking skeleton + the identity contract

**Delivers:** R0 (skeleton), R1, R1.1, R2, R9 · **Confronts:** the riskiest unknown in the plan

The one thing in this project that couples two deployments and is expensive to reverse. Everything else
assumes it works, so it goes first and gets measured rather than asserted.

**Build plan**

1. **Pandan first:** add `GET /api/v1/me` to pandan, returning the resolved user's id and email. Sync,
   reuses `get_principal` unchanged, no schema change. Ships as its own small PR on the pandan repo.
2. Scaffold the repo: `backend/`, `kaya-client/`, `kaya-cli/`, `mcp/`, `frontend/` (empty shell),
   `Makefile` with `make up` / `make dev` / `make test`, `docker-compose.yml` with Postgres 17.
3. `CLAUDE.md`: build status stated honestly, exact commands, branch/PR/test conventions, and the two
   inherited stack traps (integration-test imports inside fixture bodies; models imported in Alembic
   `env.py`).
4. Alembic migration `0001`: `user` mirror (pandan UUID as PK, email) and `note` (id, `NOTE-n` ref via
   `SEQUENCE` + `server_default`, owner_id → user, title, body TEXT, path, created_at, updated_at). Comment
   at the sequence recording that the prefix is deliberately immutable (ADR 0008).
5. **The principal resolver** (ADR 0002): bearer → `sha256` cache lookup → on miss, `GET /api/v1/me` on
   pandan with the bearer forwarded → JIT-mirror the user row → return it. No prefix inspection. Inject the
   upstream client so it is fakeable at the HTTP boundary. Negative cache 10s, positive 60s.
6. `authorize_note`: owner-only, `404` for absent, `403` for someone else's, list scoped to the caller.
7. `/api/v1/notes` CRUD with the central ref resolver (`NOTE-n` or bare id, identical outcomes), and the
   `updated_at` precondition returning `409` with both bodies (ADR 0009).
8. Single-artifact serving (FastAPI mounts the built SPA), Dockerfile with **pinned base digests** and
   provenance labels, k8s manifests, and a `make k3d` target that applies them to a local cluster.
9. CI: lint, unit, integration, build as parallel jobs with frozen installs and caching. Pre-push hook
   running lint plus the unit layer.

**Demo:** with a real `pandan_pat_…` in the environment and no kaya-side credential of any kind, `curl`
creates a note, reads it back by `NOTE-1` and by id, and edits it. A second user's PAT gets `403` on that
note. Stop pandan, and a request with an already-seen token still works; a request with a fresh token
returns `503` naming the upstream, never `401`. Then `make k3d` and the same demo against the pod.

**Rests on assumptions:** Q6 (60s cache TTL — if too long, revocation lags; one constant), Q9 (`503` not
`401` on upstream failure), Q16 (`NOTE-n` identity — if wrong, a migration plus a link rewrite, which is
why it's settled in ADR 0008 rather than discovered).

### Test plan

#### End-to-end

- A pandan-minted PAT creates, reads, edits and deletes a note through `/api/v1` with no kaya-side credential configured.
- The same note is retrievable by `NOTE-1` and by its integer id, and both forms return byte-identical bodies.
- A missing note returns `404` with the **same** error code whether addressed as `NOTE-9999` or `9999`. **[mutate]**
- A second user's PAT gets `403` on the first user's note, and `GET /api/v1/notes` omits it entirely rather than returning an empty list for a scoped query.
- With pandan stopped: a cached token still authenticates; an unseen token returns `503` naming the upstream and **not** `401`. **[mutate]**
- Two writers read one note, both `PATCH`; the second receives `409` carrying both bodies. **[mutate]**
- `make k3d` applies the manifests and the pod serves the same demo.
- **Measured and recorded in the PR:** introspection latency on a cache hit, on a cold-upstream miss, and on a warm-upstream miss. This is the open risk from PLAN, so the numbers go in the slice record.

#### Integration

- The resolver JIT-creates exactly one mirror row for a first-seen UUID, and reuses it on the second request.
- A revoked token stops working once the cache entry expires.
- A stray `Authorization` header costs no upstream call on the second attempt (negative cache holds).
- Alembic upgrade-then-downgrade leaves a clean schema.
- The `NOTE-` sequence allocates atomically under concurrent inserts and never reuses a value.

#### Unit

- The cache is keyed on a hash: the raw token never appears in the cache's keys or values. **[mutate]**
- No code path inspects a token prefix (asserted by a grep-style test over the auth module). **[mutate]**
- The ref parser accepts `NOTE-12`, `note-12`, `12`; rejects `#NOTE-12` as a usage error.
- The `409` body contains both the attempted and the stored version.
- A write omitting the precondition is accepted as a plain overwrite.

---

## V2a: The output layer's signature

**Delivers:** R3 (the layer), R3.2, R3.7, R7, R7.1

The slice that fixes the shape everything later emits through. Deliberately narrow on verbs and deliberately
complete on the layer, per ADR 0005's sequencing rule.

**Build plan**

1. `kaya-client`: `KayaClient` over httpx, plus the **`render(payload, *, fields, text_limit, fmt)`** seam as
   the single shaping-and-serializing entry point (ADR 0004). V2a implements only the `fmt` dimension; the
   other parameters exist in the signature and pass through untouched.
2. `--format {human,json,toon}` over that one serializer, with `--json` as a documented alias and `--format`
   winning if both are given. The `toon` encoder is stdlib-only and encode-only; the round-trip contract is
   proven by a test-only decoder.
3. The error contract: `error<TAB><code><TAB><message><TAB><arg>` on **stdout**, or an `{"error": {...}}`
   object under a structured format with all keys always present. An add-only named-code table maps codes to
   exit numbers, so a raise site picks a meaning and never a number.
4. Exit codes `0/1/2/3/4/5` per ADR 0005, pinned by literal-value tests.
5. `kaya note list` and `kaya note get` only. Nothing else.
6. Build-stamped `--version` (ADR 0007): release form and source-checkout form, both explicit.
7. The version-bump guard, **diffing against the merge-base with `main`**, in the pre-push hook and CI.
8. The release workflow, including the gate that executes the built artifact and **fails if it can't report a
   real commit sha**.
9. Cut the first release, so a downstream binary carrying provenance actually exists.

**Demo:** `kaya note list --format human | json | toon` on the same data, three shapes, one serializer.
`kaya note get NOTE-9999` prints a structured error row on **stdout** and exits `5`. `kaya --version` prints
the sha from a release binary and says "source checkout" from a checkout. A behavioural PR with no version
bump goes red; the same change on a merge commit does not.

**Rests on assumptions:** Q23 (pandan's exit-code scheme adopted verbatim — renumbering later is a breaking
change, which is why it is adopted rather than invented), Q30 (merge-base diff).

### Test plan

#### End-to-end

- The same payload rendered as `human`, `json` and `toon`; the `toon` output parses back to data **equal** to the `json` output.
- Seven failure classes each assert stream, shape and exit code: unknown flag (2), invalid enum (2), missing token (1), 400 (2), 404 (5), 401 (3), 403 (4). The `400` is KAN-718's addition — ADR 0008 makes a malformed ref a designed outcome of the ref resolver, and ADR 0005's table had no row for it, so it reported as a runtime failure.
- A released binary's `--version` reports a sha matching the commit it was built from; a source run says so explicitly.
- The release job **fails** when handed an artifact whose sha is missing. **[mutate]**
- The bump guard fires on a behavioural diff with no version change, stays quiet on a docs-only diff, and stays quiet on a merge commit. **[mutate — the merge-commit case especially, since it is the assertion pandan's guard fails today]**

#### Integration

- Every verb's error path routes through the shared contract; nothing writes an error to stderr as prose.
- `--format` and `--json` together resolve to `--format`'s value.
- An unknown `--format` value is a usage error, exit `2`, in the structured shape.

#### Unit

- The named-code table maps each code to its documented exit number (literal values, so a renumber breaks a test). **[mutate]**
- The default human row for `note list` is pinned **byte-identically**, so V2b can prove it changed nothing. **[mutate]**
- No verb prompts when stdin isn't a tty; it returns a structured failure.
- The `toon` encoder matches a fixed corpus byte-for-byte.

---

## V2b: Agent ergonomics inside the layer

**Delivers:** R3.1, R3.3, R3.4, R3.5, R3.6

Everything lands on V2a's seam unmoved. If a step here needs to change `render`'s signature, the sequencing
rule was violated and that is the signal to stop and reconsider rather than push through.

**Build plan**

1. **`--fields a,b,c`** on every list verb, vocabulary derived from the payload's own keys so it cannot drift
   from the API. Unknown name → a clean error naming it. A usage error on single-entity verbs, never a silent
   no-op. `--fields` does not affect structured output.
2. **Truncation** with a true total and `--full`, over an **allow-list** of prose fields (`body`, and any
   other unbounded `TEXT` column) rather than a length heuristic. Multi-byte characters never split
   mid-character. A truncated value stays a string. Limit from `KAYA_MAX_TEXT_CHARS` / config, default 500,
   `0` disables, and `config show` reports the effective value.
3. **Aggregates**: a `summary` describing **the returned set** (under a filter or `--limit`, the returned set
   and not the corpus). A trailing line for humans, a `summary` object for structured consumers, both from the
   same dict. Attached **after** truncation.
4. **Content-first bare invocation**: bare `kaya` prints the executable path, a one-line description, recent
   notes and the aggregate, and exits `0`. No token → V2a's structured auth error, not a stack trace.
   `--help` unchanged.
5. **`help[]` next-step templates**, per verb, with placeholders left unfilled (`kaya note edit <ref>
   --body-file …`). Suppressed under structured formats.
6. The full verb set: `note {list,get,create,edit,move,delete}`, `config {set,show,path}`.

**Demo:** `kaya note list --fields ref,title,path` widens the row; omitting it leaves the default row
byte-identical. A long note's `get` shows `(truncated, 2847 chars total — use --full to see complete body)`
with a **true** total. Bare `kaya` prints live state and exits `0`.

**Rests on assumptions:** Q13/ADR 0004 (shaping in the client — if this had gone in the CLI, V6 would inherit
nothing).

### Test plan

#### End-to-end

- `--fields` selects the named columns, rejects an unknown name by naming it, and leaves the default row **byte-identical** when omitted. **[mutate — this is V2a's pin doing its job]**
- Under-limit text is byte-identical; over-limit truncates at the limit with a **true** total in the hint; `--full` restores the whole body everywhere it applies.
- The aggregate matches the rows actually returned under a filter and under `--limit`, describing the returned set rather than the whole corpus. **[mutate]**
- An empty result still prints a definitive zero state rather than nothing.
- Bare `kaya` exits `0` and prints rows, not usage. With no token it prints the structured auth error.
- Every `help[]` line emitted by any verb **parses as a valid command**, and contains a literal placeholder rather than an interpolated value. **[mutate]**

#### Integration

- `--fields` on a single-entity verb is a usage error, not a silent no-op.
- `KAYA_MAX_TEXT_CHARS=0` disables truncation; `config show` reports the effective value.
- A config write preserves a hand-set `max_text_chars` that `config set` has no flag for.

#### Unit

- Truncation never splits a multi-byte character.
- Truncation touches only allow-listed fields: a long `next_cursor` and a long URL pass through intact. **[mutate]**
- `summary` counts are computed after truncation and are unaffected by it. **[mutate]**
- A truncated value is still a string; no key is added, removed or retyped.

---

## V3: The editor

**Delivers:** R8, R2 (UI as a thin client), R9 (the human-facing half)

**Build plan**

1. Svelte 5 SPA shell with runes, Vite dev proxy forwarding `/api` to the backend, built output served by
   FastAPI from the same origin.
2. **CodeMirror 6** mounted once in an `$effect` against an element ref: `@codemirror/state`, `view`,
   `lang-markdown`, `commands`, `search`. Svelte never renders inside the subtree; changes go in as
   transactions and come out through an update listener, with a **guard on the write-back** comparing against
   the editor's current document so the rune binding cannot loop.
3. **Measure and record the bundle size** in the PR (ADR 0001's obligation).
4. Live preview, a folder tree from `path`, and a note list.
5. Landing state for an unauthenticated visitor, pointing at pandan's origin from `KAYA_PANDAN_URL`, with a
   one-time PAT paste (browser SSO is deferred, ADR 0010).
6. The **conflict banner**: on a `409`, show both versions side by side with "keep mine" / "keep theirs".

**Demo:** open a note in a browser, edit it, watch the preview update, reload and see it persisted. Open the
same note in two tabs, edit both, and the second save shows the conflict banner with a real diff rather than
silently winning.

**Rests on assumptions:** Q12 (CodeMirror 6 — the one frontend unknown with teeth, and contained: it cannot
invalidate the data model or the API, which is why it isn't slice one).

### Test plan

#### End-to-end

- Create, edit and reload a note in a browser; the text persists.
- Editing the same note in two tabs produces the conflict banner on the second save, showing both versions. **[mutate]**
- Typing in the editor does not cause an update loop: a fixed 20-keystroke sequence produces exactly one final document state and exactly one `PATCH` per elapsed debounce interval, asserted as a call count. **[mutate]**
- The folder tree reflects a `path` change made through the API without a reload of the whole app.
- An unauthenticated visitor sees the landing state and a working link to pandan.

#### Integration

- Every UI action maps to a documented `/api/v1` call; a test asserts no request hits a route outside `/api/v1` (R2).
- The SPA sends the `updated_at` precondition on every body write.

#### Unit

- The editor mounts once per note and tears down cleanly on navigation (no leaked listeners).
- The write-back guard suppresses an echo when the incoming value already equals the current document.
- Markdown highlighting is applied for the constructs the product needs (headings, code fences, links).

---

## V4: Full-text search

**Delivers:** R4

**Build plan**

1. Migration: a generated `tsvector` column over title and body with a GIN index, mirroring pandan V15.
2. `GET /api/v1/notes?q=` with results scoped to the caller.
3. `--q` on `kaya note list`, and a search box in the SPA.
4. Rank by relevance, with a documented tie-break so ordering is deterministic and testable.

**Demo:** `kaya note list --q "runbook"` returns matching notes with the aggregate; the same query in the
browser highlights matches.

### Test plan

#### End-to-end

- A phrase present only in a note's body finds that note from the API, the CLI and the SPA.
- Search results are owner-scoped: another user's matching note never appears. **[mutate]**
- Identical queries return results in a deterministic order.

#### Integration

- The `tsvector` column updates when a note's body is edited, with no application-level reindex step.
- `--q` composes with `--fields`, `--limit` and the aggregate, and the aggregate describes the matched set.

#### Unit

- Query parsing handles an empty string, a single term, a quoted phrase, and characters that would otherwise be `tsquery` syntax.

---

## V5: Wikilinks, backlinks, and `KAN-` resolution

**Delivers:** R5, R5.1

The slice where the second integration contract lands. R5.1 is the acceptance criterion that keeps ADR 0003's
coupling soft, and it gets a guard rather than a promise.

**Build plan**

1. ~~**Before building:** check whether pandan can batch a card read.~~ **DONE — settled ahead of the slice
   by [spike 0001](./spikes/0001-wikilink-ref-batching.md), and the answer is not what this slice assumed.**
   Read it before writing the resolver. There is no fan-out to choose between, because a wikilink carries a
   ticket ref and **no pandan route accepts one**. The resolver does **one bounded, cached page walk of
   `GET /api/v1/cards?limit=200` per batch**, one request in flight, caching every card returned rather than
   only the referenced ones — ~3s per request, ~8s total deadline, five-page cap so a large board degrades to
   partially resolved. No `ThreadPoolExecutor`, no async client, no async engine (a fan-out would hold a kaya
   Postgres connection per in-flight request and take down note *saving*, and would hit pandan's
   `hard_limit = 40` on one instance). V5 does **not** wait on pandan issue 254.
2. A `[[…]]` parser extracting links on save. Parse `KAN-` and `EPIC-`, **not** `PAN-` (ADR 0003).
3. Migration: `note_link` (source note id, target kind, target ref, resolved target id nullable).
4. Note→note resolution by title, with the resolved id recorded so a later rename doesn't break the edge.
5. Card/epic resolution against pandan **with the caller's own PAT**, cached, with a TTL separate from the
   auth cache.
6. `GET /api/v1/notes/{ref}/links` and `/backlinks`; `kaya links` and `kaya backlinks`.
7. Editor: wikilink pills via `Decoration.mark`, and an autocomplete source on `[[` querying
   `GET /api/v1/notes?q=`.
8. Backlinks panel in the right rail.

**Demo:** a note containing `[[KAN-501]]` renders `KAN-501 · in_progress · "MCP read tools: add a fields
argument…"` inline. `kaya backlinks KAN-501` lists every note mentioning it. Then **stop pandan**: the note
still opens, still saves, still turns up in search, and the link renders unresolved with a hint.

**Rests on assumptions:** Q19 (resolve by title, record the id), Q26 (unresolved rendering rather than an
error).

### Test plan

#### End-to-end

- A note containing `[[KAN-501]]` renders the card's title and column.
- **With pandan completely stopped: the note saves, renders, and appears in full-text search; the link renders unresolved with a hint and nothing returns an error.** **[mutate — the whole point of ADR 0003, and exactly the kind of degradation guard that passes for the wrong reason]**
- `kaya backlinks NOTE-3` lists every note linking to it, answered from kaya's own database with pandan down. **[mutate]**
- Renaming a note leaves existing backlinks to it intact. **[mutate]**
- A note-to-note link to a title that doesn't exist yet resolves once a matching note is created.
- Typing `[[` in the editor opens autocomplete and inserting a suggestion produces a link that resolves.

#### Integration

- **Upstream requests scale with pages, not refs** (spike 0001): a forty-ref note issues at most three upstream requests, and a **second** render of it issues none. The test asserts the upstream call *count*, not just the result — a resolver that works correctly one ref at a time passes every result assertion and is the thing being ruled out. **[mutate]**
- Resolution uses the caller's PAT: a note referencing a card the reader cannot see renders unresolved rather than leaking the title. **[mutate]**
- Editing a note reconciles `note_link` — removed links disappear, added ones appear, unchanged ones aren't churned.
- `PAN-1` is not parsed as a ticket ref; `KAN-1` and `EPIC-1` are.

#### Unit

- The parser handles nesting, unclosed `[[`, a link inside a code fence (not a link), and a link with surrounding punctuation.
- The resolution cache is separate from the auth cache and has its own TTL.

---

## V6: The MCP surface

**Delivers:** R6

Small by construction: shaping already lives in the client (ADR 0004), so the tools inherit `fields` and
truncation rather than implementing them.

**Build plan**

1. Six tools over `KayaClient`, each read tool taking **`fields`**: `list_notes`, `get_note`, `create_note`,
   `edit_note`, `search_notes`, `get_backlinks`. Each calls the same `render`.
2. `FROZEN_TOOLS` name set and `FROZEN_TOOL_COUNT`, asserted, with a failure message explaining why the pin
   exists and warning that a removal needs a parity check first.
3. Schema compaction: strip generated `title` keys, collapse `anyOf: [{T},{null}]` — with the **nullable-enum
   exclusion** and the **`title`-is-also-an-argument-name** guard from ADR 0006.
4. `mcp/README.md` stating the direction **`MCP ⊆ CLI`** in the one canonical place, with the token
   measurements. The phrase "full parity" appears nowhere.
5. The parity test: every frozen tool name has a corresponding CLI verb.
6. Dockerfile with **pinned base digests** and provenance labels (ADR 0007).
7. **Measure and record** the resident schema cost and a representative per-read payload cost, so the next
   person to ask starts from numbers rather than intuition.

**Demo:** an agent lists notes through MCP with `fields` set and the payload is a fraction of the unnarrowed
one, with the measured ratio in the PR. `edit_note` on a stale `updated_at` returns the `409` as a structured
tool error.

### Test plan

#### End-to-end

- Every read tool honours `fields` and truncates by default, verified against the equivalent CLI invocation producing the **same shaped payload**. **[mutate]**
- `edit_note` with a stale precondition surfaces the conflict, both versions present.
- The measured per-read payload with `fields` is recorded in the PR alongside the unnarrowed figure.

#### Integration

- Adding a tool without updating `FROZEN_TOOLS` fails; removing one fails with the parity warning. **[mutate, both directions]**
- Every frozen tool name has a CLI verb. **[mutate]**
- Compaction preserves every argument name, including an argument genuinely called `title`, and the advertised schema still agrees with the validating model. **[mutate]**

#### Unit

- A nullable **enum** is left uncollapsed; a nullable scalar is collapsed. **[mutate]**
- The tool count matches the frozen constant, asserted two ways (a decorator count and the length of the listed tools).

---

## Out of scope for the MVP

Recorded here so the boundary is visible from the build document, not only from PLAN §Scope.

- A hosted deployment and browser SSO (ADR 0010, Q7) · attachments (Q35) · per-note sharing (Q8) ·
  real-time collaboration (Q22) · a graph view (Q36) · an embedded live board view (Q37) · export and import
  (Q18, though the ref is designed for it) · ambient session context, pandan's V48 (ADR 0005) · a published
  docs site (Q34) · a plugin ecosystem, permanently (Q38).
