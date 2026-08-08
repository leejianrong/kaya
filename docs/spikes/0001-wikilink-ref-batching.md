# Spike 0001 — How kaya resolves N card refs

- **Status:** Complete, recommendation below
- **Date:** 2026-08-01
- **Board card:** KAN-560 (board 18)
- **Settles:** the open risk in [`PLAN.md`](../PLAN.md) §Risks, step 1 of V5 in
  [`SLICES.md`](../SLICES.md), and the "resolution fans out" consequence in
  [ADR 0003](../adr/0003-cross-linking-one-way-soft.md)
- **Upstream ask:** <https://github.com/leejianrong/pandan/issues/254> (open, not built)

## The question

Rendering a note's wikilink pills means turning every `[[KAN-n]]` in it into a title and a column.
A spec note with forty refs is forty round trips unless the reads are batched. Three candidates:
wait for pandan's batch endpoint, fan out with a concurrency cap inside kaya, or find something
that already works.

## What pandan's API actually offers

There is no batch read, and there is a second problem underneath it that changes the shape of the
answer.

**No id-set filter.** `list_cards` takes sixteen query parameters and none of them is an id set:
`board_id`, `column`, `epic_id`, `cycle_id`, `updated_since`, `blocked`, `priority`, `label`,
`due_before`, `overdue`, `needs_human`, `assignee`, `q`, `sort`, `limit`, `cursor`
(`backend/app/routers/cards.py:295-316`, confirmed against the live `/openapi.json`). `PATCH
/api/v1/cards/batch` exists (`backend/app/routers/cards.py:648`), so batch *write* has precedent
and batch *read* simply was not built.

**Full text does not do it.** `q` runs `websearch_to_tsquery('english', q)` over the generated
vector, which covers title and description only (`backend/app/routers/cards.py:354-362`). Verified
live: `?q=KAN-48` returns one card and it is not KAN-48. Ticket numbers are not in the vector. `q`
also lands in the `expensive` rate-limit tier at 120/minute (`backend/app/ratelimit.py:63-68,
86-97`), where a plain GET is unclassified, so it is the wrong tool twice over.

**A wikilink does not carry an id.** This is the finding that reframes the options.
`GET /api/v1/cards/{card_id}` is typed `card_id: int` (`backend/app/routers/cards.py:585-587`).
`[[KAN-12]]` carries a `ticket_number`, not a primary key, and **no route anywhere accepts a
ticket ref**. The only `ticket_number`-to-row lookup in the whole backend is
`backend/app/autosync.py:78`, internal to the GitHub webhook handler. Pandan's own CLI resolves a
ticket by paging the entire card list and matching client-side
(`pandan-cli/pandan_cli/cli.py:1667-1697` for cards, `:1700-1716` for epics).

So option 2 as posed does not exist. Kaya cannot make N calls to `GET /cards/{id}` because kaya
does not have the ids, and getting them costs a list sweep. And once you have swept, you are done:
the list item and the single-read response are the **same shape**, verified live at 22 keys with an
empty symmetric difference, `ticket_number`, `title` and `column` among them. The per-id GET after
a sweep would fetch data kaya already holds.

Epics are easier still. `GET /api/v1/epics` takes only `board_id`, with no pagination, so every
`EPIC-n` ref on a board resolves in one request regardless of count.

## What I measured

Live against `https://simple-kanban-jian.fly.dev`, warmed first, 540 cards visible to the PAT
across eight boards, three pages at `limit=200`. Medians, repeat counts in brackets. Network
round trip dominates: `GET /healthz` alone is 389 ms.

