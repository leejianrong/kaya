# kaya MCP server

A thin adapter over `kaya-client`, so `fields` and truncation exist on day one by construction
rather than by being retrofitted ([ADR 0004](../docs/adr/0004-shaping-lives-in-the-shared-client.md)).
KAN-569 stood the server up: `src/kaya_mcp/server.py` holds one `MCPServer` instance and six
`@server.tool()` registrations, and `src/kaya_mcp/tools.py` holds the one-client-call-each bodies.
This is a running server, not a skeleton.

There used to be a third module, `src/kaya_mcp/errors.py`, holding the one failure this package
invented for itself — the refusal `get_backlinks` raised while `/links`/`/backlinks` had landed at no
layer. KAN-964 deleted it: KAN-566 landed all three layers, so the refusal was no longer an honest
sequencing gap. **This package now invents no failure of its own**, which is what ADR 0004's arrow
predicts of a thin adapter — every failure a tool can raise is a `kaya_client` one.

## The direction: `MCP ⊆ CLI`

**This is the one place that states it.** Every other document in this repo links here rather than
restating it — that duplication is exactly what let pandan's packaged skill claim complete tool-for-
tool coverage in bold while a `curl` workaround for a missing CLI verb sat forty lines below it, and
the false claim nearly justified deleting a working MCP surface from a roadmap card. See
[ADR 0006](../docs/adr/0006-mcp-surface-born-narrow.md) for the full reasoning and the numbers
behind it — pandan's own unnarrowed `list_cards` read costs 44,902 resident tokens, falling to 7,204
once projected to five fields (ADR 0004), which is the ~84% saving kaya's tools inherit from
`render()` by construction rather than as a follow-up.

Every MCP tool has a CLI verb behind it — deliberately the inverse of pandan's `MCP ⊇ CLI`, which is
how pandan ended up with four MCP capabilities no CLI command could reach and a surface that became
impossible to retire. In kaya, the MCP server is always removable, and a single exec-`kaya` tool
stays available as a future simplification rather than being blocked on closing gaps.

**Both halves of that are now tests** (KAN-570 landed the second one). Three files, and the split
is deliberate, because a set, a count and a direction fail for different reasons:

- `tests/test_server.py` pins the *running server's* registrations against `kaya_mcp.TOOL_NAMES`
  name for name, so a stray seventh tool or a missing decorator fails there.
- `tests/test_frozen_tool_set.py` holds ADR 0006 §2's freeze: `FROZEN_TOOLS` and
  `FROZEN_TOOL_COUNT` as literals separate from the shipped tuple, the count asserted **twice** —
  once off `server.py`'s `@server.tool()` decorators and once off what the server lists, because a
  registration that never becomes a listing counts in one and not the other — and the failure
  message the ADR asks for: why the pin exists, that adding a tool amends the ADR rather than
  appending a decorator, and the four-step check a *removal* has to pass first.
- `tests/test_cli_parity.py` is §4 rule 2: every frozen tool name has a CLI verb behind it. It reads
  `kaya-cli`'s `verbs.py` dispatch tables and `__main__.py`'s parser construction as **ASTs** rather
  than importing them, because ADR 0004 points the dependency arrow at `kaya-client` and neither
  adapter may depend on the other — the same technique, for the same reason, as
  `backend/tests/unit/test_client_deadline_outlasts_auth.py`. So a CLI verb renamed in the other
  package reddens here, which is the assertion that makes this a parity check rather than a copy of
  one.

The table is the mapping that test holds, and it is **data rather than derivation** — see the row
marked ¹ for why that is not a shortcut:

| MCP tool | `KayaClient` method | CLI equivalent |
|---|---|---|
| `list_notes` | `list_notes()` | `kaya note list` |
| `get_note` | `get_note(ref)` | `kaya note get <ref>` |
| `create_note` | `create_note(...)` | `kaya note create <title>` |
| `edit_note` | `update_note(...)` | `kaya note edit <ref>` |
| `search_notes` | `list_notes(q)` | `kaya note list --q <term>`¹ |
| `get_backlinks` | `backlinks(ref)` | `kaya backlinks <ref>` |

