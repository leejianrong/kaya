"""ADR 0004's ordering, and the type chain that makes one part of it unfalsifiable.

    projection → truncation → aggregate attachment → serialization

ADR 0005 adopts pandan's correction as a rule: "``summary`` is attached **after** truncation, so its
counts are structurally out of the truncator's reach". *Structurally* is a stronger claim than *by
convention*, and this file is where it is cashed: ``truncate`` takes and returns a ``Payload``,
``attach_summary`` returns a ``Shaped``, and ``serialize`` accepts only a ``Shaped``. There is no
order of calls in which a truncator could see a summary, because by the time one exists the type the
truncator accepts is gone.

V2a wrote here that this mattered more in V2b than it did then, because every step was a no-op and
the ordering was unobservable from outside. All four steps are live as of KAN-548, and the chain
held: the count is computed from a ``Payload`` the truncator has already finished with, and
`test_aggregates.py` shows the number not moving as ``text_limit`` does. The type refusals below
are still what stops the chain being simplified away.
"""

import pytest
from conftest import note_collection

from kaya_client import Payload, Shaped, attach_summary, project, render, truncate


def test_attach_summary_turns_a_payload_into_a_shaped(notes: Payload) -> None:
    shaped = attach_summary(notes)
    assert isinstance(shaped, Shaped)
    assert shaped.payload is notes


def test_the_aggregate_is_a_count_of_the_returned_records(notes: Payload) -> None:
    """What V2a wrote as ``summary is None`` and KAN-548 replaced with a count.

    Nothing else in this file changed for that card, which is the ordering being load-bearing rather
    than incidental. What the summary *contains* is `test_aggregates.py`'s subject.
    """
    assert attach_summary(notes).summary == {"count": 2}


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
    assert shaped.as_dict() == {"notes": [], "summary": {"count": 0}}


def test_render_refuses_a_raw_response_body() -> None:
    """The chain's entrance, and the mistake this whole package exists to prevent.

    Moved here from the retired `test_passthrough_is_a_no_op.py`, because it is the same assertion
    as `test_projection_is_first_and_takes_a_payload` one step further out: a client that returned a
    ``dict`` for an adapter to format is pandan's 11.4× (ADR 0004). If ``render`` accepted one, the
    payload's ``kind`` and prose allow-list would have to be re-derived by whoever called it, and
    the obvious place to put that derivation is the adapter.
    """
    with pytest.raises(TypeError, match="ADR 0004"):
        render({"notes": []})  # type: ignore[arg-type]
