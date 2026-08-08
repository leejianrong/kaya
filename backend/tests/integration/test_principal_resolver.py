"""The resolver against a real Postgres 17, with only pandan faked.

The unit layer already covers the cache arithmetic and the status codes. What needs a database is
the one step that has one: the just-in-time mirror. Specifically, that it is *idempotent* — the
resolver calls it on every cache miss, not only on a user's first ever request, so "creates the
row" and "does not fail the second time" are two different claims and only the second one needs
Postgres to check.

Everything reaches the resolver through an ordinary HTTP request, so the assertions cover
Starlette's `Authorization` parsing and the JSON error bodies as well as the resolution itself.
Pandan is faked at the seam ADR 0002 already required; no real PAT exists anywhere in this suite.

**No `import app.*` at module top** — see the package docstring. The fake below imports inside its
method body for exactly that reason: it is a module-level class, so an import at its top would run
at collection, before the fixture sets `DATABASE_URL`.
"""

import threading
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Any

import pytest
from sqlalchemy import text

BACKEND_ROOT = Path(__file__).resolve().parents[2]

# Shapeless on purpose: kaya has no token format, so a PAT-shaped fixture would quietly assert the
# opposite of the thing under test (and trip scripts/secret-scan.sh, which is working as intended).
TOKEN = "a-caller-supplied-string-kaya-does-not-parse"
STRAY = "something-a-scanner-put-in-an-authorization-header"

ALICE_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
ALICE_EMAIL = "alice@example.com"

COUNT_USERS = text('SELECT count(*) FROM "user"')  # `user` is reserved; quote it, always.


class FakeClock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeUpstream:
    """Pandan, faked at the HTTP boundary, counting every call."""

    def __init__(self) -> None:
        self.known: dict[str, Any] = {}
        self.available = True
        self.calls: list[str] = []

    def introspect(self, bearer: str) -> Any:
        from app.auth.principal import UpstreamUnavailable  # PR #17 trap; see module docstring

        self.calls.append(bearer)
        if not self.available:
            raise UpstreamUnavailable("https://pandan.invalid/api/v1/me is unreachable")
        return self.known.get(bearer)

    @property
    def call_count(self) -> int:
        return len(self.calls)


def _alembic_config() -> Any:
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


@pytest.fixture
def migrated(database_url: str) -> Iterator[None]:
    """The schema at head, and an empty `user` table on both sides of the test.

    Emptied on the way *in* as well as out, which is not belt-and-braces. Every assertion below is
    a count of mirror rows, and `tests/integration/test_migration_0001.py` inserts users of its own
    and leaves them — so without this, "creates exactly one row" fails with a number that reads
    like a bug in the mirror and is really the neighbouring file. Emptied on the way out too, so
    this file is not the one doing that to somebody else.
    """
    from alembic import command

    from app.db import get_sessionmaker

    command.upgrade(_alembic_config(), "head")

    def empty_the_mirror() -> None:
        with get_sessionmaker()() as session:
            session.execute(text('TRUNCATE TABLE "user" CASCADE'))
            session.commit()

    empty_the_mirror()
    try:
        yield
    finally:
        empty_the_mirror()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def upstream() -> FakeUpstream:
    return FakeUpstream()


@pytest.fixture
def alice(upstream: FakeUpstream) -> Any:
    """Teaches the fake upstream about one caller. Separate from `upstream` because the tests
    about stray headers want an upstream that knows nobody."""
    from app.auth.principal import Principal

    principal = Principal(id=ALICE_ID, email=ALICE_EMAIL)
    upstream.known[TOKEN] = principal
    return principal


@pytest.fixture
def session(migrated: None) -> Iterator[Any]:
    from app.db import get_sessionmaker

    with get_sessionmaker()() as opened:
        yield opened