¹ The only row where the tool name and the CLI word differ, and the only one where two tools share a
client method: there is no separate search call, because `GET /api/v1/notes?q=` answers with the same
`NoteList` a plain list does (KAN-558/559). **This row is why the parity test is keyed on a table and
not on tool names** — a name-derived check would go looking for a `kaya search_notes` that will never
exist, pass for five tools, and need a hand-written exception for the sixth, which is the parity test
not holding. It is also why a row is *argv* rather than a verb word: `--q` is in the row, so deleting
that flag from `kaya-cli` leaves `search_notes` with no CLI spelling and fails the test, where a
word-only row would still find `note list` sitting there for `list_notes`. Output-shaping flags
(`--fields`, `--full`, `--format`) are deliberately **not** in any row: they are ADR 0004's one
parameter through one seam, on every verb by construction, and naming them here would be `mcp/`
re-asserting a shaping contract it is forbidden to hold an opinion about.

**KAN-964 is why every row above names something real.** Until it landed, `get_backlinks` refused
every call, which would have let KAN-570's parity test go green over a tool that did not work — a
correct-looking pin across a set where one member was broken. Landing it first meant KAN-570 pinned
a set where every member functions.

What is still *not* automated is the truth of this file's prose, only its uniqueness: nothing in
`make check` reads the paragraphs above and compares them with the code. KAN-570 closes one corner of
that (names to verbs) and no more, which is why ADR 0006 §4's first rule — state it here and link,
never restate — is doing as much work as the tests are.

## The six tools, honestly

ADR 0006 froze `list_notes`, `get_note`, `create_note`, `edit_note`, `search_notes`, `get_backlinks`
before any of them existed, so they'd be written against a list rather than the list being
reverse-engineered from whatever got built. All six are real today:

- `list_notes`, `get_note`, `create_note`, `edit_note`, `search_notes` each open a `KayaClient`
  session, make the one call `kaya-cli`'s equivalent verb makes, and return through `render()` — so
  `fields` and truncation are inherited rather than reimplemented, and a stale `if_updated_at` on
  `edit_note` surfaces ADR 0009's `409` (`attempted`/`stored`, both whole notes) as a structured
  tool-level failure rather than a swallowed error.
- `get_backlinks` does the same, as of KAN-964: `KayaClient.backlinks(ref)`, then `render()`. It is
  worth its own bullet only because of where it came from. KAN-569 had to register it — ADR 0006
  froze it as one of the six — while `/links`/`/backlinks` existed at no layer, so every call raised
  a refusal naming KAN-566 rather than a stub returning `{"notes": []}`, an empty list being
  indistinguishable from "this note genuinely has no backlinks". KAN-566 then landed the route
  (`backend/app/api/links.py`), the client method and two CLI verbs — and the refusal did **not**
  resolve itself, which is what this README claimed it would. KAN-964 is the card that noticed, and
  the lesson is the one ADR 0006 §4 is already about: a claim in the canonical place has to be
  re-read when the thing it describes changes, because nothing else re-reads it.

  Two things worth knowing about how it landed. **The signature did not move**, which KAN-569
  predicted in `server.py`'s docstring — the whole change is one function body in `tools.py`. And
  `fields`, truncation and the `{"count": n}` aggregate arrived with **no line written for them**,
  because `KayaClient.backlinks` returns the note noun, the note columns and the note prose fields:
  `/backlinks` answers with the very same `NoteList` a plain list does, so the tool is `list_notes`
  at a different URL (ADR 0004, and `kaya-client/src/kaya_client/client.py`'s `backlinks` docstring
  for the full argument).

## The advertised schemas are compacted, and it is the small half

KAN-571 landed ADR 0006 §3: generated `title` annotations stripped, and `anyOf: [{T}, {null}]`
collapsed to `type: [T, null]`. `src/kaya_mcp/schema.py` is the rule and
`server.SchemaCompactingServer` applies it at `list_tools` — the one place a tool's input schema
leaves this process, and a place from which the pydantic model that *validates* a call is not
reachable. So "compaction changes what a host is told, never what is accepted" is structural rather
than promised, and `tests/test_schema_compaction.py` checks it three ways anyway: same argument
names and required-ness and nullability, then every call in a derived corpus admitted by both
schemas or neither, then real `call_tool` runs against the fake API.

