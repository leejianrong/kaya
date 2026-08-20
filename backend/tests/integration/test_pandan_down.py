"""R5.1: with pandan completely stopped, a note still saves, renders, and is searchable.

ADR 0003's line, restated as SLICES §V5's own acceptance criterion (its wording, verbatim): "the
note saves, renders, and appears in full-text search; the link renders unresolved with a hint and
nothing returns an error." This is the guard the card asks for, and the card asks for it loudly on
purpose — CLAUDE.md's framing is that this is exactly the kind of degradation guard that passes for
the wrong reason, so it is written to be mutated and watched failing (see the PR description for
the mutation actually run).

**The one subtlety that makes or breaks this file: ADR 0002's identity exception.** Authentication
is the one place kaya is *allowed* to depend on pandan — a bearer this process has never seen has to
be introspected against pandan's `GET /api/v1/me` before kaya knows who is asking, and that call
cannot succeed with pandan down. What ADR 0003 forbids is everything *after* identity is settled:
note save, note read, wikilink reconciliation, full-text search. So every test below **warms the
principal cache first, with pandan reachable**, then flips pandan off, and only then drives the
note verbs — all with the *same* bearer, and all within the cache's positive TTL
(`app/auth/cache.py`'s `PrincipalCache`, default 60s here). A test that instead handed a
never-authenticated bearer to a stopped pandan and expected `200`s would misrepresent the actual,
accepted guarantee — that is not what this file asserts, and the boundary test at the bottom checks
the honest edge of it: a bearer this cache has never warmed still gets a `503` (never a false
`401`) once pandan is down, and a *warmed* bearer degrades the same way once its cache entry lapses.
That second half is what stops this file from telling only the flattering side of the story.

The clock is injected (`app/auth/cache.py`'s `clock: Callable[[], float]`) so the TTL boundary is
asserted deterministically rather than by a real `sleep` — see dev-playbook §3 and this repo's own
convention against slow, eventually-flaky tests.

Wikilink reconciliation (`app/note_links.py`, `app/wikilinks.py`) and full-text search
(`app/auth/authorization.py`'s `notes_matching`, `app/api/search.py`) make **no network call at
all**, today or ever, by design (see both modules' docstrings) —
`app/integrations/card_resolution.py` exists and is fully wired to a cache and a resolver, but
nothing in `app/api/notes.py` or `app/api/search.py` calls it yet (that wiring is KAN-566, not this
card). So the honest claim this file can make is narrower than "kaya never depends on pandan for
anything": it is "the code paths
that exist today, and are meant to survive KAN-566 landing beside them, do not call pandan a second
time once the caller is known" — which is exactly SLICES §V4/§V5's promise and exactly what a future
card wiring a blocking call into `create_note`, `get_note` or `notes_matching` would break first.

**No `import app.*` at module top** — see the package docstring, and pandan's PR #17 trap: a
top-level `app` import runs at collection, before the `database_url` fixture sets `DATABASE_URL`.
"""

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

BACKEND_ROOT = Path(__file__).resolve().parents[2]

# Shapeless on purpose: kaya has no token format (ADR 0002), so a PAT-shaped fixture would quietly
# assert the opposite of the thing under test.
ALICE_TOKEN = "a-caller-supplied-string-kaya-does-not-parse"
ALICE_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")

# A bearer nobody ever warms the cache for. Used only in the boundary test, and never taught to the
# fake upstream, so it is cold by construction rather than by omission.
COLD_TOKEN = "a-token-this-process-has-never-seen-before"

NOTES = "/api/v1/notes"


class FakeClock:
    """Same shape as `test_principal_resolver.py`'s — injected so the TTL boundary is exact rather
    than timed."""

    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeUpstream:
    """Pandan, faked at the HTTP boundary (ADR 0002's Protocol seam).

    `available = False` is a **stopped process**, not a rejected credential: `introspect` raises
    `UpstreamUnavailable` rather than returning `None`. Returning `None` for an outage is the exact
    bug `app/auth/principal.py`'s docstring warns about — it would surface as a `401` and read as
    "your token is bad" when pandan is simply not there to ask. `test_principal_resolver.py` already
    establishes this is the right fake for an outage; this file reuses the same shape rather than
    inventing a second one.
    """

    def __init__(self) -> None:
        self.known: dict[str, Any] = {}
        self.available = True

    def introspect(self, bearer: str) -> Any:
        from app.auth.principal import UpstreamUnavailable  # PR #17 trap; see module docstring

        if not self.available:
            raise UpstreamUnavailable("https://pandan.invalid/api/v1/me is unreachable")
        return self.known.get(bearer)


def _alembic_config() -> Any:
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def upstream() -> FakeUpstream:
    return FakeUpstream()


