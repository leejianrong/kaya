<!--
title: "Linked but not merged: how kaya points at pandan's board without sharing its data"
description: kaya lets a note reference a pandan card by number and render its live title and status. Getting there meant rejecting the obvious batching optimisation, because the API it assumed existed turned out not to.
slug: linked-but-not-merged
author: Jian
date: 2026-08-18
status: Draft
tags: [architecture, api-design, python, fastapi, distributed-systems, adr]
-->

---

# Linked but not merged: how kaya points at pandan's board without sharing its data

Write `[[KAN-12]]` in a kaya note and it should render as something like `KAN-12 ·
in_progress · "MCP read tools: add a fields argument"`, not as a bare link. That one
requirement decides more than it looks like it does, because there are two very
different ways to get there. Store the ref as text and render a plain hyperlink with
no lookup at all. Or actually go and ask pandan what that card currently is.

The question this settles isn't whether kaya and pandan should link to each other.
Both designs do that. It's which way the dependency arrow points, because a note
that merely links out and a note that shows you what a card *is* are two different
products, with two different ways of breaking.

## What got rejected, and why

The plain-hyperlink version is the simpler build by a wide margin. Nothing to cache,
nothing to invalidate, no failure mode to design around at all: the URL just works,
and kaya's own `note_link` table still records that the reference exists. It's kept
as the fallback specifically because of that simplicity. But it can't show what a
card actually is, and a note that only links out gives up the entire reason a suite
like this exists, so it's the answer for when resolution genuinely can't be done, not
the default.

The other rejected option ran the opposite direction: pandan pushes backlink
registrations into kaya, or grows a typed `spec` link of its own pointing back at a
note. That needs schema and API work on pandan's side, a webhook or a polling job,
and a reconciliation story for whenever the two drift. Worse than the cost, it points
the dependency arrow both ways, so neither app could ship in ignorance of the other
existing. A third option, kaya keeping its own synced copy of card state, is the
worst of both: all the sync machinery, plus a second source of truth for data pandan
already owns, plus staleness that reads as a bug instead of an honest cache.

What shipped instead: **kaya resolves a ref by reading pandan's public API, with the
caller's own token, and pandan gains no idea kaya exists.** Not a kaya-owned service
credential either, which was considered and rejected for a specific reason: a
kaya-held credential would have broader access than any one caller, so a note could
in principle leak a card its reader isn't allowed to see. Forwarding the caller's own
PAT makes that structurally impossible rather than merely policed.

## The line that has to hold

One rule sits underneath all of this, and it's stated as an acceptance criterion with
its own mutation-tested guard rather than as a footnote: **nothing in kaya may block
on pandan.** A note has to save, render, and show up in full-text search with pandan
completely down. An unresolvable or unreachable ref becomes a quiet unresolved
wikilink, never an error, never an empty page.

That's worth stating loudly because it's exactly the kind of property that decays
one convenience at a time. Someone adds a sort by card column. Someone adds a filter
on card status. Someone adds a validation that rejects a broken ref on save. Each of
those looks entirely reasonable in isolation, and each one quietly makes saving a
note depend on pandan being up. The guard exists because a degradation path is
precisely the kind of thing that can pass a test suite for the wrong reason, so
there's an end-to-end test that stops a pandan stub mid-run and asserts a note still
saves, renders and is findable.

## The risk that turned out not to be there

Here's the part worth telling in full, because the original design got it wrong in
public and the correction is more interesting than either version on its own.

The first pass at this decision worried about fan-out: a note with forty `[[KAN-n]]`
refs is forty reads unless the reads get batched, and that got written down as an
open risk to settle later. The instinct isn't unreasonable. It's the standard
N+1 shape, and the standard fix is a batch endpoint or a concurrency-capped fan-out.

A spike went looking for that batch endpoint and found something else instead:
**there wasn't a single reference-shaped read to fan out in the first place.**
Pandan's `GET /api/v1/cards/{card_id}` is typed as an integer primary key. A
wikilink like `[[KAN-12]]` carries a *ticket number*, not that key, and no route
anywhere in pandan's API accepts a ticket number. The only place in the whole
backend that resolves a ticket number to a row is internal to its GitHub webhook
handler. Even pandan's own CLI doesn't have a shortcut: it resolves a ticket by
paging the entire card list and matching client-side.

kaya had already solved a version of this same problem for its own identifiers, and
solved it the way you'd hope: centrally, once, for every route that takes one.

