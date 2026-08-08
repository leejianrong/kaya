"""``fields`` and ``text_limit`` do **nothing** in V2a, and that is pinned rather than assumed.

The card is explicit: "V2a implements only the ``fmt`` dimension; ``fields`` and ``text_limit``
exist in the signature and pass through untouched". A no-op is the easiest thing in a codebase to
implement by accident and the hardest to date afterwards, so these assertions exist to make V2b's
arrival a **visible diff** — the day projection and truncation land, this file goes red in a way
that names exactly which parameter started meaning something.

The line this file draws is between the **shape** of an argument (checked now) and its
**vocabulary** (V2b's). ``fields=["nope"]`` is accepted here on purpose: rejecting an unknown
name is V2b's job, and doing it early would make the pass-through claim false.
``fields="ref,title"`` is refused, because a bare string is an iterable of characters and the
no-op would swallow it today only for V2b to project a payload down to ``r``, ``e``, ``f``.
"""

import pytest
from conftest import note_collection

from kaya_client import DEFAULT_TEXT_LIMIT, Payload, project, render, truncate

FORMATS = ["human", "json", "data"]


@pytest.mark.parametrize("fmt", FORMATS)
@pytest.mark.parametrize("fields", [None, ["ref"], ["ref", "title"], [], ["not_a_field_at_all"]])
def test_fields_changes_nothing(notes: Payload, fmt: str, fields: list[str] | None) -> None:
    assert render(notes, fields=fields, fmt=fmt) == render(notes, fmt=fmt)


@pytest.mark.parametrize("fmt", FORMATS)
@pytest.mark.parametrize("text_limit", [0, 1, 5, DEFAULT_TEXT_LIMIT, 10_000])
def test_text_limit_changes_nothing(notes: Payload, fmt: str, text_limit: int) -> None:
    """Including ``0``, which V2b makes "truncation disabled", and ``1``, which V2b makes brutal."""
    assert render(notes, text_limit=text_limit, fmt=fmt) == render(notes, fmt=fmt)


def test_a_long_body_is_not_truncated_anywhere(note: Payload) -> None:
    """The specific claim, on the specific field V2b's allow-list will contain.

    Asserted against the rendered bytes rather than against the payload, because the payload being
    untouched would still be true if a serializer did its own truncating — which is precisely the
    shape of the mistake ADR 0004 is about.
    """
    long_body = "x" * (DEFAULT_TEXT_LIMIT * 3)
    payload = Payload.entity(
        noun="note",
        envelope_key="notes",
        record={"ref": "NOTE-1", "title": "Long", "body": long_body},
        columns=("ref", "title", "body"),
        prose_fields=frozenset({"body"}),
    )
    rendered = render(payload)
    assert isinstance(rendered, str)
    assert long_body in rendered


def test_the_steps_themselves_return_the_very_same_object(notes: Payload) -> None:
    """Identity, not equality: an equal-but-rebuilt payload would hide a step that started working.

    These two ``is`` checks are the assertions V2b deletes. Nothing else in the suite has to change
    for projection and truncation to arrive.
    """
    assert project(notes, ["ref"]) is notes
    assert truncate(notes, 1) is notes


@pytest.mark.parametrize("fields", ["ref,title", b"ref", ["ref", 3]])
def test_a_field_list_that_could_not_be_one_is_refused_now(notes: Payload, fields: object) -> None:
    """Shape, not vocabulary. Refused now so V2b inherits no caller relying on the coercion."""
    with pytest.raises(TypeError):
        render(notes, fields=fields)  # type: ignore[arg-type]


@pytest.mark.parametrize("text_limit", [-1, -500])
def test_a_negative_text_limit_is_refused(notes: Payload, text_limit: int) -> None:
    """``0`` already spells "disabled" (ADR 0005's ``--full``), so a negative is a caller bug."""
    with pytest.raises(ValueError, match="0 disables"):
        render(notes, text_limit=text_limit)


@pytest.mark.parametrize("text_limit", ["500", 1.5, True, None])
def test_a_text_limit_that_is_not_a_character_count_is_refused(
    notes: Payload, text_limit: object
) -> None:
    """``True`` is in there deliberately: it is an ``int`` and would silently mean one char."""
    with pytest.raises(TypeError):
        render(notes, text_limit=text_limit)  # type: ignore[arg-type]


def test_render_refuses_a_raw_response_body() -> None:
    """The mistake this whole package exists to prevent, refused at the door.

    A client that returned a ``dict`` for an adapter to format is pandan's 11.4× (ADR 0004). If
    ``render`` accepted one, the payload's ``kind`` and prose allow-list would have to be re-derived
    by whoever called it, and the obvious place to put that derivation is the adapter.
    """
    with pytest.raises(TypeError, match="ADR 0004"):
        render({"notes": []})  # type: ignore[arg-type]


def test_the_empty_payload_still_renders_in_every_format() -> None:
    """A zero-row list is the payload most likely to trip a width or aggregate computation."""
    empty = note_collection()
    for fmt in FORMATS:
        assert render(empty, fmt=fmt) is not None
