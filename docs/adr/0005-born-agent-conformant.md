# ADR 0005 — The machine-facing contract is designed in from the first CLI slice, and the output layer's signature lands before behaviour goes inside it

- **Status:** Accepted
- **Date:** 2026-08-01
- **Deciders:** Jian (inherited conclusions, made binding)
- **Context source:** pandan Milestone 7 slices V42–V48 and V50, and the corrections recorded in each.

## Context

Pandan spent Milestone 7 retrofitting agent ergonomics onto a CLI that already existed. Seven slices:
`--fields` projection (V42), structured errors with a documented exit-code scheme (V43), pre-computed
aggregates on every list verb (V44), content truncation with true totals and `--full` (V45),
content-first bare invocation plus `help[]` next-step templates (V46), `--format {human,json,toon}` over
one serializer (V47), and ambient session context (V48).

Retrofitting is what made them expensive, and the slice records say so. V44 had to update ~40 pre-existing
assertions. V45 needed only 2, and the record notes that as *"the slice's first promise working"* — the
promise being that under-limit output stays byte-identical. Kaya can have V45's cheapness on every slice by
starting from the finished shape.

Two lessons from those records matter more than the feature list:

**The sequencing lesson.** V47 changed the output layer's *signature* — it introduced
`_structured_payload` / `_render_structured` as the one shaping-and-serializing seam. V44 and V45 then
landed "on V47's seams unmoved", which is why they were cheap. Had they landed first, each would have
been rewritten by V47. **The slice that changes the output layer's signature must come before the slices
that add behaviour inside it.**

**Errors are part of the contract.** V43's record notes it "defines the error shape the rest of Wave 2
emits, so it lands before V44–V47". An error is an output, and an output layer that only shapes successes
is half a contract.

## Decision

**Kaya's CLI is born with the finished contract, and the slice order enforces the sequencing lesson.**

### The contract

| # | Guarantee | Note |
|---|---|---|
| 1 | `--format {human,json,toon}` over **one** serializer in `kaya-client` (ADR 0004), so formats cannot drift | `--json` is a documented alias for `--format json`; `--format` wins if both are given |
| 2 | `--fields a,b,c` selects named columns on every list verb; vocabulary derived from the payload's own keys; an unknown name is a clean error naming it | **Omitting** it leaves structured output complete; supplying it narrows every format alike, which under `human` is the widening this row used to describe. Wording corrected by the 2026-08-09 (KAN-546) amendment below. A usage error on single-entity verbs, never a silent no-op |
| 3 | Errors **structured on stdout**: `error<TAB><code><TAB><message><TAB><arg>`, or an `{"error": {...}}` object under a structured format, with all keys always present | Human `usage:` text still goes to stderr |
| 4 | Exit codes: `0` ok · `1` runtime · `2` usage — the caller's input was rejected, by argparse or by the API (`400`) · `3` 401 · `4` 403 · `5` 404 | **Pandan's scheme, adopted verbatim.** Branch on the stable `code` string, never on message text. `2`'s wording widened by the 2026-08-09 amendment below; no number moved |
| 5 | A pre-computed `summary` on every list verb, describing **the returned set** — under a filter or `--limit`, the returned set, not the whole corpus | A trailing line for humans, a `summary` object for structured consumers, both from the same dict. **What is in it** was left open here and settled by the 2026-08-09 (KAN-548) amendment below: one key, `count`. A single entity gets none |
| 6 | Text truncated by default with a **true** total and `--full` to opt out; an allow-list of prose fields, never "any long string" | A truncated value stays a string: no key added, removed or retyped. **Where** the total is written was left open here, and settled by the 2026-08-09 (KAN-547) amendment below: in-band, inside the string, so it reaches the structured formats too. The multi-byte guarantee is code points |
| 7 | Bare `kaya` prints live state and exits `0`; `--help` still prints usage | No token → a structured auth error, not a stack trace. **How much** state was left open here, and settled by the 2026-08-09 (KAN-549) amendment below: the five most recent notes, sliced in `kaya-client` |
| 8 | Results carry `help[]` next-step **templates** with placeholders left unfilled | Every hint must parse as a real command, pinned by a test |
| 9 | No verb prompts when stdin isn't a tty | A structured failure instead of a hang |

