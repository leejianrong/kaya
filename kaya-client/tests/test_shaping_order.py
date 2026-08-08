"""ADR 0004's ordering, and the type chain that makes one part of it unfalsifiable.

    projection → truncation → aggregate attachment → serialization

ADR 0005 adopts pandan's correction as a rule: "``summary`` is attached **after** truncation, so its
counts are structurally out of the truncator's reach". *Structurally* is a stronger claim than *by
convention*, and this file is where it is cashed: ``truncate`` takes and returns a ``Payload``,
``attach_summary`` returns a ``Shaped``, and ``serialize`` accepts only a ``Shaped``. There is no
order of calls in which a truncator could see a summary, because by the time one exists the type the
truncator accepts is gone.

That matters more in V2b than it does now. Today every step is a no-op and the ordering is
unobservable from outside; the tests below are what stop somebody simplifying the chain away in the
meantime, at which point V2b would land the aggregate in the truncator's path and nothing would
notice until a count came back describing truncated text.
"""

import pytest
from conftest import note_collection

from kaya_client import Payload, Shaped, attach_summary, project, render, truncate


def test_attach_summary_turns_a_payload_into_a_shaped(notes: Payload) -> None:
    shaped = attach_summary(notes)
    assert isinstance(shaped, Shaped)
    assert shaped.payload is notes


def test_v2a_attaches_no_aggregate(notes: Payload) -> None:
    """The assertion V2b replaces with a count. Nothing else in this file changes."""
    assert attach_summary(notes).summary is None


def test_the_truncator_cannot_be_handed_a_shaped_payload(notes: Payload) -> None:
    """The load-bearing one. A summary is unreachable from truncation by construction."""
    shaped = attach_summary(notes)
    with pytest.raises(TypeError, match="attached after truncation"):
        truncate(shaped, 500)  # type: ignore[arg-type]


def test_projection_is_first_and_takes_a_payload(notes: Payload) -> None:
    """Symmetrical guard: nothing already shaped can re-enter the pipeline at step 1 either."""
    with pytest.raises(TypeError, match="first step"):
        project(attach_summary(notes), None)  # type: ignore[arg-type]


def test_records_are_never_mutated_by_a_render(notes: Payload) -> None:
    """The pipeline is pure. V2b truncates by rebuilding records, never by editing them in place.

    Worth pinning now: the payload is the *complete* API response (ADR 0004 §Consequences), and a
    truncator that edited it would make ``--full`` unsatisfiable — the untruncated text would be
    gone by the time anything asked for it.
    """
    before = [dict(record) for record in notes.records]
    for fmt in ("human", "json", "data"):
        render(notes, fmt=fmt, text_limit=1, fields=["ref"])
    assert [dict(record) for record in notes.records] == before


def test_the_shaped_dict_does_not_alias_the_payload(notes: Payload) -> None:
    """Mutating what ``fmt="data"`` returned must not reach back into the client's payload.

    An MCP adapter gets this dict and hands it to a host that may well add keys to it.
    """
    data = render(notes, fmt="data")
    assert isinstance(data, dict)
    data["notes"][0]["title"] = "clobbered"
    assert notes.records[0]["title"] == "Groceries"


def test_an_empty_collection_survives_the_whole_pipeline() -> None:
    shaped = attach_summary(truncate(project(note_collection(), None), 500))
    assert shaped.as_dict() == {"notes": []}
