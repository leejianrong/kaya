"""What a note looks like on the wire, pinned as a key list.

This exists because of KAN-557, and it is the guard whose absence would have been invisible.
Adding a column to ``Note`` is a schema decision; adding a key to ``NoteRead`` is a **contract**
decision. The two are one keystroke apart in a review, and ``search_vector`` is the first column
where they must disagree — on the wire it would be:

- a leak of storage internals into a published contract, in a shape (``'runbook':1A 'step':2B``)
  nothing outside Postgres can act on;
- roughly the size of the note again, on **every** read by **every** consumer, which is the exact
  thing ADR 0004's projection and truncation exist to stop paying for;
- and a word a user could type, because ``kaya_client``'s ``field_names()`` builds its
  ``--fields`` vocabulary from the keys the API actually returned. ``--fields search_vector``
  would validate.

``NoteRead`` is ``from_attributes=True``, so it reads attributes off the ORM object. Pydantic only
reads the fields it declares, which is what keeps a model column from leaking automatically — but
that is a property of pydantic's behaviour rather than of anything this repository decided, so it
is asserted rather than assumed. The second test does it the hard way: a real ``Note`` instance
carrying a vector, serialized both ways.

The third test faces the other direction, and it is the one that will fire on a card nobody has
written yet. When a new column is added to ``Note``, the difference between the table and the
payload has to be *named here*, so "should this be on the wire?" is a question somebody answers
rather than skips.

No database. ``Note`` is a declarative class and a transient instance needs no connection, which
is why this belongs in the fast layer where it will actually be run.
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.api.schemas import NoteRead
from app.models import Note

NOTE_PAYLOAD_KEYS = [
    "ref",
    "id",
    "title",
    "body",
    "path",
    "created_at",
    "updated_at",
    "team_id",
]
"""Every key in a note payload, in order. Brittle on purpose: this is a published contract, and an
edit to this list should have to be argued for in a diff rather than land as a side effect of a
schema change. ``owner_id`` is absent by ADR 0008's reasoning (it is always the caller, so it
carries no information), and ``search_vector`` by KAN-557's — see the module docstring.

``team_id`` (ADR 0011, R16.5, `KAN-1086`) is on the wire, unlike ``owner_id``: it *does* carry
information a reader doesn't already have — which of the caller's possibly-several teams, if any,
this note defaults to sharing with. It was withheld from `KAN-1082` (schema-only) through `KAN-1084`
(authorization only) and joins the payload only once `create_note` can actually set it to something
other than ``NULL``."""

NOT_ON_THE_WIRE = {"owner_id", "search_vector"}
"""Columns of ``note`` deliberately kept out of the payload, each for a reason written down in
``app/models/note.py``. A new name appearing here is a decision; a new name appearing *only* in
the table is an oversight, and the third test is the difference between them."""


def a_note() -> Note:
    """A transient note with every attribute set, including the one Postgres owns.

    Assigning ``search_vector`` is exactly what Postgres would refuse on a flush and exactly what
    this test needs: the value has to be *present* on the object, or "it does not reach the wire"
    would hold for the boring reason that there was nothing to leak.
    """
    note = Note(
        id=12,
        ref="NOTE-12",
        owner_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
        title="runbook",
        body="# steps",
        path="ops/runbook.md",
        created_at=datetime(2026, 8, 11, 9, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 11, 9, 30, 0, 123456, tzinfo=UTC),
    )
    note.search_vector = "'runbook':1A 'step':2B"
    return note


def test_the_note_payload_keys_are_pinned() -> None:
    assert list(NoteRead.model_fields) == NOTE_PAYLOAD_KEYS


def test_the_search_vector_does_not_reach_a_serialized_note() -> None:
    """The behavioural half: the pin above stays green if ``of()`` grew a key some other way."""
    payload = NoteRead.of(a_note()).model_dump()

    assert list(payload) == NOTE_PAYLOAD_KEYS
    assert "search_vector" not in payload
    # And in the bytes, not just the keys — a lexeme string is recognisable, so this catches it
    # arriving under some other name too.
    assert ":1A" not in NoteRead.of(a_note()).model_dump_json()


def test_every_note_column_is_either_published_or_deliberately_withheld() -> None:
    """The alarm for the *next* column, which is the one nobody will think about.

    Adding a column to ``Note`` does not add it to ``NoteRead`` — pydantic is explicit — so what
    this catches is not a leak. It is a silence: a stored field nobody decided about, which is how
    a note ends up carrying data the API can never hand back.
    """
    columns = set(Note.__table__.columns.keys())
    published = set(NOTE_PAYLOAD_KEYS)

    assert published <= columns, (
        f"the payload claims a field the table does not have: {sorted(published - columns)}"
    )
    assert columns - published == NOT_ON_THE_WIRE, (
        "a `note` column is neither in the payload nor in the list of columns deliberately kept "
        "off the wire. Decide which it is, say so in `app/models/note.py`, then name it here: "
        f"{sorted((columns - published) ^ NOT_ON_THE_WIRE)}"
    )


def test_the_pin_would_notice_an_extra_key() -> None:
    """An equality assertion passes for the wrong reason unless it is shown failing."""
    leaky = NoteRead.of(a_note()).model_dump()
    leaky["search_vector"] = "'runbook':1A"

    with pytest.raises(AssertionError):
        assert list(leaky) == NOTE_PAYLOAD_KEYS