| Call | Median | Notes |
|------|--------|-------|
| `GET /healthz` | 389 ms | the floor, pure round trip [^healthz] |
| `GET /cards/{id}` | 776 ms | [n=7] min 530, max 790 |
| 10 sequential card reads | 6,716 ms | [n=5] min 6,217, max 7,043 |
| 10 concurrent, cap 10 | 948 ms | [n=5] min 852, max 1,569 |
| 10 concurrent, cap 5 | 1,641 ms | [n=5] two waves |
| 40 refs, sequential | 26,381 ms | one run |
| 40 refs, cap 8 | 4,128 ms | [n=3] |
| `GET /cards?limit=200` | 1,290-1,728 ms | [n=7 each of two runs] 157 KiB plain, 57 KiB gzipped |
| Full page walk, 540 cards | 4,883 ms | [n=5] 3 requests, min 4,189, max 5,814 |

Twenty refs, wall clock by concurrency cap, three runs each:

| Cap | Wall clock | Per-request median | Per-request p95 | Errors |
|-----|-----------|--------------------|-----------------|--------|
| 1 | 13,350 ms | 666 ms | 881 ms | 0 |
| 2 | 7,107 ms | 758 ms | 804 ms | 0 |
| 4 | 3,976 ms | 782 ms | 949 ms | 0 |
| 8 | 2,403 ms | 817 ms | 940 ms | 0 |
| 16 | 1,654 ms | 870 ms | 1,127 ms | 0 |

Pandan absorbs twenty in flight without shedding and with only mild per-request degradation. That
is the honest case for the fan-out, and it is worth stating plainly before the case against it.

[^healthz]: Noted while re-using this row as a baseline in KAN-539: pandan has no JSON health
    endpoint. `/healthz`, `/health` and `/api/v1/health` all answer `200 text/html` with the SPA's
    `index.html`, so this row is a proxy-plus-static-file round trip. That is still the right floor
    — same proxy, same app, no database and no auth — but it is not what the path name suggests.

`updated_since` works but is not selective on this data: every window from one hour to thirty days
returns a full 200-card page, so an incremental sweep saves nothing here today.

## The options and what each costs

### 1. Wait for issue 254

Right shape, one request, a documented cap and a stated policy on missing ids. Not built. Waiting
blocks V5 behind a second pandan release, having already spent one on `GET /me`. The resolver
written for option 3 swaps its sweep for one `?refs=` call when this lands, without touching the
cache, the deadline or the degradation path, so waiting buys nothing that cannot be retrofitted in
an afternoon.

### 2. Bounded concurrent fetch in kaya

It cannot be built as specified: there are no ids to fetch by, so it is a sweep *plus* N redundant
requests. Suppose the ids problem were solved anyway. Then:

**In kaya it is a thread pool, and the pool is not the expensive part.** [ADR
0001](../adr/0001-stack-inherited-from-pandan.md) commits kaya to 100% synchronous SQLAlchemy, one
engine, one pool, and explicitly forecloses an async engine. A concurrent fetch from a sync `def`
route is a `ThreadPoolExecutor`, and that route is already occupying one of Starlette's forty
default worker threads. Threads are cheap. The connection is not: the route holds a Postgres
session from `Depends(get_db)` for the entire request, so blocking on pandan holds a kaya database
connection for the entire fan-out while doing no database work. Ten concurrent renders against a
slow pandan exhaust a 5+5 pool and take down note *saving*, which is precisely the coupling ADR
0003 forbids. The failure is in kaya, self-inflicted, and it is a resource exhaustion rather than a
timeout, so it does not degrade gracefully.

**In pandan it is the whole machine.** `fly.toml:30-33` sets `soft_limit = 20` and `hard_limit =
40` on a single 256 MB `shared-cpu-1x` box with `min_machines_running = 0` (`fly.toml:16, 35-37`),
sized against a database pool of ten. One render of a forty-ref note at full concurrency is the
machine's hard ceiling. Two concurrent renders and pandan returns 503s to everyone. The board would
go down because somebody opened a spec note.

**Slow is worse than down.** With pandan down, a fan-out fails fast on connection refused. With
pandan slow, every request in the fan-out sits on a thread and a connection for the full timeout,
and the fan-out multiplies in-flight requests against exactly the resource that is already
saturated. Concurrency is the wrong response to a slow upstream.