Measured on these six tools, `o200k_base`, re-runnable with
`uv run --with tiktoken python scripts/measure_schema_compaction.py --markdown`:

| what | bytes | tokens (`o200k_base`) |
|---|---|---|
| input schemas only | 1,633 → 1,022 (−37.4%) | 428 → 265 (−38.1%) |
| whole `tools/list` reply | 3,701 → 3,090 (−16.5%) | 948 → 785 (−17.2%) |

**Read the second row, and read it beside the other number.** The first row is the biggest honest
percentage and the narrower thing — it is what changed, not what a host holds. The second is the
whole reply a host keeps resident, tool descriptions included, which compaction does not touch; it
lands on the ~16% ADR 0006 §3 predicted. That same section measured **84%** for narrowing a read to
five useful fields, which these tools have taken since KAN-569 by calling `render()`. Compaction is
the 16%. ADR 0006's Finding 1 is exactly that trimming the resident surface optimises a ~4%-of-window
line item while a 22% one sits beside it, so this is hygiene worth taking and not a win worth
overselling. The per-read payload figure — the 22% side — is measured below (KAN-574).

### The per-read payload figure, measured against kaya's own data

The 84% quoted above is pandan's — `list_cards` against pandan's board, inherited into ADR 0006
only as the argument for why kaya's tools take `fields` from day one. Nobody had measured what a
real kaya tool *call* costs through kaya's own MCP server against kaya's own notes until KAN-574,
which is the number this section reports.

Unlike schema compaction, a tool call needs I/O a static `tools/list` does not: a live kaya backend,
a real pandan PAT, and a real `kaya-mcp` subprocess talked to over stdio — the same transport
`scripts/verify_stdio_image.py` drives against a built image, here against `python -m kaya_mcp` so
no image is needed. `scripts/measure_read_payload.py` is that script, and its own docstring is why
it is a script and not a test: there is no hosted kaya (ADR 0010) to run it against in CI, and no
committed fixture corpus realistic enough to make truncation's effect honest, so wiring it into
`make check` would mean either standing up a stack on every push for a number that does not move
between runs, or teaching CI a secret it does not otherwise need. It follows `make measure-auth`'s
contract instead: reads a credential (`KAYA_MCP_MEASURE_PAT`, falling back to
`~/.config/pandan/config.toml`), never prints it, and exits 0 having done nothing when the target
backend or the credential is absent.

Measured 2026-08-20 against an isolated stack (`COMPOSE_PROJECT_NAME=kaya-measure KAYA_DB_PORT=5443
KAYA_APP_PORT=8023 make up` — never the shared dev stack on :8010/:5434) seeded with 40 notes of
realistic, non-uniform multi-paragraph markdown (`--seed-notes 40`; corpus shape: mean body 1,382
chars, range 630–2,221 — close to `kaya-client/scripts/measure_toon_delta.py`'s own 40-note, 1,351-
mean corpus, so the percentage below is not an artifact of one-line placeholders), driven with a
real pandan PAT and re-runnable with:

```bash
KAYA_MCP_MEASURE_URL=http://localhost:8023 KAYA_MCP_MEASURE_PAT=<a real pandan PAT> \
  uv run --with tiktoken python scripts/measure_read_payload.py --markdown
```

Two rows per call, the same reason `measure_schema_compaction.py` keeps two: **`structuredContent`
only** is the shaped JSON `render()` produced, compact-encoded — the number comparable to ADR 0004's
and ADR 0006's own narrowing figures. **whole tool result** is `content` (the SDK's own indented
plain-text mirror of the same JSON) plus `structuredContent` together — what a `tools/call` response
actually contains over the wire, and a real cost this measurement found that ADR 0006 never priced:
the SDK sends the answer twice, once shaped and once again as an indented string for a text-only
host.

