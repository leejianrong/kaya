"""ADR 0009's precondition, in the fast layer: the comparison, the `409` body, and the round trip.

SLICES §V1 puts two unit rows here — "the `409` body contains both the attempted and the stored
version" and "a write omitting the precondition is accepted as a plain overwrite" — and the whole
rule is exercisable without infrastructure, because ``app/api/concurrency.py`` takes a ``Note``
and a ``NoteUpdate`` rather than a request.

The third thing under test has no row in SLICES and is the one most likely to break the feature:
**microsecond fidelity**. ``updated_at`` is ``timestamptz``, Postgres stores microseconds, and the
token goes out as JSON and comes back as JSON. Lose one microsecond anywhere in that loop and
*every* correct write is refused with a `409` — a total failure that still passes any test written
against a round-numbered timestamp. So every timestamp in this file ends in ``.123456``.

No database: a ``Note`` constructed in memory is enough, because nothing here queries.
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.concurrency import attempted_version, enforce_precondition, note_conflict
from app.api.schemas import NoteRead, NoteUpdate
from app.models import Note

# Microseconds that are not zero, not round, and not a repeated digit — a truncation to milliseconds
# would keep `.123` and still change the value, so this catches partial losses too.
STORED_AT = datetime(2026, 8, 7, 10, 11, 12, 123456, tzinfo=UTC)
CREATED_AT = datetime(2026, 8, 1, 9, 0, 0, 654321, tzinfo=UTC)
ONE_MICROSECOND = timedelta(microseconds=1)

OWNER = uuid.UUID("11111111-1111-4111-8111-111111111111")


def stored_note(**overrides: Any) -> Note:
    """A ``Note`` with every column populated, unattached to any session."""
    fields: dict[str, Any] = {
        "id": 12,
        "ref": "NOTE-12",
        "owner_id": OWNER,
        "title": "runbook",
        "body": "# steps\n\nthe original three thousand words",
        "path": "ops/runbook.md",
        "created_at": CREATED_AT,
        "updated_at": STORED_AT,
    }
    return Note(**{**fields, **overrides})


def update(**fields: Any) -> NoteUpdate:
    """A ``PATCH`` payload built the way a request builds it, so ``model_fields_set`` is honest."""
    return NoteUpdate.model_validate(fields)


def error(exception: Any) -> dict[str, Any]:
    return exception.detail["error"]


class FakeSession:
    """Enough of a ``Session`` for the check: something that re-reads a row on demand.

    ``on_refresh`` is what another writer committing looks like from in here — the row comes back
    saying something different from what this transaction had. That is the whole reason the check
    re-reads instead of trusting the copy the ref resolver loaded, so it needs to be expressible in
    the fast layer rather than only against a real Postgres.
    """

    def __init__(self, on_refresh: Callable[[Note], None] | None = None) -> None:
        self.on_refresh = on_refresh
        self.locks: list[bool] = []

    def refresh(self, instance: Note, with_for_update: bool = False) -> None:
        self.locks.append(with_for_update)
        if self.on_refresh is not None:
            self.on_refresh(instance)


# --- SLICES §V1: the `409` body carries both versions ---------------------------------------------


def test_the_409_body_contains_both_the_attempted_and_the_stored_version() -> None:
    """SLICES §V1's unit row, and the whole reason the status code alone is not the feature.

    "Your write was refused" is not actionable. The caller needs what it tried to write and what is
    there now, which is what KAN-556's "keep mine / keep theirs / side-by-side" banner renders.
    """
    note = stored_note()
    payload = update(body="my rewritten paragraph", if_updated_at=STORED_AT - ONE_MICROSECOND)

    conflict = note_conflict(note, payload)

    assert conflict.status_code == 409
    assert error(conflict)["code"] == "note_conflict"
    assert error(conflict)["attempted"].body == "my rewritten paragraph"
    assert error(conflict)["stored"].body == "# steps\n\nthe original three thousand words"


def test_both_versions_are_whole_notes_rather_than_the_changed_fields() -> None:
    """A prose diff needs both bodies entire. A client cannot reconstruct one from a patch it no
    longer holds, and the SPA that shows the banner may not be the tab that sent the write."""
    conflict = note_conflict(stored_note(), update(body="mine", if_updated_at=CREATED_AT))

    for version in (error(conflict)["attempted"], error(conflict)["stored"]):
        assert isinstance(version, NoteRead)
        assert set(version.model_dump()) == {
            "ref",
            "id",
            "title",
            "body",
            "path",
            "created_at",
            "updated_at",
        }


def test_the_two_versions_carry_the_updated_at_that_makes_keep_mine_possible() -> None:
    """"Keep mine" is this same `PATCH` again, with ``attempted``'s body and ``stored``'s token.

    So ``attempted.updated_at`` is the version the caller was editing from — not a new stamp for a
    write that never happened — and ``stored.updated_at`` is the one to send next.
    """
    read_at = STORED_AT - timedelta(seconds=30)
    conflict = note_conflict(stored_note(), update(body="mine", if_updated_at=read_at))

    assert error(conflict)["attempted"].updated_at == read_at
    assert error(conflict)["stored"].updated_at == STORED_AT


def test_the_message_names_both_timestamps() -> None:
    """ADR 0005 wants a refusal renderable as one line. "The note changed" without saying when
    leaves a scripted caller nothing to log."""
    read_at = STORED_AT - timedelta(minutes=5)
    message = error(note_conflict(stored_note(), update(body="mine", if_updated_at=read_at)))[
        "message"
    ]

    assert "NOTE-12" in message
    assert STORED_AT.isoformat() in message
    assert read_at.isoformat() in message


def test_the_refusal_does_not_invent_a_shape_of_its_own() -> None:
    """``error_body`` is the single builder (KAN-536). The two versions ride along as extras, so a
    client that only reads ``error.code`` still parses this one."""
    conflict = note_conflict(stored_note(), update(body="mine", if_updated_at=CREATED_AT))

    assert set(conflict.detail) == {"error"}
    assert set(error(conflict)) == {"code", "message", "attempted", "stored"}
    assert isinstance(error(conflict)["code"], str)
    assert isinstance(error(conflict)["message"], str)


def test_the_attempted_version_shows_untouched_fields_as_they_are_stored() -> None:
    """Kaya never saw the caller's base version, only the token naming it. Showing the stored value
    for a field this write was not changing is the honest rendering *and* the useful one — the diff
    then highlights only what the caller actually touched."""
    attempted = attempted_version(
        stored_note(title="renamed by the other writer"),
        update(body="mine", if_updated_at=CREATED_AT),
    )

    assert attempted.title == "renamed by the other writer"
    assert attempted.ref == "NOTE-12"
    assert attempted.id == 12
    assert attempted.created_at == CREATED_AT


def test_building_the_conflict_does_not_touch_the_stored_note() -> None:
    """The `409` is built from a live ORM object. Mutating it here would write the refused change to
    the database on the way out — a rejected write that lands anyway."""
    note = stored_note()

    note_conflict(note, update(title="mine", body="mine too", if_updated_at=CREATED_AT))

    assert note.title == "runbook"
    assert note.body == "# steps\n\nthe original three thousand words"


# --- Which writes are guarded ---------------------------------------------------------------------


def test_a_write_omitting_the_precondition_is_a_plain_overwrite() -> None:
    """SLICES §V1's other unit row, and ADR 0009 §Decision in one assertion.

    The precondition is "a guarantee available to any client that wants it, not a tax on every
    caller": `curl` works without a read-first dance, and `kaya note edit --force` stays possible.
    Making it mandatory would be a different decision from the one that was accepted.
    """
    assert update(body="whatever was there before is gone").guards_the_body() is False


def test_a_write_carrying_a_precondition_on_the_body_is_guarded() -> None:
    assert update(body="mine", if_updated_at=STORED_AT).guards_the_body() is True


def test_a_metadata_only_write_is_unguarded_even_with_a_stale_precondition() -> None:
    """ADR 0009 §Decision: "Metadata-only writes (title, path) stay plain LWW, because they're
    card-shaped fields where the original reasoning holds."

    The reasoning it means is the payload one — losing 3,000 words silently is a different harm from
    losing a re-typed title — so a rename is not a conflict this decision is about. The SPA "sends
    it always", and a `409` on a rename would train its user to dismiss the banner that matters.
    """
    assert update(title="renamed", if_updated_at=CREATED_AT).guards_the_body() is False
    assert update(path="archive/2026/moved.md", if_updated_at=CREATED_AT).guards_the_body() is False
    assert update(title="renamed", path="moved.md", if_updated_at=CREATED_AT).guards_the_body() is (
        False
    )


def test_a_write_touching_both_metadata_and_the_body_is_guarded() -> None:
    """And therefore rejected whole. Applying the title half of a refused write would be a second
    silent edit, in the opposite direction."""
    payload = update(title="renamed", body="mine", if_updated_at=CREATED_AT)

    assert payload.guards_the_body() is True
    assert attempted_version(stored_note(), payload).title == "renamed"


def test_an_empty_patch_is_not_a_body_write() -> None:
    """A no-op changes nothing, so there is nothing to lose and nothing to refuse."""
    assert update(if_updated_at=CREATED_AT).guards_the_body() is False


def test_sending_the_body_unchanged_is_still_a_body_write() -> None:
    """"Guarded" is about what the write claims to touch, not about whether the bytes differ.
    Comparing bodies instead would make the guarantee depend on the caller having read recently
    enough for its copy to still match — which is the thing under dispute."""
    note = stored_note()

    assert update(body=note.body, if_updated_at=CREATED_AT).guards_the_body() is True


def test_the_precondition_is_never_written_to_the_note() -> None:
    """``changes()`` feeds ``setattr``. A precondition that leaked into it would stamp
    ``updated_at`` with the value the caller *read*, which is a time-travelling row and a
    permanently wedged token."""
    changes = update(body="mine", if_updated_at=STORED_AT).changes()

    assert changes == {"body": "mine"}
    assert "if_updated_at" not in changes


# --- Enforcement: which writes are actually stopped -----------------------------------------------


def test_a_stale_precondition_stops_the_write() -> None:
    """The wiring, not just the payload. Every assertion above is about what a `409` *contains*, and
    all of them still pass against an ``enforce_precondition`` that never raises one."""
    note = stored_note()

    with pytest.raises(HTTPException) as raised:
        enforce_precondition(
            FakeSession(), note, update(body="mine", if_updated_at=CREATED_AT)
        )

    assert raised.value.status_code == 409
    assert error(raised.value)["code"] == "note_conflict"


def test_a_matching_precondition_lets_the_write_through() -> None:
    """The other half. An implementation that refuses everything passes the test above."""
    payload = update(body="mine", if_updated_at=STORED_AT)

    assert enforce_precondition(FakeSession(), stored_note(), payload) is None


def test_an_unguarded_write_is_neither_stopped_nor_locked() -> None:
    """A write that omits the precondition is specified to be a plain overwrite, so it must not pay
    for one either — locking the row would serialise exactly the callers who opted out."""
    session = FakeSession()

    assert enforce_precondition(session, stored_note(), update(body="mine")) is None
    assert enforce_precondition(session, stored_note(), update(title="renamed")) is None
    assert session.locks == [], "an unguarded write took a row lock it does not need"


def test_the_row_is_re_read_under_a_lock_before_the_comparison() -> None:
    """The guard's own blind spot, in the fast layer.

    ``note`` was loaded earlier in this transaction. If the comparison trusts that copy, two writers
    who both read before either committed each compare against their own stale snapshot, both pass,
    and the second silently overwrites the first — the exact loss this module exists to prevent,
    living inside the guard against it. So: a session whose re-read reports somebody else's commit
    must produce a `409` even though the in-memory value matched.
    """
    note = stored_note()
    someone_else_committed = STORED_AT + timedelta(seconds=5)

    def commit_by_another_writer(instance: Note) -> None:
        instance.updated_at = someone_else_committed
        instance.body = "theirs"

    session = FakeSession(on_refresh=commit_by_another_writer)

    with pytest.raises(HTTPException) as raised:
        enforce_precondition(session, note, update(body="mine", if_updated_at=STORED_AT))

    assert session.locks == [True], "the re-read must take the row lock"
    assert error(raised.value)["stored"].body == "theirs", "the diff shows what is really there"
    assert error(raised.value)["stored"].updated_at == someone_else_committed


# --- The microsecond round trip -------------------------------------------------------------------


def test_the_token_survives_serialization_to_the_microsecond() -> None:
    """Out as JSON, and the microseconds are all still there.

    Asserted on the serialized string rather than on the model, because the loss this guards against
    happens *at* serialization and a model-to-model comparison would never see it.
    """
    serialized = NoteRead.of(stored_note()).model_dump(mode="json")["updated_at"]

    assert "123456" in serialized, serialized
    assert datetime.fromisoformat(serialized) == STORED_AT


def test_the_token_survives_parsing_back_to_the_microsecond() -> None:
    """And in again. This is the half that decides whether a correct write is accepted."""
    printed = NoteRead.of(stored_note()).model_dump(mode="json")["updated_at"]

    parsed = update(body="mine", if_updated_at=printed).if_updated_at

    assert parsed == STORED_AT
    assert parsed.microsecond == 123456


def test_one_microsecond_of_drift_is_a_mismatch_and_not_a_rounding_error() -> None:
    """The comparison is exact on purpose. A tolerance would be indistinguishable from the bug: it
    would let a genuinely stale precondition through whenever the two writes were close together,
    which is exactly when two writers are racing."""
    stored = stored_note().updated_at

    assert stored != STORED_AT - ONE_MICROSECOND
    assert stored != STORED_AT + ONE_MICROSECOND
    assert stored == STORED_AT


def test_the_same_instant_in_another_offset_matches() -> None:
    """Two aware datetimes compare as instants, so a client that re-serializes the token through a
    local timezone is not punished for it. What is compared is the moment, not the spelling."""
    in_singapore = STORED_AT.astimezone(timezone(timedelta(hours=8)))

    assert in_singapore.isoformat() != STORED_AT.isoformat()
    assert update(body="mine", if_updated_at=in_singapore).if_updated_at == stored_note().updated_at


def test_a_naive_precondition_is_refused_rather_than_guessed_at() -> None:
    """A `422` naming the field, not an assumption of UTC.

    An offset guessed wrong shifts the token by hours, so it never matches again and the caller sees
    a permanent `409` with no way to act on it. Comparing a naive value against the aware one from
    Postgres is not an option either — Python raises, and a `500` is a worse answer than both.
    """
    with pytest.raises(ValidationError) as raised:
        update(body="mine", if_updated_at="2026-08-07T10:11:12.123456")

    assert "if_updated_at" in str(raised.value)


def test_an_explicit_null_precondition_is_refused_rather_than_read_as_omitted() -> None:
    """The way a client produces ``null`` here is a bug — a template that always emits the key, with
    the timestamp it meant to send missing. Reading it charitably would silently downgrade that
    client to last-write-wins, which is the prose loss ADR 0009 exists to close, applied to the one
    caller who asked not to have it."""
    with pytest.raises(ValidationError) as raised:
        update(body="mine", if_updated_at=None)

    assert "if_updated_at" in str(raised.value)


def test_an_unknown_precondition_spelling_is_refused_rather_than_ignored() -> None:
    """``extra="forbid"`` earns its keep here more than anywhere else: a client that sends
    ``updated_at`` instead of ``if_updated_at`` would otherwise be silently unguarded — it would
    believe it had the guarantee, and would be wrong in the direction that loses work."""
    with pytest.raises(ValidationError):
        update(body="mine", updated_at=STORED_AT.isoformat())