Three of pandan's specific corrections are adopted as rules rather than rediscovered:

- **The truncation allow-list is named prose fields**, not a length heuristic. A blanket rule eventually
  cuts a `next_cursor` and silently breaks pagination, or mangles a URL.
- **`summary` is attached after truncation**, so its counts are structurally out of the truncator's reach.
- **Every `help[]` template must parse.** Pandan's spec shipped `pandan comment add <id> "…"`, which is
  not a valid command (the body needs `--body`), and the wrong form propagated into a card. The guard is a
  test that parses every emitted hint.

### The sequencing rule, made structural

Kaya's CLI arrives in **two slices, in this order**:

- **V2a — the signature.** The `render` seam in `kaya-client`, `--format`, the error shape, the exit-code
  table, and build-stamped `--version` (ADR 0007). A deliberately minimal verb set (`note list`,
  `note get`) so the slice is about the *layer*, not the breadth.
- **V2b — the behaviour inside it.** `--fields`, aggregates, truncation, content-first, `help[]`, and the
  full verb set — all landing on V2a's seam unmoved.

That split is the sequencing lesson expressed as slice boundaries rather than as advice. V2a's own
acceptance criteria include a byte-identity pin on the default human row, so V2b can prove it changed
nothing it didn't mean to.

**Exit codes are a published contract from V2a.** Do not renumber them later.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Ship a simple CLI first, add ergonomics when needed | The experiment has been run. It cost pandan seven slices, ~40 rewritten assertions in one of them, and left the MCP adapter permanently behind. |
| One big "AXI-conformant CLI" slice | Violates small-and-reversible, and collapses the very sequencing distinction that makes the parts cheap. |
| Invent a cleaner exit-code scheme for a greenfield CLI | The scheme is fine and *sameness across the suite* is worth more than marginal elegance. An operator scripting both tools should never have to remember which is which. |
| Skip `toon`, since pandan measured it as a win only on uniform rows | Correct that it doesn't always pay (`get` was +2% vs compact JSON), but the flag is nearly free once one serializer exists, and note *lists* are exactly the uniform-row case where it wins. Measure and record per payload, as V47 did. |

## Consequences

- **Positive:** every later slice emits through a finished layer, so adding a verb is adding a verb.
  Under-limit output stays byte-identical by construction, which is what kept V45's test churn to two
  assertions. Suite-wide consistency: an operator or agent fluent in `pandan`'s output is fluent in
  `kaya`'s.
- **Neutral:** V2a and V2b together are more up-front work than a naive CLI, spent before there is much to
  list. That is the point, and it is cheaper here than the same work later.
- **Negative / deferred:** the contract is frozen early, so a genuine improvement to the exit-code scheme
  or the error shape is a breaking change from V2a onward. Accepted: a stable machine contract is worth
  more than the improvement, which is exactly why pandan's V43 says "do not renumber them".
- **Ambient session context** (pandan V48) is **not** in the MVP. It's real value, but it depends on
  having enough notes for ambient state to be worth injecting. Post-MVP.

## Amendment (2026-08-09, KAN-718): `2` is the caller's input being rejected, wherever it was caught

§contract 4's table above described `2` as "usage (argparse rejected argv)", naming the *layer that
noticed* rather than the meaning. It had no row for a `400` at all, so KAN-542's deliberate
unmapped-default sent one to `1`. Observed against a real backend during V2a's demo:

```
kaya note get NOTE-9999   -> exit 5, error<TAB>note_not_found<TAB>no such note<TAB>
kaya note get '#NOTE-12'  -> exit 1, error<TAB>invalid_note_ref<TAB>not a note reference…<TAB>#NOTE-12
```

**Why it matters more than a tidier label.** [ADR 0008](0008-note-identity.md) makes `#NOTE-12` a
`400` *by design*: the central ref resolver refuses a malformed identifier rather than answering
`404` about a string that is not a note reference at all, because "a typo indistinguishable from a
genuine miss" is the exact failure that ADR exists to prevent. A `400` is therefore a **designed
outcome of every ref-taking verb**, met routinely rather than exceptionally — and exit `1` reports
it as a runtime failure, i.e. as something that went wrong on kaya's side. That is wrong twice over:
it hides the caller's own mistake, and a script branching on exit codes would plausibly *retry* a
failure it can never succeed at. Under `2` it re-reads what it typed, which is the correct action.