@pytest.fixture
def client(session: Any, upstream: FakeUpstream, clock: FakeClock) -> Iterator[Any]:
    """A one-route app standing in for `/api/v1`, which does not exist yet (KAN-536).

    The route is a stub; the dependency under it is the real one, wired to a real mirror over a
    real session. Only the upstream and the clock are substituted.
    """
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    from app.auth.cache import PrincipalCache
    from app.auth.dependencies import get_principal, get_resolver
    from app.auth.mirror import SqlAlchemyPrincipalMirror
    from app.auth.principal import Principal
    from app.auth.resolver import PrincipalResolver

    resolver = PrincipalResolver(
        upstream=upstream,
        mirror=SqlAlchemyPrincipalMirror(session),
        cache=PrincipalCache(positive_ttl=60.0, negative_ttl=10.0, clock=clock),
    )

    app = FastAPI()

    @app.get("/whoami")
    def whoami(principal: Annotated[Principal, Depends(get_principal)]) -> dict[str, str]:
        return {"id": str(principal.id), "email": principal.email}

    app.dependency_overrides[get_resolver] = lambda: resolver
    with TestClient(app) as test_client:
        yield test_client


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- The mirror ---------------------------------------------------------------------------------


@pytest.mark.usefixtures("alice")
def test_a_first_seen_uuid_gets_exactly_one_mirror_row_and_reuses_it(
    client: Any, session: Any, upstream: FakeUpstream
) -> None:
    first = client.get("/whoami", headers=_auth(TOKEN))
    second = client.get("/whoami", headers=_auth(TOKEN))

    assert first.status_code == 200
    assert first.json() == {"id": str(ALICE_ID), "email": ALICE_EMAIL}
    assert second.json() == first.json()

    assert session.execute(COUNT_USERS).scalar_one() == 1
    assert upstream.call_count == 1, "the second request was served from the cache"


@pytest.mark.usefixtures("alice")
def test_mirroring_again_after_the_cache_lapses_does_not_duplicate_or_fail(
    client: Any, session: Any, clock: FakeClock, upstream: FakeUpstream
) -> None:
    """The claim that actually needs Postgres.

    Step 4 runs on *every* cache miss, so the second insert is a real conflict on a real primary
    key. A read-then-insert mirror passes the test above and raises `IntegrityError` here.
    """
    client.get("/whoami", headers=_auth(TOKEN))
    created_at = session.execute(text('SELECT created_at FROM "user"')).scalar_one()

    clock.advance(61)
    again = client.get("/whoami", headers=_auth(TOKEN))

    assert again.status_code == 200
    assert upstream.call_count == 2, "the cache really did lapse — otherwise this proves nothing"
    assert session.execute(COUNT_USERS).scalar_one() == 1
    assert session.execute(text('SELECT created_at FROM "user"')).scalar_one() == created_at


@pytest.mark.usefixtures("migrated")
def test_a_racing_first_insert_does_not_break_the_slower_caller(alice: Any) -> None:
    """Two agents, one cold cache, one user who has never been seen. Postgres settles it.

    Staged rather than thrashed. A pool of threads all calling `ensure` looks like a race test and
    is not one: whether any two of them actually overlap is up to the scheduler, so it passes
    against a read-then-insert mirror most of the time — verified, which is why it is not the test
    that ended up here.

    This version forces the interleaving. The leader inserts and **holds the transaction open**, so
    the row exists and is invisible to everyone else. The follower then runs the real `ensure`,
    which is the exact state a read-then-insert cannot survive: its `SELECT` sees nothing, its
    `INSERT` blocks on the primary key index, and the moment the leader commits it gets a unique
    violation — on somebody's very first request, which is the worst possible moment to raise.
    """
    from app.auth.mirror import SqlAlchemyPrincipalMirror
    from app.db import get_sessionmaker

    factory = get_sessionmaker()
    outcome: dict[str, Any] = {}

    def follow() -> None:
        with factory() as own:
            try:
                SqlAlchemyPrincipalMirror(own).ensure(alice)
                outcome["ok"] = True
            except Exception as exc:  # noqa: BLE001 — the point is *which* exception, if any
                outcome["error"] = repr(exc)

    with factory() as leader:
        leader.execute(
            text('INSERT INTO "user" (id, email) VALUES (:id, :email)'),
            {"id": alice.id, "email": alice.email},
        )
        # Deliberately not committed. The row is real and nobody else can see it.

        follower = threading.Thread(target=follow)
        follower.start()
        # Long enough for the follower to reach its INSERT and block on the index. If it has not,
        # the test passes for a weaker reason rather than flaking — it never reports a false
        # failure, which is the property that matters for something living in the slow layer.
        time.sleep(0.5)
        leader.commit()

    follower.join(timeout=10)
    assert not follower.is_alive(), "the follower never came back — it is stuck behind the leader"
    assert outcome == {"ok": True}

    with factory() as verifier:
        assert verifier.execute(COUNT_USERS).scalar_one() == 1


