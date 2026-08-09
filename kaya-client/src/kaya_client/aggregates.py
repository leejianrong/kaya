"""Step 3 of ADR 0004's ordering: the ``summary``. **Live since KAN-548.**

V2a held this module's place and pinned that it attached ``None``, so V2b would arrive as a visible
diff rather than as a change of behaviour nobody can date. This is that diff, and it is the third
consecutive V2b card for which ``render``'s signature did not move.

The step already mattered structurally while it was empty. ADR 0005 adopts pandan's correction as a
rule — "``summary`` is attached **after** truncation, so its counts are structurally out of the
truncator's reach" — and this module is where *structurally* is bought: it takes a ``Payload`` and
returns a ``Shaped``, and nothing downstream of it accepts a ``Payload`` again. A truncator cannot
reach a summary because by the time one exists there is no ``Payload`` left to hand it.

### The summary is the returned set, and that is true by construction

ADR 0005 §contract 5: "describing **the returned set** — under a filter or ``--limit``, the returned
set, not the whole corpus". The count below is ``len(payload.records)``, and ``attach_summary``
takes **one** parameter. There is no corpus in scope, no total to pass in and nowhere for one to
arrive from, so the tempting wrong answer is not reachable from inside this function rather than
being ruled out by care. ``tests/test_aggregates.py`` asserts the arity for exactly that reason: the
mutation that makes this describe a corpus has to widen the signature first, and that is a visible
thing to do in review.

### What is in it: **one key**, and the key is a count

``{"count": n}``. Nothing else, and the smallness is the decision rather than a starting point.

This package exists because payload breadth is what makes an agent read expensive — pandan's 44,902
tokens — so every key here is paid for on **every list read** by every consumer, forever. A key
therefore has to answer "what does a caller *do* with it?", and only the count does: it is how a
caller knows whether the rows it is looking at are all of them without counting lines, which is the
question a filter or a ``--limit`` creates and the reason contract 5 says "the returned set". The
candidates that were considered and left out — a date range over ``updated_at``, a breakdown by
``path`` — are facts a caller can compute from records it already has, and neither one changes a
decision. A summary that grew to five keys would cost more than the ``--fields`` projection two
cards ago saved on a narrow read. Measured: `scripts/measure_toon_delta.py`'s fourth table.

Adding a key here is an edit to ``tests/test_aggregates.py``'s literal, which is the same device
`serialization` uses to keep publishing a ``--format`` value a conscious act.

### An ``ENTITY`` payload gets no summary

A summary describes a returned *set*, and one note is not a set of anything. ``count: 1`` on a
`note get` would be a key that is the same on every call ever made, i.e. tokens spent to say
nothing, and `test_human_row_is_pinned.py`'s ``SINGLE_NOTE`` is deliberately untouched by this card
as the byte-level witness for it.

### Two renderings, one dict

Contract 5 asks for "a trailing line for humans, a ``summary`` object for structured consumers,
**both from the same dict**". `summary_line` below is that line, and it is a function of the
mapping: the structured formats print the dict through `Shaped.as_dict`, the human format prints
`summary_line`, and neither recomputes anything from the records. A count that disagreed between the
two formats would have to come from a second computation, and there isn't one to write.
"""

from kaya_client.payloads import Kind, Payload, Shaped

COUNT_KEY = "count"
"""The summary's one key. Named rather than written inline, because the human line reads it back out
of the same mapping the structured formats serialize — that is the mechanism behind "both from the
same dict", and a literal in two places is how the two renderings would eventually disagree."""


def attach_summary(payload: Payload) -> Shaped:
    """Wrap ``payload`` with the aggregate describing the records it actually carries.

    One parameter, on purpose: see this module's docstring. A collection gets ``{"count": n}``; an
    entity gets ``None``.

    Refusing a non-``Payload`` completes the type chain `tests/test_shaping_order.py` pins. This is
    step 3, so what arrives has been projected and truncated; a ``Shaped`` reaching it would mean
    something re-entered the pipeline after serialization's own input type had been produced.
    """
    if not isinstance(payload, Payload):
        raise TypeError(
            "attach_summary takes a Payload — it is step 3, after truncation and before "
            "serialization (ADR 0004)"
        )
    if payload.kind is not Kind.COLLECTION:
        return Shaped(payload=payload, summary=None)
    return Shaped(payload=payload, summary={COUNT_KEY: len(payload.records)})


def summary_line(shaped: Shaped) -> str | None:
    """ADR 0005 §contract 5's trailing line for humans — ``2 notes`` — or ``None`` for no line.

    Read out of ``shaped.summary``, never recounted from the records, so the line and the object a
    structured consumer receives are two renderings of one dict and cannot drift.

    ``None`` in two cases, each of which is a decision:

    - **there is no summary at all**, i.e. an entity. `serialization._entity` never asks.
    - **the count is zero.** `serialization._rows` already prints ``no notes`` for an empty
      collection — a definitive zero state rather than an empty string, which is indistinguishable
      from a crashed pipe — and that sentence *is* the rendering of ``count: 0``. A ``0 notes``
      footer beneath it would be the same fact said twice, in two spellings, one of which a reader
      would eventually take as contradicting the other. The structured formats still carry
      ``{"count": 0}``, because an object has no room for a sentence and a consumer that receives no
      ``summary`` key cannot tell an empty result from a version of kaya that had none.

    The plural comes from ``envelope_key``, which is the API's own plural (``{"notes": [...]}``),
    and the singular from ``noun``. Both are facts the payload already carries because `KayaClient`
    attached them at the call, so this does no English of its own — an ``-s`` appended here would be
    wrong for the first envelope whose plural is irregular, and would be wrong silently.
    """
    if shaped.summary is None:
        return None
    count = shaped.summary.get(COUNT_KEY)
    if not count:
        return None
    noun = shaped.payload.noun if count == 1 else shaped.payload.envelope_key
    return f"{count} {noun}"