**What changed.** `400 → 2` is a row added to `EXIT_FOR_STATUS` in `kaya-cli/src/kaya_cli/failures.py`,
and `2`'s wording in the table above now reads *the caller's input was rejected — by argparse, or by
the API*. Both halves of §contract 4's rule survive intact:

- **It is an addition, not a renumber.** No shipped number moved; `0/1/2/3/4/5` mean what they meant
  in V2a, and the "do not renumber them" rule below is about numbers moving, not meanings arriving.
  `tests/test_exit_codes.py` pins each row by literal value and checks the tables as *supersets*
  precisely so that adding a row reddens nothing while moving one reddens exactly what moved.
- **The refusal is keyed on its status, not on the code string.** `invalid_note_ref` is deliberately
  *not* a row in `EXIT_FOR_CODE`. The backend's code vocabulary grows without the client's
  knowledge, so the next `400` code — a malformed cursor, a rejected path — must exit `2` without
  anybody remembering to add it, which is the same reasoning that made `401`/`403`/`404`
  status-keyed in the first place.
- **The unmapped default stays `1`.** Only `400` moved, because only `400` is definitionally the
  caller's input being rejected. Defaulting an unknown status to `2` would send a caller to re-read
  the manual over a server-side `422`, which is the argument KAN-542 made and this amendment does
  not disturb.

The scheme was adopted from pandan verbatim so an operator scripting both tools never has to
remember which is which, and that is why the fix had to be an addition. Widening what `2` covers
keeps the two tools reading the same: `2` still means "you sent something wrong", so a pandan user's
model of a kaya `2` is correct without being told. Inventing a seventh number for "the API rejected
your input" would have been the version of this change that broke the sameness the scheme was
adopted for.

## Amendment (2026-08-09, KAN-546): `--fields` narrows every format, and it is *omitting* it that keeps structured output complete

§contract 2's table above said `--fields` "widens the human row" and "does not affect structured
output, which is already complete". Those are two descriptions of two different operations, and
`kaya-client/src/kaya_client/projection.py` flagged the contradiction in V2a rather than guessing at
it, because V2a builds the seam and V2b fills it. This is V2b filling it.

**The decision: `--fields` narrows the shaped dict uniformly, for every format.** `fields` names a
subset of the record's own keys; `columns` becomes that subset in the order the caller gave, and
`records` narrow to it. Under `human` that *widens* the visible row, because the default row
(`ref`/`title`/`path`) is deliberately narrower than the record — so §contract 2's original word is
satisfied by the same operation that satisfies [ADR 0004](0004-shaping-lives-in-the-shared-client.md)'s.
Under `json`, `toon` and `data` the payload carries exactly the named keys.

**What contract 2 was actually protecting, restated so it still holds.** A caller who did **not**
ask for projection gets a complete record — one it can feed straight back to the API's own contract.
That is now true by construction rather than by a rule about formats: `fields=None` returns the very
same payload object, and `kaya-client/tests/test_human_row_is_pinned.py` is the byte-level witness.
What the original wording got wrong is the case where the caller *did* ask. Structured output being
"already complete" is an argument for leaving it alone by default, not for ignoring an explicit
request; a `--format json` that silently declined to project would make `--fields` mean two
different things depending on a flag the caller set for an unrelated reason.

**Why not make it conditional on `fmt`.** It is reachable — `fmt` is in scope on the same call — and
it is exactly the wrong shape. The CLI's `--fields` and the MCP server's `fields` are one parameter
through one seam ([ADR 0004](0004-shaping-lives-in-the-shared-client.md)); a projection that
depended on the format would put a behavioural difference between the two adapters *inside* the step
they share, which is the drift that ADR exists to prevent. It would also strand the MCP surface:
`data` is the format V6 returns as `structuredContent`, so "projection does not affect structured
output" read literally means the adapter ADR 0004 was written for is the one that gets none of it.