@pytest.fixture
def client(database_url: str, upstream: FakeUpstream, clock: FakeClock) -> Iterator[Any]:
    """The real app (`app.main.app`) with only `get_resolver` overridden — same pattern as
    `test_notes_api.py`'s `client` fixture, with one addition: the `PrincipalCache` here takes the
    injected `clock`, which is what lets the boundary test move time without a real `sleep`.

    A fresh cache per test, for the reason `test_notes_api.py` gives: the cache is process-wide by
    design, and one surviving a `TRUNCATE` would serve a principal whose mirror row no longer
    exists.
    """
    from typing import Annotated

    from alembic import command
    from fastapi import Depends
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from app.auth.cache import PrincipalCache
    from app.auth.dependencies import get_resolver, reset_auth
    from app.auth.mirror import SqlAlchemyPrincipalMirror
    from app.auth.resolver import PrincipalResolver
    from app.auth.single_flight import SingleFlight
    from app.db import get_session, get_sessionmaker
    from app.main import app

    command.upgrade(_alembic_config(), "head")

    def empty() -> None:
        with get_sessionmaker()() as session:
            session.execute(text('TRUNCATE TABLE note_link, note, "user" CASCADE'))
            session.commit()

    empty()
    reset_auth()
    cache = PrincipalCache(positive_ttl=60.0, negative_ttl=10.0, clock=clock)
    single_flight = SingleFlight()

    def resolver(session: Annotated[Session, Depends(get_session)]) -> PrincipalResolver:
        return PrincipalResolver(
            upstream=upstream,
            mirror=SqlAlchemyPrincipalMirror(session),
            cache=cache,
            single_flight=single_flight,
        )

    app.dependency_overrides[get_resolver] = resolver
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        reset_auth()
        empty()


@pytest.fixture
def alice(upstream: FakeUpstream) -> Any:
    from app.auth.principal import Principal

    principal = Principal(id=ALICE_ID, email="alice@example.com")
    upstream.known[ALICE_TOKEN] = principal
    return principal


