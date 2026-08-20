"""What a link looks like on the wire, pinned as a key list — KAN-566.

The twin of ``test_note_payload_keys.py``, and it exists for the reason that file's own docstring
gives, one table over: adding a column to ``note_link`` is a schema decision and adding a key to
``LinkRead`` is a **contract** decision, and the two are one keystroke apart in a review.

``note_link`` is the more dangerous of the two tables to serialize, because three of its five
columns are internal surrogates and one of them — ``resolved_id`` — is *already the thing the edge
points at*, so publishing it looks like helpfulness rather than a leak. It would hand a caller a
number no route accepts (ADR 0008: a note is addressed as ``NOTE-12``, ``note-12`` or ``12``, and
that last one is ``note.id``, not ``note_link.resolved_id``), and ``kaya_client``'s
``field_names()`` builds its ``--fields`` vocabulary from the keys the API actually returned, so
``--fields resolved_id`` would validate.

The third test faces the other direction and is the one that fires on a card nobody has written yet:
when a column is added to ``note_link``, whether it belongs on the wire has to be *answered here*
rather than skipped.

No database. These are declarative classes and transient instances need no connection.
"""

import pytest

from app.api.schemas import LinkRead
from app.models.note_link import NoteLink

LINK_PAYLOAD_KEYS = [
    "target_kind",
    "target_ref",
    "resolved_ref",
    "title",
    "column",
]
"""Every key in a link payload, in order. Brittle on purpose, exactly like the note list.

``resolved_ref`` is the deliberate *rename* rather than a passthrough: it carries a ``NOTE-n`` or a
``KAN-n``, never ``note_link.resolved_id``'s integer. And there is deliberately no ``resolved``
boolean — see ``LinkRead``, which argues that it would be a second spelling of
``resolved_ref is null``."""

NOT_ON_THE_WIRE = {"id", "source_note_id", "resolved_id", "created_at"}
"""``note_link`` columns deliberately kept out of the payload.

- ``id`` — the edge's own surrogate. It identifies a row in a table no caller can address.
- ``source_note_id`` — the note in the URL. It carries no information, the same argument
  ``NoteRead`` makes for omitting ``owner_id``.
- ``resolved_id`` — an internal id whose *namespace depends on another column*
  (``app/models/note_link.py``). ``resolved_ref`` is what a caller can act on.
- ``created_at`` — when the edge was first recorded. A real fact, and nothing has asked for it: a
  link is a property of the body as it stands, and the body's own timestamps are on the note. It is
  additive to this payload the day something wants it.
"""

DERIVED_KEYS = {"resolved_ref", "title", "column"}
"""Payload keys with no column behind them at all — resolved live, per caller, per read.

They are the reason the third test cannot simply assert ``published <= columns`` the way the note
one does: ``/links`` is not a projection of a table. ``title`` and ``column`` come from pandan
through KAN-564's cache and are never stored (``app/api/links.py`` says why persisting them would
be a cross-caller leak), and ``resolved_ref`` is derived from ``resolved_id`` precisely so that the
id does not travel."""


def test_the_link_payload_keys_are_pinned() -> None:
    assert list(LinkRead.model_fields) == LINK_PAYLOAD_KEYS


def test_no_internal_id_reaches_a_serialized_link() -> None:
    """The behavioural half: the pin above stays green if ``LinkRead`` grew a key some other way.

    The record is built the way ``link_records`` builds one, and then checked for the *values* as
    well as the keys — 4242 is a distinctive integer, so this catches ``resolved_id`` arriving under
    some other name, which is precisely how a rename-and-forget would land it.
    """
    record = LinkRead(
        target_kind="NOTE",
        target_ref="Old Name",
        resolved_ref="NOTE-7",
        title="New Name",
        column=None,
    )
    payload = record.model_dump()

    assert list(payload) == LINK_PAYLOAD_KEYS
    for withheld in NOT_ON_THE_WIRE:
        assert withheld not in payload

    serialized = LinkRead(
        target_kind="NOTE", target_ref="x", resolved_ref="NOTE-4242", title="y", column=None
    ).model_dump()
    assert "4242" not in str({k: v for k, v in serialized.items() if k != "resolved_ref"})


def test_every_note_link_column_is_either_published_or_deliberately_withheld() -> None:
    """The alarm for the *next* column on ``note_link``, which is the one nobody will think about.

    Unlike ``NoteRead``, ``LinkRead`` is not a projection of a table — three of its keys have no
    column at all — so the assertion is on the columns, not on the payload: every column is either
    named as published or named as withheld, and a new one is in neither list until somebody
    decides.
    """
    columns = set(NoteLink.__table__.columns.keys())
    from_columns = set(LINK_PAYLOAD_KEYS) - DERIVED_KEYS

    assert from_columns <= columns, (
        f"the payload claims a column `note_link` does not have: {sorted(from_columns - columns)}"
    )
    assert columns - from_columns == NOT_ON_THE_WIRE, (
        "a `note_link` column is neither in the payload nor in the list of columns deliberately "
        "kept off the wire. Decide which it is, say so in `app/models/note_link.py`, then name it "
        f"here: {sorted((columns - from_columns) ^ NOT_ON_THE_WIRE)}"
    )


def test_the_pin_would_notice_an_extra_key() -> None:
    """An equality assertion passes for the wrong reason unless it is shown failing."""
    leaky = LinkRead(
        target_kind="NOTE", target_ref="x", resolved_ref="NOTE-7", title="y", column=None
    ).model_dump()
    leaky["resolved_id"] = 7

    with pytest.raises(AssertionError):
        assert list(leaky) == LINK_PAYLOAD_KEYS


def test_the_column_alarm_would_notice_a_new_column() -> None:
    """And so does the third test, shown failing — the same discipline, on the assertion whose
    whole job is to fire on a card that does not exist yet."""
    columns = set(NoteLink.__table__.columns.keys()) | {"resolved_at"}
    from_columns = set(LINK_PAYLOAD_KEYS) - DERIVED_KEYS

    with pytest.raises(AssertionError):
        assert columns - from_columns == NOT_ON_THE_WIRE