**Measured here rather than cited from pandan.** ADR 0004's case rests on a 44,902-token
`list_cards` read falling to 7,204 — pandan's board, not kaya's notes. Re-measured on kaya's own
corpus through the shipped `render` (40 notes, mean body 266 chars, `o200k_base`, via
`kaya-client/scripts/measure_toon_delta.py`):

| `note list`, 40 notes | compact JSON | vs complete | toon | vs complete |
|---|---:|---:|---:|---:|
| complete records (7 keys) | 5,226 | — | 4,637 | — |
| `--fields ref,title,path` | 1,072 | −79.5% | 866 | −81.3% |
| `--fields ref,title` | 548 | −89.5% | 429 | −90.7% |
| `--fields ref` | 245 | −95.3% | 206 | −95.6% |

ADR 0004 predicted "~84%" from field breadth alone. On kaya's shape the default row recovers 79.5%
and a two-column read 89.5%, so the prediction carries. The saving stacks with `toon` rather than
competing with it: the two together take a `note list` from 5,226 tokens to 429.

**Nothing is withdrawn from a user by this.** `--fields` had never shipped — V2a published
`--format`, `--json` and the exit table, and this ADR's own §Negative consequence about a frozen
contract is about promises already made. There is no invocation whose output changes, which is why
this is an amendment and not a breaking change, and why it could be settled by the slice that
implements it rather than by a new ADR. The 2026-08-09 (KAN-718) amendment above is the precedent
for the form: correct the wording where it named the wrong thing, keep the guarantee it was reaching
for, and do not re-litigate an accepted decision.

## Amendment (2026-08-09, KAN-547): the truncation hint is **in-band**, and the guarantee is code points

§contract 6 asks for two things in one row — a **true** total, and "a truncated value stays a
string: no key added, removed or retyped" — and says nothing about where the total is written down.
`kaya-client/src/kaya_client/truncation.py` recorded that gap in V2a rather than guessing at it,
because V2a builds the seam and V2b fills it. This is V2b filling it.

**The decision: the hint is appended to the truncated string itself.** A cut `body` is the first
`text_limit` characters, a blank line, then
`(truncated, 2847 chars total — use --full to see complete body)`. No key is added, the value is
still a `str`, and the total therefore reaches `json`, `toon` and `data` as well as `human`.

**Why the alternative does not survive contract 6 read as a whole.** The obvious other design is a
human-only hint, with structured output carrying a silently shortened string. Truncation is step 2
of [ADR 0004](0004-shaping-lives-in-the-shared-client.md)'s ordering and serialization is step 4, so
by the time `human` could print a hint the original length no longer exists. The only two ways to
carry it that far are a second key — which the same sentence of contract 6 forbids — or truncating
inside the serializer, which is ADR 0004's rule broken and would put a shaping decision in the one
step that branches on format. In-band is what is left once both are excluded, and it is also the
only reading under which the promise is kept to the consumer who needs it: under a human-only hint
an agent on `--format json` cannot distinguish a 500-character note from a truncated 3,000-character
one, so "a true total" would be a promise kept only to the audience who could have counted.

The sibling tool already does this. `pandan get KAN-716` prints
`… (truncated, 1940 chars total — use --full to see complete body)` inside the description text, and
pandan's V45 is the slice this contract row was derived from.

**What it costs, stated rather than hidden.** A consumer that wants the prose alone gets the hint
with it. The answer is `--full`, which is the flag contract 6 pairs with the total in the first
place, and `KAYA_MAX_TEXT_CHARS=0` for a deployment that always wants whole notes.

**The multi-byte guarantee is code points, not grapheme clusters.** SLICES §V2b's unit line says
"truncation never splits a multi-byte character", and that is what is implemented and tested: `str`
slicing is by code point, so no cut can produce a lone surrogate, a broken UTF-8 sequence or a
replacement character, and `text_limit` and the total are the same unit. A cut *can* fall inside a
grapheme cluster — between a letter and its combining accent, inside a ZWJ emoji sequence, between a
base emoji and its skin-tone modifier — and `kaya-client/tests/test_truncation.py` demonstrates that
rather than hiding it. Closing that gap needs a UAX #29 segmentation table, i.e. a dependency, and
SLICES §V2a fixes `kaya-client` at exactly one runtime dependency. Claiming clusters while
implementing code points would be the "full parity" mistake in miniature, so the narrower claim is
the one made.