def auth(token: str = ALICE_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create(client: Any, token: str = ALICE_TOKEN, **fields: str) -> dict[str, Any]:
    fields.setdefault("title", "a note")
    response = client.post(NOTES, json=fields, headers=auth(token))
    assert response.status_code == 201, response.text
    return response.json()


def warm(client: Any, token: str = ALICE_TOKEN) -> None:
    """One successful call while pandan is reachable — this is what puts a positive entry in the
    principal cache, which is the whole precondition the rest of a test relies on."""
    response = client.get(NOTES, headers=auth(token))
    assert response.status_code == 200, response.text


# --- The demo, end to end: create, read, edit, delete, search, all with pandan stopped ------------


@pytest.mark.usefixtures("alice")
def test_full_note_crud_and_search_survive_pandan_being_completely_down(
    client: Any, upstream: FakeUpstream
) -> None:
    """SLICES §V5's end-to-end row, word for word: "the note saves, renders, and appears in
    full-text search ... and nothing returns an error." **[mutate]**

    Structure: warm the cache with pandan up, then stop pandan, then do every note verb an agent
    would actually do — create, read, edit under ADR 0009's precondition, move, search, delete —
    with the *same* already-authenticated bearer. If any of these needed a second trip to pandan,
    every assertion below would 503 instead of succeeding, because `upstream.available` never goes
    back to `True` in this test.
    """
    warm(client, ALICE_TOKEN)
    upstream.available = False

    created = create(
        client,
        ALICE_TOKEN,
        title="a runbook",
        body="see [[KAN-501]] and [[EPIC-9]] for context",
        path="ops/runbook.md",
    )
    assert created["ref"].startswith("NOTE-")

    read = client.get(f"{NOTES}/{created['ref']}", headers=auth(ALICE_TOKEN))
    assert read.status_code == 200
    assert read.json() == created

    edited = client.patch(
        f"{NOTES}/{created['ref']}",
        json={"body": "revised, still see [[KAN-501]]", "if_updated_at": created["updated_at"]},
        headers=auth(ALICE_TOKEN),
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["body"] == "revised, still see [[KAN-501]]"

    moved = client.patch(
        f"{NOTES}/{created['ref']}",
        json={"path": "archive/runbook.md"},
        headers=auth(ALICE_TOKEN),
    )
    assert moved.status_code == 200, moved.text

    found = client.get(NOTES, params={"q": "runbook"}, headers=auth(ALICE_TOKEN))
    assert found.status_code == 200, found.text
    assert [note["ref"] for note in found.json()["notes"]] == [created["ref"]]

    deleted = client.delete(f"{NOTES}/{created['ref']}", headers=auth(ALICE_TOKEN))
    assert deleted.status_code == 204

    assert client.get(f"{NOTES}/{created['ref']}", headers=auth(ALICE_TOKEN)).status_code == 404


@pytest.mark.usefixtures("alice")
def test_wikilink_reconciliation_writes_local_rows_with_pandan_down(
    client: Any, upstream: FakeUpstream
) -> None:
    """`app/note_links.py` and `app/wikilinks.py` both promise, in their own docstrings, to make no
    network call ever — this is the end-to-end proof that the promise survives contact with a
    stopped pandan, for both halves the module handles: a pandan-shaped ref (`[[KAN-501]]`, left
    unresolved, `resolved_id IS NULL`) and a note-to-note title link that resolves **locally**
    against another note already in the database.
    """
    warm(client, ALICE_TOKEN)

    target = create(client, ALICE_TOKEN, title="Target Note", body="nothing special")

    upstream.available = False

    linking = create(
        client,
        ALICE_TOKEN,
        title="Linking note",
        body="mentions [[KAN-501]] and links to [[Target Note]]",
    )
    assert linking["ref"].startswith("NOTE-")

    from sqlalchemy import select

    from app.db import get_sessionmaker
    from app.models.note import Note
    from app.models.note_link import NoteLink

    with get_sessionmaker()() as session:
        source_id = session.execute(
            text("SELECT id FROM note WHERE ref = :ref"), {"ref": linking["ref"]}
        ).scalar_one()
        rows = session.scalars(
            select(NoteLink).where(NoteLink.source_note_id == source_id)
        ).all()

        by_kind = {row.target_kind: row for row in rows}
        assert set(by_kind) == {"KAN", "NOTE"}
        assert by_kind["KAN"].target_ref == "KAN-501"
        assert by_kind["KAN"].resolved_id is None, "a pandan ref stays unresolved with pandan down"

        target_id = session.execute(
            text("SELECT id FROM note WHERE ref = :ref"), {"ref": target["ref"]}
        ).scalar_one()
        assert by_kind["NOTE"].target_ref == "Target Note"
        assert by_kind["NOTE"].resolved_id == target_id, (
            "note-to-note resolution is a local SELECT and must not need pandan"
        )
        # And Note itself never crossed into an ORM query built outside app/auth/authorization.py.
        assert session.get(Note, source_id) is not None


# --- The identity exception, honestly bounded -----------------------------------------------------


@pytest.mark.usefixtures("alice")
def test_a_cold_bearer_gets_503_while_a_cache_warmed_one_still_works(
    client: Any, upstream: FakeUpstream, clock: FakeClock
) -> None:
    """ADR 0002's exception, stated as a test rather than only as prose.

    Authentication is the one place kaya may depend on pandan: a bearer this process has never seen
    genuinely cannot be resolved with pandan down, and that is `503` (Q9), never a `401` that would
    send a client into a token-rotation loop over an outage it cannot fix. A bearer that was already
    resolved while pandan was up keeps working from the cache, within its TTL, with no further
    pandan involvement at all — which is the property every test above actually relies on, made
    explicit here on its own.
    """
    warm(client, ALICE_TOKEN)

    upstream.available = False
    clock.advance(30)  # still inside the 60s positive TTL

    still_warm = client.get(NOTES, headers=auth(ALICE_TOKEN))
    assert still_warm.status_code == 200, "a cache hit must not need pandan"

    cold = client.get(NOTES, headers=auth(COLD_TOKEN))
    assert cold.status_code == 503
    assert cold.status_code != 401, "an outage must never be reported as a bad credential"
    error = cold.json()["error"]
    assert error["code"] == "upstream_unavailable"
    assert cold.headers["Retry-After"] == "5"


@pytest.mark.usefixtures("alice")
def test_the_positive_cache_lapsing_with_pandan_still_down_is_a_503_not_a_false_401(
    client: Any, upstream: FakeUpstream, clock: FakeClock
) -> None:
    """The other half of the honest boundary: this file does not claim kaya never needs pandan, only
    that it does not need pandan *again* while the caller is already known. Once the cache entry
    itself lapses, the same bearer needs pandan exactly as much as a bearer it has never seen — so
    the correct answer is `503` (pandan is down, ask again later), and the wrong answer a sloppier
    implementation could produce is `401` (this looks like a bad credential), which is precisely the
    failure Q9 exists to rule out.
    """
    warm(client, ALICE_TOKEN)
    upstream.available = False

    clock.advance(61)  # past the 60s positive TTL

    lapsed = client.get(NOTES, headers=auth(ALICE_TOKEN))
    assert lapsed.status_code == 503, "a lapsed cache entry needs pandan again, honestly"
    assert lapsed.json()["error"]["code"] == "upstream_unavailable"
