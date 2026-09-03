"""ADR 0011/R16.3, end to end: real routes, real Postgres, real HTTP — both pandan upstreams faked.

``test_owner_scoped_lists.py`` proves the SQL; ``test_note_authorization.py`` proves the pure
function. This file is the third leg: that `note_from_ref` and `list_notes` actually call
`TeamAccessResolver` and act on what it returns, over the wire, the way a caller would see it.

There is no `POST /api/v1/notes` support for `team_id` yet (R16.5, `KAN-1086`) — the team-shared
note below is inserted directly, the same way `tests/integration/test_owner_scoped_lists.py` does,
and only the read paths go through the real HTTP client.
"""

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

BACKEND_ROOT = Path(__file__).resolve().parents[2]

ALICE_TOKEN = "a-caller-supplied-string-kaya-does-not-parse"
BOB_TOKEN = "a-different-caller-supplied-string"
ALICE_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
BOB_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
PLATFORM_TEAM_ID = 501

NOTES = "/api/v1/notes"

INSERT_TEAM = text("INSERT INTO team (id) VALUES (:id)")
INSERT_TEAM_NOTE = text(
    "INSERT INTO note (owner_id, title, team_id) VALUES (:owner_id, :title, :team_id) RETURNING ref"
)


class FakeIdentityUpstream:
    """Pandan's identity endpoint, faked — same shape as `test_notes_api.py`'s."""

    def __init__(self) -> None:
        self.known: dict[str, Any] = {}

    def introspect(self, bearer: str) -> Any:
        return self.known.get(bearer)


class FakeTeamUpstream:
    """Pandan's `GET /api/v1/teams`, faked — a bearer maps to the team ids its owner belongs to."""

    def __init__(self) -> None:
        self.known: dict[str, frozenset[int]] = {}
        self.calls: list[str] = []

    def member_teams(self, bearer: str) -> frozenset[int]:
        self.calls.append(bearer)
        return self.known.get(bearer, frozenset())


def _alembic_config() -> Any:
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


@pytest.fixture
def identity_upstream() -> FakeIdentityUpstream:
    return FakeIdentityUpstream()


@pytest.fixture
def team_upstream() -> FakeTeamUpstream:
    return FakeTeamUpstream()


@pytest.fixture
def client(
    database_url: str, identity_upstream: FakeIdentityUpstream, team_upstream: FakeTeamUpstream
) -> Iterator[Any]:
    """The real app, with both of pandan's endpoints swapped for fakes — identity (ADR 0002) and
    team membership (ADR 0011) are two different upstreams, two different overrides, mirroring how
    `app/auth/`'s two resolvers never share a cache or a single-flight registry."""
    from typing import Annotated

    from alembic import command
    from fastapi import Depends
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from app.auth.cache import PrincipalCache
    from app.auth.dependencies import get_resolver, get_team_access_resolver, reset_auth
    from app.auth.mirror import SqlAlchemyPrincipalMirror
    from app.auth.resolver import PrincipalResolver
    from app.auth.single_flight import SingleFlight
    from app.auth.team_cache import TeamMembershipCache
    from app.auth.team_resolver import TeamAccessResolver
    from app.db import get_session, get_sessionmaker
    from app.main import app

    command.upgrade(_alembic_config(), "head")

    def empty() -> None:
        with get_sessionmaker()() as session:
            session.execute(text('TRUNCATE TABLE note, "user", team CASCADE'))
            session.commit()

    empty()
    reset_auth()
    cache = PrincipalCache(positive_ttl=60.0, negative_ttl=10.0)
    single_flight = SingleFlight()
    team_cache = TeamMembershipCache(positive_ttl=60.0, negative_ttl=10.0)
    team_single_flight = SingleFlight()

    def resolver(session: Annotated[Session, Depends(get_session)]) -> PrincipalResolver:
        return PrincipalResolver(
            upstream=identity_upstream,
            mirror=SqlAlchemyPrincipalMirror(session),
            cache=cache,
            single_flight=single_flight,
        )

    def team_resolver() -> TeamAccessResolver:
        return TeamAccessResolver(
            upstream=team_upstream,
            cache=team_cache,
            single_flight=team_single_flight,
        )

    app.dependency_overrides[get_resolver] = resolver
    app.dependency_overrides[get_team_access_resolver] = team_resolver
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        reset_auth()
        empty()


@pytest.fixture
def alice(identity_upstream: FakeIdentityUpstream) -> Any:
    from app.auth.principal import Principal

    principal = Principal(id=ALICE_ID, email="alice@example.com")
    identity_upstream.known[ALICE_TOKEN] = principal
    return principal


