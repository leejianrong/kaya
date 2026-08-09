"""``text_limit`` still does **nothing**, pinned rather than assumed. ``fields`` now does something.

V2a pinned both halves so that V2b's arrival would be a **visible diff** — a no-op is the easiest
thing in a codebase to implement by accident and the hardest to date afterwards. **KAN-546 spent the
``fields`` half**: this file went red exactly where projection started meaning something, and those
assertions moved out to `test_projection.py`, which is what the parameter does now.

What is left here is the ``text_limit`` half, still a validated pass-through, and it must stay that
way until **KAN-547** fills it. That card's diff is this file going red a second time, in the same
way, for the other parameter. Do not pre-empt it and do not relax it: `test_a_long_body_is_not_
truncated_anywhere` is the whole of ADR 0005 §contract 6 stated as an absence.

The line this file draws is between the **shape** of an argument (a ``TypeError``, checked at the
seam whatever the payload contains) and its **vocabulary** (a ``UsageError``, exit `2`, and for
``fields`` that now lives in `kaya_client.projection`). ``fields="ref,title"`` is a shape error and
is refused here, because a bare string is an iterable of characters and projection would narrow a
payload down to ``r``, ``e``, ``f``.
"""

import pytest
from conftest import note_collection

from kaya_client import DEFAULT_TEXT_LIMIT, Payload, project, render, truncate

FORMATS = ["human", "json", "data"]


@pytest.mark.parametrize("fmt", FORMATS)
def test_omitting_fields_still_changes_nothing(notes: Payload, fmt: str) -> None:
    """All that survives of ``test_fields_changes_nothing``, and the half that was never V2b's.

    KAN-546 made ``fields=["ref"]`` mean something, so the parametrised cases moved to
    `test_projection.py`. ``fields=None`` did not move: ADR 0005 §contract 2's guarantee is now
    precisely that a caller who *did not ask* for projection gets the complete record back, and that
    is the same claim `test_human_row_is_pinned.py` makes about the bytes.
    """
    assert render(notes, fields=None, fmt=fmt) == render(notes, fmt=fmt)


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


def test_the_truncator_returns_the_very_same_object(notes: Payload) -> None:
    """Identity, not equality: an equal-but-rebuilt payload would hide a step that started working.

    This is the assertion **KAN-547** deletes. Its sibling — ``project(notes, ["ref"]) is notes`` —
    is the one KAN-546 deleted, and `test_projection.py` states the replacement: projection returns
    the same object for ``fields=None`` and a narrowed one otherwise.
    """
    assert truncate(notes, 1) is notes


def test_projection_is_still_identity_when_nothing_was_asked_for(notes: Payload) -> None:
    """The half of the old ``is`` check that KAN-546 kept, and strengthened by keeping.

    ``fields=None`` returning the very same object is what makes "omitting ``--fields`` changed
    nothing" a fact about identity rather than about two equal renders — and it is the mechanism
    behind the byte-identity pin, not a restatement of it.
    """
    assert project(notes, None) is notes


@pytest.mark.parametrize("fields", ["ref,title", b"ref", ["ref", 3]])
def test_a_field_list_that_could_not_be_one_is_refused(notes: Payload, fields: object) -> None:
    """Shape, not vocabulary — a ``TypeError`` for a caller bug, not exit `2` for a typo.

    Still here, and still a ``TypeError``, now that projection is live: this is the case the
    distinction was drawn for. A bare ``"ref,title"`` is an iterable of characters, so without this
    the payload would narrow to ``r``, ``e``, ``f`` — or, worse, be refused as an unknown *field*
    named ``r``, sending the adapter author looking at their vocabulary instead of their ``split``.
    """
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
