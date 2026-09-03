"""ADR 0002's step 5: the `404`/`403` split, and the `WHERE` that scopes a list.

Both functions are pure, so this whole file runs with no database and no framework. That is not an
accident of the implementation — it is why ``authorize_note`` takes a ``Note`` instead of a session
and an identifier, and why ``notes_owned_by`` returns a statement instead of rows.

The scoping assertions are made against the **compiled statement**, because that is where the claim
lives. "Returns only my notes" is satisfied by a Python filter over everything, and SLICES §V1 asks
for something stronger: the other user's note is never fetched. Only the SQL can say which happened.
``tests/integration/test_owner_scoped_lists.py`` then runs the same statement against a real
Postgres holding both users' notes.
"""

import uuid

import pytest
from fakes import ALICE, BOB
from fastapi import HTTPException
from sqlalchemy import Select

from app.auth.authorization import authorize_note, notes_owned_by
from app.auth.principal import Principal
from app.models import Note


def note_owned_by(principal: Principal, *, title: str = "a note") -> Note:
    """A detached ``Note``. No session: nothing here needs one, which is the point."""
    return Note(id=1, ref="NOTE-1", owner_id=principal.id, title=title, body="", path="")


# --- One note: the 404/403 split ----------------------------------------------------------------


def test_the_owner_gets_the_very_note_back() -> None:
    """Returned rather than merely permitted, so the check sits on the path to the value."""
    mine = note_owned_by(ALICE)

    assert authorize_note(ALICE, mine) is mine


def test_an_absent_note_is_a_404() -> None:
    with pytest.raises(HTTPException) as raised:
        authorize_note(ALICE, None)

    assert raised.value.status_code == 404
    assert raised.value.detail["error"]["code"] == "note_not_found"


def test_someone_elses_note_is_a_403_and_deliberately_not_a_404() -> None:
    """The decided behaviour, stated as a test because it is the one that looks like a leak.

    A `403` tells the caller the note exists. ADR 0002 §"The resolver", PLAN §Authorization and
    SLICES §V1 all name `403` explicitly, so a later "hardening" to a blanket `404` is a change to
    the contract and should fail here rather than pass quietly.
    """
    theirs = note_owned_by(BOB)

    with pytest.raises(HTTPException) as raised:
        authorize_note(ALICE, theirs)

    assert raised.value.status_code == 403
    assert raised.value.status_code != 404
    assert raised.value.detail["error"]["code"] == "note_forbidden"


def test_the_two_refusals_carry_different_codes() -> None:
    """`404` and `403` are two different facts; one code for both would erase the distinction the
    split exists to make."""
    codes = []
    for note in (None, note_owned_by(BOB)):
        with pytest.raises(HTTPException) as raised:
            authorize_note(ALICE, note)
        codes.append(raised.value.detail["error"]["code"])

    assert len(set(codes)) == 2, f"both refusals answered {codes[0]}"


def test_the_404_body_cannot_vary_with_how_the_note_was_addressed() -> None:
    """ADR 0008's identical-error-code requirement, met one layer below where it is asked for.

    KAN-536 owns the guard that `NOTE-9999` and `9999` return the same code. This function is what
    makes that guard easy to satisfy: it never sees an identifier, so there is nothing in the body
    that *could* differ between the two spellings — not the code, not even the message.
    """
    with pytest.raises(HTTPException) as raised:
        authorize_note(ALICE, None)

    rendered = repr(raised.value.detail)
    assert "NOTE" not in rendered
    assert not any(character.isdigit() for character in rendered)


def test_a_refusal_does_not_disclose_the_owner() -> None:
    """The `403` gives up that the note exists. It must not also give up whose it is."""
    theirs = note_owned_by(BOB, title="bob's private planning note")

    with pytest.raises(HTTPException) as raised:
        authorize_note(ALICE, theirs)

    rendered = repr(raised.value.detail)
    assert BOB.email not in rendered
    assert str(BOB.id) not in rendered
    assert theirs.title not in rendered


def test_ownership_is_the_uuid_and_nothing_else() -> None:
    """Pandan owns the email and may change it mid-session; the UUID is the identity (ADR 0002)."""
    renamed = Principal(id=ALICE.id, email="alice.newname@example.com")

    mine = note_owned_by(ALICE)

    assert authorize_note(renamed, mine) is mine


# --- ADR 0011/R16.3: the team-default rung -------------------------------------------------------

PLATFORM_TEAM_ID = 501
DESIGN_TEAM_ID = 502


