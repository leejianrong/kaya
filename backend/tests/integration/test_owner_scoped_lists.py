"""``notes_visible_to`` against a real Postgres 17 holding two users' notes.

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

INSERT_ACCOUNT = text(
    "INSERT INTO kaya_account (id, email, hashed_password, is_active, is_superuser, is_verified) "
    "VALUES (:id, :email, 'not-a-real-hash', true, false, false)"
)
INSERT_NOTE = text("INSERT INTO note (owner_id, title) VALUES (:owner_id, :title)")
COUNT_NOTES = text("SELECT count(*) FROM note")

# ADR 0017: a workspace, its members, and a note in it. `workspace_member.role` is `viewer`,
# `editor` or `owner`; a note's `workspace_id` is a `RESTRICT` foreign key.
INSERT_WORKSPACE = text("INSERT INTO workspace (id, name) VALUES (:id, 'Platform')")
INSERT_MEMBER = text(
    "INSERT INTO workspace_member (workspace_id, user_id, role) "
    "VALUES (:workspace_id, :user_id, :role)"
)
INSERT_WORKSPACE_NOTE = text(
    "INSERT INTO note (owner_id, title, workspace_id) VALUES (:owner_id, :title, :workspace_id)"
)
PLATFORM_ID = 501
TRUNCATE = text("TRUNCATE TABLE note, kaya_account, workspace CASCADE")


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
            session.execute(TRUNCATE)
            session.commit()

    empty()
    with factory() as session:
        session.execute(INSERT_ACCOUNT, {"id": ALICE_ID, "email": "alice@example.com"})
        session.execute(INSERT_ACCOUNT, {"id": BOB_ID, "email": "bob@example.com"})
        session.execute(INSERT_NOTE, {"owner_id": ALICE_ID, "title": "alice on kaya"})
        session.execute(INSERT_NOTE, {"owner_id": ALICE_ID, "title": "alice on pandan"})
        session.execute(INSERT_NOTE, {"owner_id": BOB_ID, "title": "bob on kaya"})
        session.commit()

    with factory() as session:
        yield session

    empty()


@pytest.fixture
def alice_and_bob_with_a_workspace_note(database_url: str) -> Iterator[Any]:
    """Alice owns a personal note and wrote a note in the Platform workspace; she is its `owner`,
    Bob is not a member.

    A separate fixture rather than rows added to `two_users_with_notes`, so the base fixture's own
    counts (used by tests that predate workspaces) stay exactly what they were.
    """
    from alembic import command

    from app.db import get_sessionmaker

    command.upgrade(_alembic_config(), "head")
    factory = get_sessionmaker()

    def empty() -> None:
        with factory() as session:
            session.execute(TRUNCATE)
            session.commit()

    empty()
    with factory() as session:
        session.execute(INSERT_ACCOUNT, {"id": ALICE_ID, "email": "alice@example.com"})
        session.execute(INSERT_ACCOUNT, {"id": BOB_ID, "email": "bob@example.com"})
        session.execute(INSERT_WORKSPACE, {"id": PLATFORM_ID})
        session.execute(
            INSERT_MEMBER, {"workspace_id": PLATFORM_ID, "user_id": ALICE_ID, "role": "owner"}
        )
        session.execute(INSERT_NOTE, {"owner_id": ALICE_ID, "title": "alice's personal note"})
        session.execute(
            INSERT_WORKSPACE_NOTE,
            {"owner_id": ALICE_ID, "title": "alice's workspace note", "workspace_id": PLATFORM_ID},
        )
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
    from app.auth.authorization import notes_visible_to

    session = two_users_with_notes
    alice = _principal(ALICE_ID, "alice@example.com")

    titles = sorted(note.title for note in session.scalars(notes_visible_to(alice)))

    assert session.execute(COUNT_NOTES).scalar_one() == 3, "bob's note must actually be there"
    assert titles == ["alice on kaya", "alice on pandan"]
    assert all(note.owner_id == ALICE_ID for note in session.scalars(notes_visible_to(alice)))


def test_a_search_term_matching_only_the_other_users_note_returns_nothing(
    two_users_with_notes: Any,
) -> None:
    """The shape KAN-536's search will take, and where an unscoped query looks most convincing.

    "kaya" matches all three notes. Alice's page must be her two; a query that filtered afterwards
    would have loaded Bob's prose to do it, and one that forgot to filter would leak it outright.
    """
    from app.auth.authorization import notes_visible_to
    from app.models import Note

    session = two_users_with_notes
    alice = _principal(ALICE_ID, "alice@example.com")
    bob = _principal(BOB_ID, "bob@example.com")

    matching = notes_visible_to(alice).where(Note.title.ilike("%kaya%"))
    only_bobs = notes_visible_to(alice).where(Note.title.ilike("%bob%"))

    assert [note.title for note in session.scalars(matching)] == ["alice on kaya"]
    assert list(session.scalars(only_bobs)) == []
    assert [note.title for note in session.scalars(notes_visible_to(bob))] == ["bob on kaya"]


def test_a_user_with_no_notes_is_the_only_empty_list(two_users_with_notes: Any) -> None:
    """The empty page is a real answer for a real caller, which is why it must not also be the
    answer somebody else's note produces."""
    from app.auth.authorization import notes_visible_to

    session = two_users_with_notes
    stranger = _principal(uuid.uuid4(), "nobody@example.com")

    assert list(session.scalars(notes_visible_to(stranger))) == []
    assert session.execute(COUNT_NOTES).scalar_one() == 3