@pytest.fixture
def bob(identity_upstream: FakeIdentityUpstream) -> Any:
    from app.auth.principal import Principal

    principal = Principal(id=BOB_ID, email="bob@example.com")
    identity_upstream.known[BOB_TOKEN] = principal
    return principal


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def alices_team_note(client: Any, alice: Any) -> str:
    """A note owned by Alice and shared with the Platform team, inserted directly (R16.5 is what
    teaches `POST /api/v1/notes` to do this over HTTP). Returns its `NOTE-n` ref.

    Alice's ``user`` row does not exist until something mirrors it (`app/auth/mirror.py`'s
    just-in-time insert, run from a real request) — a raw `INSERT` before any request has
    authenticated as her would violate `note.owner_id`'s foreign key. A throwaway `POST` earns the
    mirror row the same way `test_notes_api.py`'s `create` helper does it implicitly — a `POST`
    rather than a `GET /notes`, deliberately: the list route always calls `TeamAccessResolver`
    (`app/api/notes.py`'s `list_notes`), and a call made here would already be sitting in
    ``team_upstream.calls`` before a test's own assertions run.
    """
    from app.db import get_sessionmaker

    assert (
        client.post(NOTES, json={"title": "throwaway"}, headers=auth(ALICE_TOKEN)).status_code
        == 201
    )

    with get_sessionmaker()() as session:
        session.execute(INSERT_TEAM, {"id": PLATFORM_TEAM_ID})
        ref = session.execute(
            INSERT_TEAM_NOTE,
            {"owner_id": ALICE_ID, "title": "alice's team note", "team_id": PLATFORM_TEAM_ID},
        ).scalar_one()
        session.commit()
    return ref


@pytest.mark.usefixtures("alice", "bob")
def test_a_team_member_reaches_a_teammates_team_shared_note_over_http(
    client: Any, team_upstream: FakeTeamUpstream, alices_team_note: str
) -> None:
    team_upstream.known[BOB_TOKEN] = frozenset({PLATFORM_TEAM_ID})

    response = client.get(f"{NOTES}/{alices_team_note}", headers=auth(BOB_TOKEN))

    assert response.status_code == 200, response.text
    assert response.json()["title"] == "alice's team note"


@pytest.mark.usefixtures("alice", "bob")
def test_no_membership_is_a_403_over_http_never_a_404(
    client: Any, team_upstream: FakeTeamUpstream, alices_team_note: str
) -> None:
    # bob is not in team_upstream.known at all -- an empty answer, exactly ADR 0011's soft-fail
    # shape for "pandan could not be asked" and "genuinely not a member" alike.
    response = client.get(f"{NOTES}/{alices_team_note}", headers=auth(BOB_TOKEN))

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "note_forbidden"


@pytest.mark.usefixtures("alice", "bob")
def test_the_owner_never_pays_for_a_team_check_on_their_own_note(
    client: Any, team_upstream: FakeTeamUpstream, alices_team_note: str
) -> None:
    """The lazy-check property (`app/api/refs.py`'s `resolve_note`): the owner path never calls
    `TeamAccessResolver` at all, so it is unaffected by what pandan's teams endpoint would say."""
    response = client.get(f"{NOTES}/{alices_team_note}", headers=auth(ALICE_TOKEN))

    assert response.status_code == 200, response.text
    assert team_upstream.calls == [], "the owner's own read must never reach the team upstream"


@pytest.mark.usefixtures("alice", "bob")
def test_a_team_note_appears_in_a_members_list_and_not_a_strangers(
    client: Any,
    identity_upstream: FakeIdentityUpstream,
    team_upstream: FakeTeamUpstream,
    alices_team_note: str,
) -> None:
    """Two distinct callers, deliberately, rather than one bearer's membership flipped mid-test —
    `TeamMembershipCache`'s positive TTL means a revocation would not show up until it lapses
    (`test_team_resolver.py` already covers that timing), and this test is not about timing."""
    from app.auth.principal import Principal

    carol_token = "yet-another-caller-supplied-string"
    identity_upstream.known[carol_token] = Principal(id=uuid.uuid4(), email="carol@example.com")
    team_upstream.known[BOB_TOKEN] = frozenset({PLATFORM_TEAM_ID})
    # carol is a real, resolvable caller who belongs to no team at all.

    bobs_view = client.get(NOTES, headers=auth(BOB_TOKEN))
    assert bobs_view.status_code == 200, bobs_view.text
    assert [note["title"] for note in bobs_view.json()["notes"]] == ["alice's team note"]

    carols_view = client.get(NOTES, headers=auth(carol_token))
    assert carols_view.json()["notes"] == []
