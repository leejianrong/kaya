"""``notes_owned_by`` against a real Postgres 17 holding two users' notes.

The unit layer asserts that the ``WHERE`` is on the statement. What it cannot assert is that the
clause does what it says once Postgres has it, and the property SLICES §V1 actually asks for is
about rows: another user's note is **omitted**, not returned-then-hidden. That needs a database
with somebody else's note in it, which is precisely the thing a developer's machine never has.

Every assertion below is paired with a check that the other user's note exists at all. A scoping
test against an empty table is the classic pass-for-the-wrong-reason, and it is the same failure
mode as the empty-list-for-a-scoped-query behaviour the card exists to rule out.

**No `import app.*` at module top** — see the package docstring (pandan's PR #17 trap).
"""

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

BACKEND_ROOT = Path(__file__).resolve().parents[2]

ALICE_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
BOB_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")

# `user` is reserved in Postgres; every hand-written statement against it quotes the name.
INSERT_USER = text('INSERT INTO "user" (id, email) VALUES (:id, :email)')
INSERT_NOTE = text("INSERT INTO note (owner_id, title) VALUES (:owner_id, :title)")
COUNT_NOTES = text("SELECT count(*) FROM note")


def _alembic_config() -> Any:
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


@pytest.fixture
def two_users_with_notes(database_url: str) -> Iterator[Any]:
    """Alice with two notes, Bob with one, on a schema at head.

    Emptied on the way in as well as out: the neighbouring migration test inserts notes of its own
    and leaves them, and every count below would then be reporting on that file instead of this one.
    """
    from alembic import command

    from app.db import get_sessionmaker

    command.upgrade(_alembic_config(), "head")
    factory = get_sessionmaker()

    def empty() -> None:
        with factory() as session:
            session.execute(text('TRUNCATE TABLE note, "user" CASCADE'))
            session.commit()

    empty()
    with factory() as session:
        session.execute(INSERT_USER, {"id": ALICE_ID, "email": "alice@example.com"})
        session.execute(INSERT_USER, {"id": BOB_ID, "email": "bob@example.com"})
        session.execute(INSERT_NOTE, {"owner_id": ALICE_ID, "title": "alice on kaya"})
        session.execute(INSERT_NOTE, {"owner_id": ALICE_ID, "title": "alice on pandan"})
        session.execute(INSERT_NOTE, {"owner_id": BOB_ID, "title": "bob on kaya"})
        session.commit()

    with factory() as session:
        yield session

    empty()


def _principal(user_id: uuid.UUID, email: str) -> Any:
    from app.auth.principal import Principal

    return Principal(id=user_id, email=email)


def test_another_users_note_is_omitted_rather_than_returned_and_filtered(
    two_users_with_notes: Any,
) -> None:
    from app.auth.authorization import notes_owned_by

    session = two_users_with_notes
    alice = _principal(ALICE_ID, "alice@example.com")

    titles = sorted(note.title for note in session.scalars(notes_owned_by(alice)))

    assert session.execute(COUNT_NOTES).scalar_one() == 3, "bob's note must actually be there"
    assert titles == ["alice on kaya", "alice on pandan"]
    assert all(note.owner_id == ALICE_ID for note in session.scalars(notes_owned_by(alice)))


def test_a_search_term_matching_only_the_other_users_note_returns_nothing(
    two_users_with_notes: Any,
) -> None:
    """The shape KAN-536's search will take, and where an unscoped query looks most convincing.

    "kaya" matches all three notes. Alice's page must be her two; a query that filtered afterwards
    would have loaded Bob's prose to do it, and one that forgot to filter would leak it outright.
    """
    from app.auth.authorization import notes_owned_by
    from app.models import Note

    session = two_users_with_notes
    alice = _principal(ALICE_ID, "alice@example.com")
    bob = _principal(BOB_ID, "bob@example.com")

    matching = notes_owned_by(alice).where(Note.title.ilike("%kaya%"))
    only_bobs = notes_owned_by(alice).where(Note.title.ilike("%bob%"))

    assert [note.title for note in session.scalars(matching)] == ["alice on kaya"]
    assert list(session.scalars(only_bobs)) == []
    assert [note.title for note in session.scalars(notes_owned_by(bob))] == ["bob on kaya"]


def test_a_user_with_no_notes_is_the_only_empty_list(two_users_with_notes: Any) -> None:
    """The empty page is a real answer for a real caller, which is why it must not also be the
    answer somebody else's note produces."""
    from app.auth.authorization import notes_owned_by

    session = two_users_with_notes
    stranger = _principal(uuid.uuid4(), "nobody@example.com")

    assert list(session.scalars(notes_owned_by(stranger))) == []
    assert session.execute(COUNT_NOTES).scalar_one() == 3


def test_the_authorized_read_of_one_note_still_tells_403_from_404(
    two_users_with_notes: Any,
) -> None:
    """``authorize_note`` over rows that came from Postgres rather than a constructor.

    The unit tests build detached ``Note`` objects; this checks the same split holds when `owner_id`
    has been round-tripped through the database as a real `uuid` column.
    """
    from fastapi import HTTPException

    from app.auth.authorization import authorize_note, notes_owned_by

    session = two_users_with_notes
    alice = _principal(ALICE_ID, "alice@example.com")
    bob = _principal(BOB_ID, "bob@example.com")

    (bobs_note,) = list(session.scalars(notes_owned_by(bob)))

    assert authorize_note(bob, bobs_note) is bobs_note

    with pytest.raises(HTTPException) as forbidden:
        authorize_note(alice, bobs_note)
    assert forbidden.value.status_code == 403

    with pytest.raises(HTTPException) as absent:
        authorize_note(alice, None)
    assert absent.value.status_code == 404