def test_the_authorized_read_of_one_note_still_tells_403_from_404(
    two_users_with_notes: Any,
) -> None:
    """``authorize_note`` over rows that came from Postgres rather than a constructor.

    The unit tests build detached ``Note`` objects; this checks the same split holds when `owner_id`
    has been round-tripped through the database as a real `uuid` column.
    """
    from fastapi import HTTPException

    from app.auth.authorization import authorize_note, notes_visible_to

    session = two_users_with_notes
    alice = _principal(ALICE_ID, "alice@example.com")
    bob = _principal(BOB_ID, "bob@example.com")

    (bobs_note,) = list(session.scalars(notes_visible_to(bob)))

    assert authorize_note(bob, bobs_note) is bobs_note

    with pytest.raises(HTTPException) as forbidden:
        authorize_note(alice, bobs_note)
    assert forbidden.value.status_code == 403

    with pytest.raises(HTTPException) as absent:
        authorize_note(alice, None)
    assert absent.value.status_code == 404


# --- ADR 0017: workspace access, against real rows ----------------------------------------------


def _add_member(session: Any, user_id: uuid.UUID, role: str) -> None:
    session.execute(
        INSERT_MEMBER, {"workspace_id": PLATFORM_ID, "user_id": user_id, "role": role}
    )
    session.commit()


def test_a_workspace_note_appears_in_a_members_list_and_only_theirs(
    alice_and_bob_with_a_workspace_note: Any,
) -> None:
    from app.auth.authorization import notes_visible_to

    session = alice_and_bob_with_a_workspace_note
    alice = _principal(ALICE_ID, "alice@example.com")
    bob = _principal(BOB_ID, "bob@example.com")

    assert sorted(n.title for n in session.scalars(notes_visible_to(bob))) == []

    _add_member(session, BOB_ID, "viewer")

    assert sorted(n.title for n in session.scalars(notes_visible_to(bob))) == [
        "alice's workspace note"
    ], "bob sees the workspace note and not alice's personal one"
    assert sorted(n.title for n in session.scalars(notes_visible_to(alice))) == [
        "alice's personal note",
        "alice's workspace note",
    ]


def test_leaving_a_workspace_takes_the_notes_you_wrote_there_with_you(
    alice_and_bob_with_a_workspace_note: Any,
) -> None:
    """ADR 0017: `owner_id` grants nothing in a workspace. Alice created the note, then her
    membership is removed, and it is no longer in her list: access is the membership."""
    from app.auth.authorization import notes_visible_to

    session = alice_and_bob_with_a_workspace_note
    alice = _principal(ALICE_ID, "alice@example.com")

    session.execute(text("DELETE FROM workspace_member WHERE user_id = :u"), {"u": ALICE_ID})
    session.commit()

    assert sorted(n.title for n in session.scalars(notes_visible_to(alice))) == [
        "alice's personal note"
    ]


def test_authorize_note_follows_the_role_over_a_real_row(
    alice_and_bob_with_a_workspace_note: Any,
) -> None:
    from fastapi import HTTPException

    from app.auth.authorization import Access, authorize_note, notes_visible_to, workspace_role_of

    session = alice_and_bob_with_a_workspace_note
    alice = _principal(ALICE_ID, "alice@example.com")
    bob = _principal(BOB_ID, "bob@example.com")
    (shared,) = [
        n for n in session.scalars(notes_visible_to(alice)) if n.title == "alice's workspace note"
    ]

    def role_of(who: Any) -> str | None:
        return session.scalars(workspace_role_of(who, shared.workspace_id)).one_or_none()

    assert role_of(bob) is None
    with pytest.raises(HTTPException) as stranger:
        authorize_note(bob, shared, Access.READ, role_of(bob))
    assert stranger.value.status_code == 403, "a non-member is refused, never told 404"

    _add_member(session, BOB_ID, "viewer")
    assert authorize_note(bob, shared, Access.READ, role_of(bob)) is shared
    with pytest.raises(HTTPException) as too_low:
        authorize_note(bob, shared, Access.WRITE, role_of(bob))
    assert too_low.value.status_code == 403, "a viewer may read but not write"

    session.execute(
        text("UPDATE workspace_member SET role = 'editor' WHERE user_id = :u"), {"u": BOB_ID}
    )
    session.commit()
    assert authorize_note(bob, shared, Access.WRITE, role_of(bob)) is shared