### 3. Sweep the list once per batch, answer every ref from it

Page-walk `GET /api/v1/cards?limit=200` with the caller's PAT and gzip, one request in flight at a
time, populate the resolution cache with every card the caller can see, then answer all N refs from
the cache. Requests scale with **board size**, not with ref count: three requests and 4.9 s for 540
cards, whether the note has one ref or forty. Unclassified for rate limiting. 57 KiB per page on
the wire. Sequential, so it holds one connection and one thread, and a slow pandan costs at most
three timeouts before the note renders unresolved.

The one number that cuts against it: at 540 cards a cold sweep is 4.9 s, while a cap-8 fan-out of
twenty refs is 2.4 s. On cold-cache wall clock alone the fan-out wins up to about forty-five refs
on a board this size, where the two cross (measured: forty refs at cap 8 is 4.1 s). It loses on
every other axis, and it loses the wall-clock axis too once the sweep it depends on is counted.

## Recommendation

**Kaya resolves refs with a single bounded list sweep per resolution batch, cached. No fan-out, no
thread pool, and V5 does not wait for issue 254.**

The mechanism:

- The resolver holds a `ticket_number` to `(id, title, column)` cache with its own TTL, separate
  from the auth cache, as ADR 0003 already requires. A stale column is cosmetic, so the TTL is
  generous, measured in minutes.
- A batch containing any uncached ref triggers one page walk with the caller's PAT, requesting
  gzip, one request in flight. Every card the walk returns is cached, not only the referenced ones.
- Refs still unresolved after the walk render as unresolved wikilinks with a hint. So do all of
  them if the walk hits its deadline.
- A per-request timeout of about 3 s and a total walk deadline of about 8 s, sized off the measured
  1.5 s page and 4.9 s cold walk so there is headroom without being generous. A page cap of five as
  well, so a large board degrades to partially resolved rather than to a long sweep. Eight seconds
  is tolerable here only because the pill is a separate request from the note body, and only on a
  cold cache.
- No `ThreadPoolExecutor`, no `httpx.AsyncClient`, no async engine. ADR 0001 holds unchanged.

Three things make this the right answer rather than merely the available one.

**The cache multiplies differently.** A per-ref design fills one cache entry per request. A sweep
fills 200 per request. A forty-ref note on a cold cache costs three requests, and every other note
referencing any card on those boards is then free until the TTL expires. That is the difference
between a fan-out amortised over one note and one amortised over the whole workspace, and it is the
part most easily missed when comparing the two on a single cold render.

**The pill is already a second request.** PLAN's affordance table wires the wikilink pill to `GET
/api/v1/notes/{ref}/links`, separate from the note body. The body never waits for resolution at
all, so ADR 0003's line holds structurally and the resolver only needs a short deadline and an
unresolved fallback, not a fast one.

**It is issue 254's shape already.** One upstream call per render batch, a cache, a deadline, an
unresolved fallback. When 254 lands the sweep becomes `?refs=KAN-12,KAN-45` and nothing else moves.

V5's integration guard should assert requests scale with pages rather than refs: a forty-ref note
issues at most three upstream requests, and a second render of it issues none.

## What would change the answer

- **Issue 254 ships.** Swap the sweep for one call. Everything else stands.
- **The board grows past a few thousand cards.** The sweep stops being bounded and waiting for 254
  becomes correct. The five-page cap turns that from an outage into visible partial resolution, and
  hitting it regularly is the signal to revisit.
- **The resolution TTL has to drop to seconds.** The sweep amortises less and the gap narrows. ADR
  0003 already argues a stale card title is cosmetic, and that argument is what makes a generous
  TTL defensible.
- **Pandan gets more than one machine, or a bigger one.** `hard_limit = 40` on a single instance is
  half the case against the fan-out. The kaya-side connection-holding argument is the other half
  and does not move.