`list_notes` — complete vs `fields=["ref", "title", "path"]` (`NOTE_LIST_COLUMNS`, the same three
columns a `human` render already shows by default):

| what | bytes | tokens (`o200k_base`) |
|---|---|---|
| structuredContent only | 31,347 → 4,155 (−86.7%) | 7,701 → 1,156 (−85.0%) |
| whole tool result | 67,174 → 10,420 (−84.5%) | 17,231 → 3,098 (−82.0%) |

**Kaya's own number lands within a point of pandan's borrowed 84%** — 85.0% on the structured
payload, 82.0% on the whole tool result once the SDK's indented text mirror is counted too. That
second figure is the honest one for "what a host actually holds resident per call", and it is a few
points lower than the first for a reason worth stating rather than rounding away: the text mirror
carries the same fixed pretty-printing overhead whether the payload is narrow or complete, so it is
proportionally larger against the narrow one — narrowing looks slightly less dramatic once that
mirror is counted.

`get_note` on the corpus's longest body (`NOTE-17`, 2,221 chars) — `KAYA_MAX_TEXT_CHARS=0` (what
`kaya note get --full` sets, and the only way to reach that state through an MCP call, since there
is no `--full` argument on the tool itself) vs the default `KAYA_MAX_TEXT_CHARS=500`, full-side
first so the prose order matches the table's before → after order (truncation only removes text, so
the untruncated side is always the larger one):

| what | bytes | tokens (`o200k_base`) |
|---|---|---|
| structuredContent only | 2,458 → 790 (−67.9%) | 504 → 193 (−61.7%) |
| whole tool result | 5,038 → 1,688 (−66.5%) | 1,069 → 432 (−59.6%) |

`list_notes` is the representative read — it is where narrowing, truncation and the aggregate all
apply at once, and it is pandan's own comparison point. `get_note` is the complementary second point
specifically because the aggregate does not apply to one record, so what it isolates is truncation
alone, still a ~60% saving on a single long document at the default limit.

Two guards, both adopted from pandan's implementation rather than rediscovered, and both with the
positive control that keeps them from being vacuous:

- **A nullable enum is not collapsed**, because `enum` constrains the whole value and the collapsed
  form therefore **rejects `null`** — asserted against a real JSON Schema validator rather than
  quoted. It falls out of an allow-list of sibling keys provably inert for `null`, so `const`, `$ref`
  and the in-place applicators are refused by the same line with nothing written for them. **Kaya
  has no nullable enum on any of its six tools**, and the test says so out loud: the guard is
  asserted over a *constructed* probe tool driven through the real SDK, and a separate test reddens
  the day a real one arrives so the guard can graduate from constructed to live.
- **A `title` argument survives.** Pandan's first pass recursed on the key's spelling and deleted the
  argument from two tools. Kaya has the collision for real — `create_note(title, …)` and
  `edit_note(ref, title=None, …)` — so the traversal is driven by JSON Schema keywords: inside
  `properties` (or `$defs`, or `patternProperties`) a key is a *name* and is never inspected, and
  `title` is stripped only at a schema position, where it is an annotation. A third case comes free
  from the same rule: `default`, `const`, `enum` and `examples` hold arbitrary JSON, so a blind walk
  edits a caller's *data* there.

The word "generated" in "strip generated `title` keys" is checked rather than assumed: nothing in
this package authors a title, and a test rebuilds each stripped annotation from the name pydantic
generated it from, so a card that starts writing `Field(title=…)` reddens instead of losing it.

## Watch for: a new tool needs a restart; a new field doesn't

Because the tools pass JSON straight through `render()`, a new **field** the API starts returning
shows up in a tool's response immediately, with no change on this side. A new **tool**, by contrast,
is a registration this process makes once at import time — it isn't callable by an MCP host until
the host restarts the server subprocess. If a "the tool doesn't exist" report ever shows up right
after a tool was added, check whether the host picked up the new process before chasing anything
else (ADR 0006 §Consequences).

## Commands

```bash
uv sync --all-extras
uv run pytest -q
uv run ruff check .
```

Verified against this package as of this README: 92 tests pass, ruff is clean.
