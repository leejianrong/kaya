"""Step 1 of ADR 0004's ordering: ``fields`` selection. **Live since KAN-546.**

V2a held this module's place and pinned that it did nothing, so that V2b would arrive as a visible
diff rather than as a subtle change of behaviour nobody can date. This is that diff. The pin was
``tests/test_passthrough_is_a_no_op.py``, which KAN-546 halved and KAN-547 retired: its ``fields``
assertions are in `tests/test_projection.py` and its ``text_limit`` ones in
`tests/test_truncation.py`, because after both cards neither parameter passes anything through.

### What `--fields` does, and why it does the same thing in every format

**It narrows the shaped dict, uniformly.** ``fields`` names a subset of the record's own keys;
``columns`` becomes that subset **in the order the caller gave**, and ``records`` narrow to it.

V2a recorded a tension here and left it to V2b, so here is the settlement. ADR 0004 §Decision calls
this step "projection — ``fields`` selection", motivated by pandan's measurement that field breadth
is what makes an MCP payload cost 44,902 tokens; ADR 0005 §contract 2 says ``--fields`` "widens the
human row" and "does not affect structured output, which is already complete". Those describe
different operations, and the honest answer turned out to be that one operation satisfies both
readings:

- under ``human``, narrowing to the named subset **widens** the visible row, because the default row
  (``ref``/``title``/``path``) is deliberately narrower than the record. ADR 0005's word, satisfied.
- under ``json``/``toon``/``data``, the payload carries exactly the named keys. ADR 0004's
  44,902→7,204, satisfied.

What ADR 0005 §contract 2 actually protects is that a caller who did *not* ask for projection gets a
complete record — one it can feed back to the API's own contract. ``fields=None`` returns the very
same payload object, so that is true by construction. A caller who *did* ask asked in both adapters
at once: the CLI's ``--fields`` and MCP's ``fields`` are one parameter through one seam, and making
the projection depend on ``fmt`` would put a behavioural difference between the two adapters inside
the shared step, which is the exact drift ADR 0004 exists to prevent. ADR 0005 carries a dated
amendment (2026-08-09, KAN-546) saying so; nothing was withdrawn from a user, because ``--fields``
had never shipped.

### Shape, then applicability, then vocabulary

The three refusals below are ordered, and the order is the answer to "what is wrong with this call?"
asked from the outside in:

1. **Shape** (``TypeError``, and it predates this card). ``fields="ref,title"`` is a bare string,
   which is an iterable of characters, so a projection would narrow the payload to ``r``, ``e``,
   ``f``. Splitting the comma-separated argv value is the adapter's job, and this says so.
2. **Applicability** (``UsageError``). ``fields`` on a single entity is refused, never silently
   ignored — ADR 0005 §contract 2, and the requirement `Payload.kind` exists to answer. It is
   checked before the vocabulary because ``kaya note get 12 --fields nope`` has one thing wrong with
   it and it is not the spelling.
3. **Vocabulary** (``UsageError``, naming the field). Derived from ``Payload.field_names()``, taken
   from the payload **before** anything narrows it, so it cannot drift from the API. The message
   names the offending field *and* lists what was available, because a refusal that only said "no"
   would leave the caller guessing at the very thing this vocabulary is derived to be exact about.

All three of the ``UsageError``s are ADR 0005 §contract 4's exit `2` without anybody choosing a
number: the class carries ``code = "usage"`` and `kaya_cli.failures` looks it up.

### The parameter is called ``fields`` in every message, never ``--fields``

The CLI spells it as a flag and MCP spells it as a tool parameter. A message written here reaches
both, so it names the parameter they share. Telling an MCP caller to drop a ``--flag`` that does not
exist on its surface would be this package knowing about one adapter, which is the arrow ADR 0004
points the other way.
"""

from collections.abc import Sequence

from kaya_client.errors import UsageError
from kaya_client.payloads import Kind, Payload

FIELDS_ARG = "fields"
"""What ADR 0005 §contract 3's ``arg`` column carries when the refusal is about the parameter itself
rather than about one name inside it. The parameter's name, not a flag's spelling — see above."""


def project(payload: Payload, fields: Sequence[str] | None) -> Payload:
    """Return ``payload`` selected down to ``fields``, or ``payload`` itself if ``fields is None``.

    The ``None`` path returns the **same object**, not an equal copy. That is what makes "omitting
    ``--fields`` changed nothing" provable rather than plausible, and it is the property
    `tests/test_human_row_is_pinned.py` is the byte-level witness for.
    """
    if not isinstance(payload, Payload):
        raise TypeError("project takes a Payload — it is the first step, before anything shapes it")
    check_fields(fields)
    if fields is None:
        return payload

    if payload.kind is not Kind.COLLECTION:
        raise UsageError(
            f"fields selects columns from a list of {payload.envelope_key}, and one "
            f"{payload.noun} is already a single record — drop it, or ask a list verb",
            arg=FIELDS_ARG,
        )

    selected = list(fields)
    if not selected:
        # Reachable in code (an MCP call with `fields=[]`) but not from argv: the CLI splits on
        # commas, and splitting any string yields at least one segment. Refused rather than treated
        # as `None`, because "select nothing" and "do not project" are different requests and the
        # first one produces records with no keys at all — a payload no consumer can act on.
        raise UsageError(
            "fields named no columns to select — omit it to get the default row", arg=FIELDS_ARG
        )

    check_vocabulary(payload, selected)
    return payload.narrowed_to(selected)


def check_fields(fields: Sequence[str] | None) -> None:
    """Reject an argument that could not be a field list, whatever its names turn out to be.

    Shape only, and separate from `check_vocabulary` because the two failures are different kinds of
    wrong: this one is a programming error in the caller (a ``TypeError``, raised even for a payload
    that has no vocabulary at all), and that one is a person or an agent naming a column the API
    does not have (a ``UsageError``, exit `2`).
    """
    if fields is None:
        return
    if isinstance(fields, str | bytes):
        raise TypeError(
            "fields must be a sequence of field names, not a string — split the comma-separated "
            "argv value in the adapter"
        )
    if not all(isinstance(name, str) for name in fields):
        raise TypeError("fields must contain only field names")


def check_vocabulary(payload: Payload, fields: Sequence[str]) -> None:
    """Every name must be a key the payload's own records carry. Refuse the first that is not.

    **The vocabulary is read before any narrowing**, which is the whole of "derived from the
    payload's own keys so it cannot drift from the API" — a list maintained here would go stale on
    the deploy that adds a column, and one read after projection would accept only what it had
    already selected.

    A payload with **no records has no vocabulary**, and every name is accepted. A `note list` that
    came back empty must still answer ``no notes``: refusing ``--fields ref`` because the corpus
    happens to be empty would report the caller's spelling as wrong on the evidence of somebody
    else's data, and the zero state is the correct answer to the question either way.
    """
    vocabulary = payload.field_names()
    if not vocabulary:
        return
    for name in fields:
        if name not in vocabulary:
            known = ", ".join(vocabulary)
            raise UsageError(
                f"unknown field {name!r} — a {payload.noun} has {known}",
                arg=name,
            )