```python
# kaya/backend/app/api/refs.py
def resolve_note(session: Session, principal: Principal, raw: str) -> Note:
    """A caller's string → the note it may see, or the same refusal for either spelling."""
    ref = parse_note_ref(raw)

    if ref.prefixed:
        statement = note_addressed_as_ref(ref.canonical)
    elif ref.number > POSTGRES_INTEGER_MAX:
        return authorize_note(principal, None)
    else:
        statement = note_addressed_as_id(ref.number)

    return authorize_note(principal, session.scalars(statement).one_or_none())
```

A note has both a stable `NOTE-n` ref and a mutable internal id, and every verb that
takes either resolves through this one function so the two spellings can never
quietly drift apart. Pandan's cards have exactly the same two-name shape (a ticket
number from a sequence, and a primary key), but nothing on pandan's side does the
resolving. So kaya couldn't fetch by id even if it wanted to, because kaya never has
the id to begin with. Getting it costs a list sweep, and once you've swept the list
you already have everything the single-card read would have told you: the list item
and the single-read response turned out to be the same shape at the byte level,
twenty-two matching keys.

## What actually ships: a sweep, not a fan-out

The real mechanism is a page walk over pandan's card list, done once per batch of
unresolved refs, with every card the walk returns cached rather than only the ones
that were actually referenced:

- `GET /api/v1/cards?limit=200`, the caller's own PAT, gzip requested, one request in flight at a time.
- A per-request timeout of about three seconds, a total walk deadline of about eight, and a cap of five pages, so a very large board degrades to partially resolved rather than to a long wait.
- Requests scale with **board size**, not with how many refs the note happens to contain.

Measured live against the real deployment (540 cards across eight boards), that's
three requests and about 4.9 seconds cold, whether the note being rendered has one
ref or forty:

| Approach | Refs | Requests | Wall clock |
|---|---|---|---|
| Sequential per-ref reads | 40 | 40 | 26.4 s |
| Concurrent fan-out, cap 8 | 40 | 40 | 4.1 s |
| Full page-walk sweep | any | 3 | 4.9 s |

Worth being honest about the one number that cuts the other way: at this board size,
a capped fan-out actually wins on raw wall clock up to somewhere around forty-five
refs, where the two approaches cross. The sweep is still the right call, for two
reasons that a single cold-cache comparison hides. A per-ref design fills one cache
entry per request; the sweep fills two hundred, so the cost amortises across every
other note on the same boards rather than just the one being rendered right now.
And the wall-clock comparison for the fan-out quietly leaves out the sweep it would
still need to run first, to get the ids to fan out over.

There's a second reason the fan-out was never really on the table, and it's the same
shape of bug as the auth threadpool problem this suite ran into elsewhere. kaya's
routes are synchronous, and a route holds its database connection for the whole
request. A concurrent fan-out from a sync route would hold a kaya database
connection open for the entire fan-out while doing no database work with it, so
enough concurrent renders exhaust the pool and take down note **saving**, which
needs nothing from pandan at all. That's the exact coupling the "nothing may block on
pandan" rule forbids, just self-inflicted from the inside instead of arriving from
outside. It would have taken pandan down too: its production instance runs a hard
concurrency ceiling low enough that one forty-ref note rendered at full fan-out is
close to the whole machine's capacity. Slow is a worse failure than down here,
because a downed upstream fails fast on connection refused, while a slow one holds
every thread and connection in the fan-out for the full timeout, multiplying load
against the exact resource that's already saturated.

## What's left deliberately unfinished

Pandan doesn't yet have a batch-read endpoint that would let this become one call
instead of a bounded sweep (there's an open issue tracking it). That's fine, and
it's fine on purpose: the sweep is already shaped like that endpoint's eventual
answer, one upstream call per batch, a cache, a deadline, an unresolved fallback. The
day pandan grows `?refs=KAN-12,KAN-45`, the sweep gets replaced by one call and
nothing else about the design has to move.

## The lesson underneath both halves of this

The lesson worth keeping past this one feature: a fan-out risk written down as an
open question in a design doc is a claim, and the correct next step is to go and
check it against the actual API, not to build the mitigation for a version of the
problem that doesn't exist. Reading pandan's real route signatures turned a "batch
this eventually" risk into "there's nothing here to batch", which is a better answer
and a cheaper one, and it only came from looking rather than assuming.