**`--full` and `KAYA_MAX_TEXT_CHARS=0` are one state with one spelling.** `render` gained no
`full=True`; `--full` resolves to `text_limit=0` in `kaya_cli.parsing.resolve_text_limit`, whose
entire content is that the flag outranks the environment. The number itself is
`kaya_client.config.max_text_chars`, so V6's MCP server started from the same shell truncates to the
same length without importing an adapter. **`render`'s signature did not move**, which is the third
consecutive V2b card for which that is true.

**Measured on kaya's own corpus** (40 notes, `o200k_base`, through the shipped `render`, via
`kaya-client/scripts/measure_toon_delta.py`), against `--full` as the baseline because that is what
a read cost before this card:

| `note list`, 40 notes, complete records | compact JSON | vs `--full` | toon | vs `--full` | `note get` JSON | vs `--full` |
|---|---:|---:|---:|---:|---:|---:|
| mean body 1,351 chars, default `500` | 7,298 | −41.7% | 6,672 | −44.1% | 182 | −49.7% |
| mean body 1,351 chars, `200` | 5,237 | −58.1% | 4,611 | −61.3% | 132 | −63.5% |
| mean body 3,495 chars, default `500` | 7,329 | −72.8% | 6,703 | −74.6% | 183 | −80.0% |

**And the honest counter-result: on a corpus of short notes the default costs a little rather than
saving.** At a mean body of 266 characters *no* note exceeds 500, so the default is a byte-identical
no-op; forcing the limit down to 200 makes a `note list` **+1.0%** larger in JSON, because the hint
has a fixed cost of roughly twenty tokens and cutting a 266-character body to 200 recovers fewer
than that. That is the correct behaviour rather than a defect — the hint is what makes the total
true — but it is why truncation is a saving on *documents* and not on one-line notes, and it is the
kind of number ADR 0004's "measure, don't assert" rule exists to surface.

**Nothing is withdrawn from a user.** Truncation had never shipped; V2a published `--format`,
`--json` and the exit table, and this ADR's §Negative consequence about a frozen contract is about
promises already made. The precedent for the form is the two amendments above: correct or complete
the wording where it under-specified something, keep the guarantee it was reaching for, and do not
re-litigate an accepted decision.

## Amendment (2026-08-09, KAN-548): the summary is **one key**, and the zero state is a sentence

§contract 5 asks for "a pre-computed `summary` … describing the returned set" and says nothing
about what is in it. `kaya-client/src/kaya_client/aggregates.py` recorded that gap in V2a rather
than guessing at it, because V2a builds the seam and V2b fills it. This is V2b filling it, and it is
the third V2b card in a row for which **`render`'s signature did not move**.

**The decision: `{"count": n}`, and nothing else.** `n` is `len(payload.records)` — the rows the
call actually returned. Under `human` it renders as a footer, `2 notes`, after a blank line; under
`json`, `toon` and `data` it is a `summary` key beside the API's envelope, never inside a record.