# --- Revocation, and the negative cache ---------------------------------------------------------


@pytest.mark.usefixtures("alice")
def test_a_revoked_token_stops_working_once_the_cache_entry_expires(
    client: Any, upstream: FakeUpstream, clock: FakeClock
) -> None:
    assert client.get("/whoami", headers=_auth(TOKEN)).status_code == 200

    upstream.known.pop(TOKEN)  # revoked in pandan, mid-session

    still_cached = client.get("/whoami", headers=_auth(TOKEN))
    assert still_cached.status_code == 200, "Q6's revocation lag, up to the TTL and no longer"

    clock.advance(61)
    revoked = client.get("/whoami", headers=_auth(TOKEN))

    assert revoked.status_code == 401
    assert revoked.json()["detail"]["error"]["code"] == "invalid_token"


def test_a_stray_authorization_header_costs_no_upstream_call_on_the_second_attempt(
    client: Any, upstream: FakeUpstream, session: Any
) -> None:
    """The negative cache doing the job a prefix check would have been reached for.

    Kaya cannot look at the header and know it is rubbish — pandan answers 401 identically for a
    malformed token and a revoked one — so it asks once and then remembers the answer for 10s.
    """
    responses = [client.get("/whoami", headers=_auth(STRAY)) for _ in range(4)]

    assert [r.status_code for r in responses] == [401, 401, 401, 401]
    assert upstream.call_count == 1
    assert session.execute(COUNT_USERS).scalar_one() == 0, "a rejection never reaches the mirror"


def test_the_negative_cache_lapses_so_a_freshly_minted_token_is_not_stuck(
    client: Any, upstream: FakeUpstream, clock: FakeClock, alice: Any
) -> None:
    assert client.get("/whoami", headers=_auth(STRAY)).status_code == 401

    upstream.known[STRAY] = alice  # the PAT gets minted a moment later

    clock.advance(9)
    assert client.get("/whoami", headers=_auth(STRAY)).status_code == 401

    clock.advance(2)
    assert client.get("/whoami", headers=_auth(STRAY)).status_code == 200


# --- Pandan down --------------------------------------------------------------------------------


@pytest.mark.usefixtures("alice")
def test_an_unseen_token_gets_a_503_naming_the_upstream_while_a_cached_one_still_works(
    client: Any, upstream: FakeUpstream, clock: FakeClock
) -> None:
    """V1's demo, as a test: stop pandan, and a cached token keeps working.

    The `503` is Q9 and the one status worth being loud about — a `401` here would send a client
    into a token-rotation loop over an outage it cannot fix.
    """
    assert client.get("/whoami", headers=_auth(TOKEN)).status_code == 200

    upstream.available = False

    clock.advance(30)
    assert client.get("/whoami", headers=_auth(TOKEN)).status_code == 200

    cold = client.get("/whoami", headers=_auth("a-token-this-process-has-never-seen"))

    assert cold.status_code == 503
    assert cold.status_code != 401
    error = cold.json()["detail"]["error"]
    assert error["code"] == "upstream_unavailable"
    assert error["upstream"] == "pandan"
    assert cold.headers["Retry-After"] == "5"


def test_a_missing_authorization_header_is_a_401_in_the_documented_shape(client: Any) -> None:
    unauthenticated = client.get("/whoami")

    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["detail"]["error"]["code"] == "authentication_required"
    assert unauthenticated.headers["WWW-Authenticate"] == "Bearer"


def test_a_non_bearer_scheme_is_refused_without_asking_pandan(
    client: Any, upstream: FakeUpstream
) -> None:
    """Basic auth is not a thing kaya has; it must not become an upstream round trip either."""
    refused = client.get("/whoami", headers={"Authorization": "Basic dXNlcjpwYXNz"})

    assert refused.status_code == 401
    assert upstream.call_count == 0


@pytest.mark.usefixtures("alice")
def test_no_response_ever_echoes_the_token(client: Any, upstream: FakeUpstream) -> None:
    """Every path a token can take out of the app, checked in one place."""
    upstream.available = False
    bodies = [
        client.get("/whoami").text,
        client.get("/whoami", headers=_auth(STRAY)).text,
        client.get("/whoami", headers=_auth(TOKEN)).text,
    ]

    for body in bodies:
        assert TOKEN not in body
        assert STRAY not in body