def team_note(*, title: str = "a team note") -> Note:
    """A detached note owned by Bob and shared with the Platform team."""
    note = note_owned_by(BOB, title=title)
    note.team_id = PLATFORM_TEAM_ID
    return note


def test_a_team_member_reaches_a_teammates_team_shared_note() -> None:
    shared = team_note()

    assert authorize_note(ALICE, shared, frozenset({PLATFORM_TEAM_ID})) is shared


def test_the_owner_still_gets_their_own_team_note_back_with_no_team_ids_at_all() -> None:
    """The owner check runs first and never needs team_ids — the default `frozenset()` is enough
    for the note's own owner, exactly as it always was."""
    shared = team_note()

    assert authorize_note(BOB, shared) is shared


def test_no_team_ids_on_a_team_note_is_still_a_403() -> None:
    """The default (`frozenset()`) reproduces pre-R16 behaviour exactly: a caller who is not the
    owner and supplies no team_ids is refused, whether that's because they belong to no team or
    because ADR 0011's soft-fail decided pandan couldn't say."""
    shared = team_note()

    with pytest.raises(HTTPException) as raised:
        authorize_note(ALICE, shared)

    assert raised.value.status_code == 403


def test_membership_in_a_different_team_grants_nothing() -> None:
    shared = team_note()

    with pytest.raises(HTTPException) as raised:
        authorize_note(ALICE, shared, frozenset({DESIGN_TEAM_ID}))

    assert raised.value.status_code == 403


def test_a_personal_note_is_unaffected_by_team_ids() -> None:
    """`note.team_id is None` short-circuits the team rung entirely — team_ids naming every team
    in existence still would not grant access to a note that was never shared."""
    personal = note_owned_by(BOB)

    with pytest.raises(HTTPException) as raised:
        authorize_note(ALICE, personal, frozenset({PLATFORM_TEAM_ID, DESIGN_TEAM_ID}))

    assert raised.value.status_code == 403


def test_team_default_access_is_never_a_404() -> None:
    """A team note a caller cannot reach is exactly the "somebody else's note" case — `403`, the
    existence-revealing refusal ADR 0002/PLAN §Authorization already chose, never a `404`."""
    shared = team_note()

    with pytest.raises(HTTPException) as raised:
        authorize_note(ALICE, shared)

    assert raised.value.status_code != 404


# --- Many notes: the WHERE ----------------------------------------------------------------------


def compiled(statement: Select[tuple[Note]]) -> tuple[str, dict[str, object]]:
    compiled_statement = statement.compile()
    return str(compiled_statement), dict(compiled_statement.params)


def test_a_list_query_is_scoped_in_sql_rather_than_after_the_fact() -> None:
    sql, params = compiled(notes_owned_by(ALICE))

    assert "WHERE note.owner_id = " in sql
    assert ALICE.id in params.values(), "the caller's UUID is the bound value, not a literal"


def test_two_callers_get_two_different_statements() -> None:
    """Cheap, and it catches the copy-paste where the scoping binds a fixture instead of the arg."""
    _, alice = compiled(notes_owned_by(ALICE))
    _, bob = compiled(notes_owned_by(BOB))

    assert ALICE.id in alice.values()
    assert BOB.id in bob.values()
    assert ALICE.id not in bob.values()


def test_composing_onto_the_statement_cannot_lose_the_scoping() -> None:
    """The reason this returns a ``Select``. A route adds a search term, an ordering and a page;
    none of those can remove a clause that is already on the statement.

    The owner clause is parenthesised once a second ``.where()`` ANDs onto it (ADR 0011's ``OR``
    needs the parens to keep its precedence), so this checks for the clause rather than for
    ``WHERE`` immediately preceding it — the same property, tolerant of the wrapping.
    """
    paged = (
        notes_owned_by(ALICE)
        .where(Note.title.ilike("%meeting%"))
        .order_by(Note.updated_at.desc())
        .limit(50)
    )

    sql, params = compiled(paged)

    assert "note.owner_id = " in sql
    assert ALICE.id in params.values()
    assert "LIMIT" in sql


def test_the_scoping_does_not_depend_on_the_principal_being_mirrored_yet() -> None:
    """A ``Principal`` is whatever pandan said (ADR 0002); no local row is consulted to scope."""
    stranger = Principal(id=uuid.uuid4(), email="never-seen@example.com")

    _, params = compiled(notes_owned_by(stranger))

    assert stranger.id in params.values()