**Why one key rather than a useful-looking handful.** This layer exists because payload breadth is
what makes an agent read expensive (ADR 0004's 44,902 tokens), and a key here is paid on *every*
list read by every consumer, forever — the opposite of a `--fields` narrowing, which the caller
opts into. So a key has to answer "what does a caller *do* with it?", and only the count does: it
is how a reader knows whether the rows in front of it are all of them, which is the question a
filter or a `--limit` creates and the reason this row says "the returned set". The candidates
considered and rejected — a date range over `updated_at`, a breakdown by `path` — are derivable
from records the caller already has and change no decision. Measured: on a narrow read the
summary is already **+2.4%** in JSON (table below); a five-key summary would spend more than the
projection two cards ago saved.

**"The returned set, not the corpus" is true by construction, not by care.** `attach_summary` takes
exactly one parameter and it is the payload. There is no corpus in scope, no total to pass in and
nowhere for one to arrive from, so the wrong answer is not reachable from inside the function —
producing it would mean widening a signature, which is a visible thing to do in review.
`kaya-client/tests/test_aggregates.py` asserts the arity for that reason, alongside the data
assertion that a payload built from a slice of a forty-note corpus counts the slice.

**An empty result keeps its sentence and gains no footer.** `no notes` *is* the rendering of
`count: 0` — SLICES §V2b's "definitive zero state rather than nothing" — and a `0 notes` line under
it would be the same fact twice in two spellings, one of which a reader eventually takes as
contradicting the other. The structured formats still carry `{"count": 0}`, because an object has
no room for a sentence and a *missing* `summary` key is ambiguous: a consumer could not tell an
empty result from a kaya that predates aggregates.

**A single entity gets no summary at all.** A summary describes a returned *set*, and one note is
not a set of anything; `count: 1` on every `note get` ever made is tokens spent to say nothing.
`test_human_row_is_pinned.py`'s `SINGLE_NOTE` is the byte-level witness and is **unchanged** by
this card.

**The one pin this card was allowed to redden, and what moved in it.** V2a wrote into
`kaya-client/tests/test_human_row_is_pinned.py` that a later slice reddening it while `--fields`
was omitted would be "the guard working, not a stale test to update". That sentence did its job
twice — KAN-546 and KAN-547 both landed with the file untouched and green, which was their evidence
— and contract 5 is what finally required a change. Every **collection** literal gained
`\n\n<count> <noun>`; nothing inside a table moved (columns, the two-space gap, widths from the
returned rows, no header, no trailing whitespace, all still asserted byte-for-byte);
`SINGLE_NOTE` and the `no notes` zero state did not change. The file now carries that record in its
docstring, because a pin quietly edited is a pin destroyed.

**The footer is separated by a blank line**, not by a single newline, so that it is a block rather
than a third row: `2 notes` on the line directly under a two-row table is a row to anything that
split on newlines, and the consumer most likely to do that is the agent this layer exists for. It
is the same device `serialization._entity` already uses for a note's prose and `truncation` for its
hint.

**Measured on kaya's own corpus** (40 notes, `o200k_base`, through the shipped `render`, via
`kaya-client/scripts/measure_toon_delta.py`), against the same render with no summary attached —
which is literally what a read cost before this card:

| `note list`, 40 notes | JSON without `summary` | with | cost | toon without | with | cost |
|---|---:|---:|---:|---:|---:|---:|
| complete records (7 keys) | 5,226 | 5,232 | **+0.1%** | 4,637 | 4,644 | **+0.2%** |
| `--fields ref,title,path` | 1,072 | 1,078 | +0.6% | 866 | 874 | +0.9% |
| `--fields ref,title` | 548 | 554 | +1.1% | 429 | 437 | +1.9% |
| `--fields ref` | 245 | 251 | **+2.4%** | 206 | 214 | **+3.9%** |

Six tokens in JSON, seven or eight in TOON, flat regardless of corpus size — so the *percentage*
is entirely a statement about what it is being added to. On the read ADR 0004 was written about it
rounds to nothing; on the narrowest possible projection it is 2.4%, which is the honest number and
the reason the key count is one. TOON pays slightly more because a keyed block costs a line where
JSON costs a brace, which is the same shape as its measured `note get` loss.

**Nothing is withdrawn from a user.** Aggregates had never shipped; V2a published `--format`,
`--json` and the exit table, and this ADR's §Negative consequence about a frozen contract is about
promises already made. The precedent for the form is the three amendments above: complete the
wording where it under-specified something, keep the guarantee it was reaching for, and do not
re-litigate an accepted decision.

## Amendment (2026-08-09, KAN-549): "live state" is the **five** most recent notes, and the banner is not a rendering

§contract 7 says "bare `kaya` prints live state and exits `0`" and SLICES §V2b spells that as "the
executable path, a one-line description, recent notes and the aggregate". Two words in that were
under-specified, and `kaya-cli/src/kaya_cli/__main__.py` recorded the gap in V2a rather than
guessing at it. This is V2b filling it, and it is the sixth and last V2b card for which **`render`'s
signature did not move**.

**The decision: `recent` is five, and the number is `kaya_client.client.RECENT_NOTES`.** A bare
invocation shows the five most recently updated notes the caller owns, in the API's own order, with
ADR 0005 §contract 5's footer over *those five*.

**Why a number at all, and why five.** `list_notes()` returns every note the caller owns — there is
no `?limit=` on `GET /api/v1/notes` and paging is deferred — so "recent notes" without a limit is
the whole corpus, and a bare invocation that prints four hundred rows is not content-first, it is a
wall. Five is what makes the whole invocation one screen (three banner lines, five rows, a footer
and two `help:` lines is 13 lines, inside a 24-line default with the command still visible), and it
is measured at **174 `human` tokens against 893** for the same invocation unsliced — the first call
an agent makes, and the one most likely to be made speculatively, so the read whose cost matters
most. Ten costs 284, **+63%** for five rows nobody asked for.

**Where the slice lives, which is the part with a rule behind it.** A slice is a shaping decision —
it changes what a consumer is shown and therefore what a read costs — so
[ADR 0004](0004-shaping-lives-in-the-shared-client.md) puts it in `kaya-client`. It is
`Payload.limited_to()`, the rows-wise twin of `narrowed_to`, applied at the *call* by
`KayaClient.recent_notes()`. The obvious alternative, `payload.records[:5]` in `kaya_cli`, is a
projection rule in the one package ADR 0004 forbids one in, and V6's MCP server would inherit none
of it. The alternative that ADR 0005 forbids — a `limit` parameter on `render` — is the stop signal
rather than a step.

**And the property that falls out of that placement rather than being arranged.** §contract 5
requires the summary to describe "the returned set — under a filter or `--limit`, the returned set,
not the whole corpus". `aggregates.attach_summary` counts the records it is handed and takes exactly
one parameter, and the slice happened before it was handed anything, so a bare `kaya` over forty
notes reports `5 notes` with **no rule added to `aggregates` at all**. Nothing in that module learned
what a limit is. `kaya-client/tests/test_overview.py` asserts it end to end, where
`test_aggregates.py` already asserted it structurally.

**The banner is not a rendering, and the guard is a signature.** `kaya_client.overview.overview()`
takes three `str`s — program, version, executable path — and **no `Payload`**. It therefore *cannot*
format a result, which is what keeps "`render` is called in exactly one place in `kaya-cli`" a
checkable claim rather than a habit; `kaya-cli/tests/test_bare_invocation.py` counts the call sites
over the package's AST. It takes the same door `provenance.version_line` already takes, for the
reason that module's docstring gives: shaping lives in `kaya-client`, and it does not all live in
one function. The three lines are joined to `render`'s output by `serialization.BLOCK_GAP` on one
`print`, which is the same separator every other trailing block already uses.

**The third banner line is static, and that is the interesting restraint.** The reader has to be
told a slice happened, or `5 notes` under five rows reads as "you have five notes". The honest-looking
answer is "showing 5 of 42" — and the total is *right there*, since `list_notes` fetched all forty-two.
It is not printed, because a banner that derived a number from the payload would be a second thing in
the process shaping output from a payload, and the second one is always where a projection rule
eventually lands. So the line names the limit and the verb that lifts it (`kaya note list`), the
footer stays contract 5's returned set, and the caller who wants forty-two types one command and gets
it from the one seam. This is the same trade §contract 8 makes for `help[]` templates: advice about
the tool is static, facts about the result are in-band.

**A bare invocation has no `--format`, and that is deliberate.** The top-level parser carries no
output flags — they live on the verbs — so `kaya --format json` is a usage error, unchanged from
V2a. A banner is prose: under a structured format it would have to be either invalid JSON in front
of a document or a key inside one, and `kaya note list --format json` already answers the question
that reaches for. The banner is therefore `human`'s alone by construction rather than by a
suppression rule.

**What is withdrawn from a user, stated plainly.** Bare `kaya` used to exit `0` on any machine,
printing a banner and the epilogue. It now opens a session, so **with no token it exits `1` and
prints `error<TAB>no_credential<TAB>…` on stdout**. That is contract 7's own note ("no token → a
structured auth error, not a stack trace") arriving rather than a change of mind, and it is why
`kaya-cli` takes a minor bump: a script running `kaya` as a liveness check would now see a non-zero
status, which is the correct answer to "is this kaya usable?" and was not what it was told before.
`--help` and `--version` are untouched and both still answer before anything opens a session, which
is what keeps the two commands a confused user reaches for working on a machine with no credential.
