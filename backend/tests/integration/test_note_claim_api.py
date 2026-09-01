"""``PUT /api/v1/notes/{ref}`` against a real Postgres — R12/KAN-1061's ref-preservation route
(``app/api/note_claim.py``).

This is the piece the first cut of R12 (KAN-1060..1063) shipped without, on the theory that "no new
backend route" was this round's scope. It was the maintainer's own planning gap, not a real
constraint — ADR 0008 §Decision commits to it explicitly ("an import re-uses \\[the ref\\] when
free"), and skipping it means a re-imported note breaks every ``[[NOTE-n]]`` wikilink still pointing
at it elsewhere. This file is the proof it now works, end to end, against the same database the
production sequence guarantee (``tests/integration/test_migration_0001.py``) is proven against.

**No ``import app.*`` at module top** — see the package docstring, and pandan's PR #17 trap.
"""

import re
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

BACKEND_ROOT = Path(__file__).resolve().parents[2]

ALICE_TOKEN = "a-caller-supplied-string-kaya-does-not-parse"
ALICE_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")

BOB_TOKEN = "a-different-callers-string-kaya-also-does-not-parse"
BOB_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")

NOTES = "/api/v1/notes"
REF_PATTERN = re.compile(r"^NOTE-(\d+)$")

READ_VERSIONS = text(
    "SELECT id, body FROM note_version WHERE note_id = :note_id ORDER BY created_at DESC, id DESC"
)
READ_LINKS = text(
    "SELECT target_kind, target_ref, resolved_id FROM note_link WHERE source_note_id = :note_id"
)
SEQUENCE_LAST_VALUE = text("SELECT last_value FROM note_ref_seq")

INSERT_USER = text('INSERT INTO "user" (id, email) VALUES (:id, :email) ON CONFLICT DO NOTHING')
INSERT_NOTE_ORDINARY = text(
    "INSERT INTO note (owner_id, title) VALUES (:owner_id, :title) RETURNING ref"
)
INSERT_NOTE_EXPLICIT_REF = text(
    "INSERT INTO note (owner_id, ref, title) VALUES (:owner_id, :ref, :title) "
    "ON CONFLICT (ref) DO NOTHING RETURNING ref"
)


class FakeUpstream:
    """Pandan, faked at the HTTP boundary (ADR 0002's Protocol seam). Kaya holds no credential."""

    def __init__(self) -> None:
        self.known: dict[str, Any] = {}

    def introspect(self, bearer: str) -> Any:
        return self.known.get(bearer)


def _alembic_config() -> Any:
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


@pytest.fixture
def upstream() -> FakeUpstream:
    return FakeUpstream()


@pytest.fixture
def engine(database_url: str) -> Any:
    """The schema at head, for reading ``note_link``/``note_version``/the sequence directly."""
    from alembic import command

    from app.db import get_engine

    command.upgrade(_alembic_config(), "head")
    return get_engine()


@pytest.fixture
def migrated_engine(database_url: str) -> Any:
    """The schema at head, for the raw-connection concurrency test below — the same guarantee
    ``engine`` gives, spelled separately so that test does not have to pull in the `client`/
    `upstream` machinery it never touches, matching
    ``tests/integration/test_migration_0001.py``'s ``migrated`` fixture."""
    from alembic import command

    from app.db import get_engine

    command.upgrade(_alembic_config(), "head")
    return get_engine()


@pytest.fixture
def client(database_url: str, upstream: FakeUpstream) -> Iterator[Any]:
    """The real app with pandan swapped out, exactly as ``test_notes_api.py`` builds it."""
    from typing import Annotated

    from alembic import command
    from fastapi import Depends
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from app.auth.cache import PrincipalCache
    from app.auth.dependencies import get_resolver, reset_auth
    from app.auth.mirror import SqlAlchemyPrincipalMirror
    from app.auth.principal import Principal
    from app.auth.resolver import PrincipalResolver
    from app.auth.single_flight import SingleFlight
    from app.db import get_session, get_sessionmaker
    from app.main import app

    command.upgrade(_alembic_config(), "head")

    def empty() -> None:
        with get_sessionmaker()() as session:
            session.execute(text('TRUNCATE TABLE note, "user" CASCADE'))
            session.commit()

    empty()
    reset_auth()
    upstream.known[ALICE_TOKEN] = Principal(id=ALICE_ID, email="alice@example.com")
    upstream.known[BOB_TOKEN] = Principal(id=BOB_ID, email="bob@example.com")
    cache = PrincipalCache(positive_ttl=60.0, negative_ttl=10.0)
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


def auth(token: str = ALICE_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create(client: Any, *, token: str = ALICE_TOKEN, **fields: str) -> dict[str, Any]:
    fields.setdefault("title", "a note")
    response = client.post(NOTES, json=fields, headers=auth(token))
    assert response.status_code == 201, response.text
    return response.json()


def claim(client: Any, ref: str, *, token: str = ALICE_TOKEN, **fields: str) -> Any:
    fields.setdefault("title", "claimed")
    return client.put(f"{NOTES}/{ref}", json=fields, headers=auth(token))


def number_of(ref: str) -> int:
    match = REF_PATTERN.match(ref)
    assert match, f"{ref} is not NOTE-n"
    return int(match.group(1))


def next_free_ref(engine: Any) -> str:
    """A ref this test has certainly not used yet — read fresh, right before using it.

    A hardcoded high number (``NOTE-999001``) is *not* safe across this file's own tests: the
    `client` fixture truncates `note` between tests but a `TRUNCATE` never touches the sequence
    (`app/models/note.py`'s whole point), and this file's own claims deliberately advance it. So a
    fixed constant collides with whatever an *earlier* test in this file already claimed or
    created. ``last_value + 1`` is exactly the number an ordinary create would get right now, which
    is free by definition — nothing has claimed it yet."""
    with engine.connect() as connection:
        current = connection.execute(SEQUENCE_LAST_VALUE).scalar_one()
    return f"NOTE-{current + 1}"


# -------------------------------------------------------- the headline: export, delete, import


@pytest.mark.usefixtures("upstream")
def test_reclaiming_a_deleted_notes_ref_gives_it_back(client: Any) -> None:
    """The literal round trip: create, note the ref, delete, import (claim) the same file back.

    This is ADR 0008 §Decision's sentence made true rather than aspirational — "an import re-uses
    \\[the ref\\] when free" — and the scenario every real `note export` / `note delete` /
    `note import` sequence actually produces: the ref was legitimately allocated once, so it can
    only be *behind* the sequence by the time it is reclaimed, never ahead of it (see the sequence-
    bump tests below for the case where it can be ahead).
    """
    original = create(client, title="Groceries", body="milk\neggs", path="home/groceries.md")
    ref = original["ref"]

    deleted = client.delete(f"{NOTES}/{ref}", headers=auth())
    assert deleted.status_code == 204, deleted.text

    # The exported front matter is title/body/path; the ref comes back from the file's own
    # `kaya_ref` line and is what kaya-client sends as the URL, per `app/api/note_claim.py`.
    response = claim(client, ref, title="Groceries", body="milk\neggs", path="home/groceries.md")
    assert response.status_code == 201, response.text
    reclaimed = response.json()

    assert reclaimed["ref"] == ref, "the whole point: the same ref came back"
    assert reclaimed["id"] != original["id"], "a new row, not the deleted one resurrected"
    assert reclaimed["title"] == "Groceries"
    assert reclaimed["body"] == "milk\neggs"
    assert reclaimed["path"] == "home/groceries.md"

    # And the note is genuinely reachable through the ordinary ref-resolved routes afterward —
    # not a one-off response that doesn't stick.
    reread = client.get(f"{NOTES}/{ref}", headers=auth())
    assert reread.status_code == 200
    assert reread.json() == reclaimed


# --------------------------------------------------------------------------------- the happy path


@pytest.mark.usefixtures("upstream")
def test_claim_creates_a_note_with_the_given_content(client: Any, engine: Any) -> None:
    ref = next_free_ref(engine)
    response = claim(client, ref, title="Imported", body="body text", path="vault/note.md")
    assert response.status_code == 201, response.text
    note = response.json()
    assert note["ref"] == ref
    assert note["title"] == "Imported"
    assert note["body"] == "body text"
    assert note["path"] == "vault/note.md"


@pytest.mark.usefixtures("upstream")
def test_claim_sets_the_location_header_to_the_claimed_ref(client: Any, engine: Any) -> None:
    ref = next_free_ref(engine)
    response = claim(client, ref, title="x")
    assert response.headers["location"] == f"{NOTES}/{ref}"


@pytest.mark.usefixtures("upstream")
def test_claim_reconciles_wikilinks_and_cuts_a_version(client: Any, engine: Any) -> None:
    """The claimed note gets exactly what `create_note` gives an ordinary note: a `note_link` row
    for its own `[[Title]]`, and one `note_version` row — nothing bespoke, per R12's own wording.
    """
    target = create(client, title="Target Note")

    response = claim(
        client, next_free_ref(engine), title="Linker", body=f"See [[{target['title']}]]."
    )
    assert response.status_code == 201, response.text
    linker = response.json()

    with engine.connect() as connection:
        links = list(connection.execute(READ_LINKS, {"note_id": linker["id"]}))
        versions = list(connection.execute(READ_VERSIONS, {"note_id": linker["id"]}))

    assert len(links) == 1
    assert links[0].target_kind == "NOTE"
    assert links[0].resolved_id == target["id"], "resolved forward, same as an ordinary create"
    assert len(versions) == 1
    assert versions[0].body == f"See [[{target['title']}]]."


@pytest.mark.usefixtures("upstream")
def test_claim_resolves_a_pending_link_waiting_for_this_title(client: Any, engine: Any) -> None:
    """KAN-563's *backward* resolution: a note created earlier with an unresolved `[[Title]]`
    matching this claim's title gets pointed at it — the exact "unresolved-then-resolves-once-the-
    target-lands" case a corpus import relies on, now proven for the claim path too.
    """
    waiting = create(client, title="Waiting", body="See [[Not Yet]].")

    response = claim(client, next_free_ref(engine), title="Not Yet")
    assert response.status_code == 201, response.text
    landed = response.json()

    with engine.connect() as connection:
        links = list(connection.execute(READ_LINKS, {"note_id": waiting["id"]}))

    assert len(links) == 1
    assert links[0].resolved_id == landed["id"]


# ------------------------------------------------------------------------------ refusals


@pytest.mark.usefixtures("upstream")
def test_claim_refuses_a_ref_already_taken(client: Any) -> None:
    taken = create(client, title="Already here")

    response = claim(client, taken["ref"], title="Squatter")
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["error"]["code"] == "ref_taken"
    assert body["error"]["ref"] == taken["ref"]

    # And nothing about the existing note moved.
    reread = client.get(f"{NOTES}/{taken['ref']}", headers=auth())
    assert reread.json()["title"] == "Already here"


@pytest.mark.usefixtures("upstream")
def test_claim_refuses_a_ref_taken_by_someone_else(client: Any) -> None:
    """A ref is a global name, per ADR 0008 — `authorize_note`'s 403/404 split is about *reading*
    someone else's note, not about whether their ref is available for a stranger to claim."""
    bobs = create(client, token=BOB_TOKEN, title="bob's")

    response = claim(client, bobs["ref"], title="alice's attempt", token=ALICE_TOKEN)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "ref_taken"


@pytest.mark.usefixtures("upstream")
def test_claim_refuses_a_bare_integer(client: Any) -> None:
    """Deliberately narrower than every other ref-taking route: there is no existing row for a bare
    integer to be a second spelling *of* — see `app/api/note_claim.py`'s docstring."""
    response = claim(client, "999005", title="x")
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "invalid_note_ref"


@pytest.mark.usefixtures("upstream")
def test_claim_refuses_a_malformed_ref(client: Any) -> None:
    from urllib.parse import quote

    response = client.put(
        f"{NOTES}/{quote('#NOTE-1', safe='')}", json={"title": "x"}, headers=auth()
    )
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "invalid_note_ref"


@pytest.mark.usefixtures("upstream")
def test_claim_requires_a_credential(client: Any) -> None:
    response = client.put(f"{NOTES}/NOTE-999006", json={"title": "x"})
    assert response.status_code == 401


@pytest.mark.usefixtures("upstream")
def test_claim_still_validates_the_body(client: Any) -> None:
    """The body is a plain ``NoteCreate`` — same schema, same validation — as the ordinary route."""
    response = claim(client, "NOTE-999007", title="")
    assert response.status_code == 422, response.text


# ------------------------------------------------------------ the sequence bump, deterministically


@pytest.mark.usefixtures("upstream")
def test_claiming_a_ref_ahead_of_the_sequence_advances_it_forward(
    client: Any, engine: Any
) -> None:
    """The edge case a well-behaved import never hits (a ref no deployment's sequence has ever
    reached) but this route still has to survive: claim `current + 50`, then prove an *ordinary*
    create afterward never reaches back into the range this just claimed.
    """
    with engine.connect() as connection:
        current = connection.execute(SEQUENCE_LAST_VALUE).scalar_one()

    far_ahead = current + 50
    response = claim(client, f"NOTE-{far_ahead}", title="from the future")
    assert response.status_code == 201, response.text

    afterward = create(client, title="ordinary, afterward")
    assert number_of(afterward["ref"]) > far_ahead, (
        "an ordinary create landed inside the range the claim just took — the sequence did not "
        "advance past it, so this write was one nextval() away from a duplicate ref"
    )


@pytest.mark.usefixtures("upstream")
def test_claiming_a_ref_behind_the_sequence_does_not_move_it_backward(
    client: Any, engine: Any
) -> None:
    """The realistic case (a reclaimed, previously-allocated ref) must not perturb the sequence at
    all — moving it *backward* is the one way this feature could reintroduce a future duplicate.
    """
    early = create(client, title="early")
    for _ in range(5):
        create(client, title="filler")
    deleted = client.delete(f"{NOTES}/{early['ref']}", headers=auth())
    assert deleted.status_code == 204

    with engine.connect() as connection:
        before = connection.execute(SEQUENCE_LAST_VALUE).scalar_one()

    reclaimed = claim(client, early["ref"], title="reclaimed, behind the sequence")
    assert reclaimed.status_code == 201, reclaimed.text

    with engine.connect() as connection:
        after = connection.execute(SEQUENCE_LAST_VALUE).scalar_one()
    assert after == before, "reclaiming an old, low ref must not touch the sequence at all"

    next_ordinary = create(client, title="ordinary, right after")
    assert number_of(next_ordinary["ref"]) > number_of(early["ref"])


# ------------------------------------------------------------------- the race, made deterministic


@pytest.mark.usefixtures("upstream")
def test_an_ordinary_create_that_wins_the_ref_first_leaves_a_clean_409_for_the_claim(
    client: Any,
) -> None:
    """One concrete interleaving of "an ordinary create and a claim want the same ref", sequenced
    by hand rather than by real threads (the deterministic style
    `tests/integration/test_migration_0001.py::test_a_rolled_back_insert_never_lends_its_ref_to_the_next_writer`
    uses for the same reason: a real race is flaky to assert on, an ordering is not). The ordinary
    writer's `nextval()` commits first; the claim for that exact ref, arriving after, must refuse
    cleanly rather than either succeeding (which would be an outright duplicate this test would
    catch by construction, since it names the same ref) or corrupting anything.
    """
    ordinary = create(client, title="got there first")

    response = claim(client, ordinary["ref"], title="too slow")
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "ref_taken"

    # No duplicate landed, and the original is exactly what it was.
    reread = client.get(f"{NOTES}/{ordinary['ref']}", headers=auth())
    assert reread.json()["title"] == "got there first"


def test_concurrent_ordinary_inserts_and_explicit_ref_claims_never_duplicate_a_ref(
    migrated_engine: Any,
) -> None:
    """The real-concurrency stress test, at the same layer
    `test_migration_0001.py::test_the_ref_sequence_allocates_atomically_under_concurrent_inserts`
    uses: raw connections, a thread pool, no coordination beyond what Postgres itself provides.

    Half the workers do an ordinary `nextval()`-allocated INSERT; half do an explicit-ref claim —
    the exact statement shape `app/api/note_claim.py`'s `claim_note` issues
    (`INSERT ... ON CONFLICT (ref) DO NOTHING RETURNING ref`) — for ref numbers chosen to overlap
    the range the ordinary writers are simultaneously drawing from, which is the scenario a
    read-then-write implementation would lose and a database-level unique constraint cannot.

    The property under test is the one that matters: **every ref that landed is unique**, and
    **nothing but the unique index itself decided who lost.** A losing explicit claim returns no
    row (this file's own `INSERT_NOTE_EXPLICIT_REF` mirrors the route's `ON CONFLICT DO NOTHING`,
    so it never raises); a losing *ordinary* insert — the case an explicit claim beat a `nextval()`
    to the number it was about to allocate — raises `IntegrityError` on the unique constraint,
    exactly the "just `500` the loser rather than corrupt anything" outcome this feature's design
    accepts (see `app/api/note_claim.py`'s module docstring): correct, not corrupting, and cheap
    enough that this test catches it right alongside the clean 409 the HTTP route would answer with
    for the same failure. Nothing here asserts every writer succeeds, only that success never
    collides and that a loss is always one of these two clean shapes.
    """
    from sqlalchemy.exc import IntegrityError

    engine = migrated_engine
    owner = uuid.uuid4()

    with engine.begin() as connection:
        connection.execute(INSERT_USER, {"id": owner, "email": f"{owner}@example.test"})
        start = connection.execute(SEQUENCE_LAST_VALUE).scalar_one()

    # The pool both kinds of workers draw from: comfortably inside the range ordinary `nextval()`
    # calls will produce over the next `workers` calls, so a naive implementation collides often
    # rather than rarely.
    claim_targets = [start + n for n in range(1, 21)]

    def ordinary_insert(worker: int) -> str | None:
        with engine.begin() as connection:
            try:
                return connection.execute(
                    INSERT_NOTE_ORDINARY, {"owner_id": owner, "title": f"ordinary {worker}"}
                ).scalar_one()
            except IntegrityError:
                # This worker's `nextval()` landed on a number an explicit claim already took —
                # the loser's clean, expected shape. `engine.begin()`'s own `__exit__` rolls the
                # transaction back; nothing here needs to.
                return None

    def explicit_claim(number: int) -> str | None:
        with engine.begin() as connection:
            row = connection.execute(
                INSERT_NOTE_EXPLICIT_REF,
                {"owner_id": owner, "ref": f"NOTE-{number}", "title": f"claim {number}"},
            ).scalar_one_or_none()
            return row

    with ThreadPoolExecutor(max_workers=32) as pool:
        ordinary_futures = [pool.submit(ordinary_insert, n) for n in range(20)]
        claim_futures = [pool.submit(explicit_claim, n) for n in claim_targets]
        refs = [f.result() for f in ordinary_futures] + [f.result() for f in claim_futures]

    landed = [ref for ref in refs if ref is not None]
    assert len(landed) == len(set(landed)), "two writers landed the same ref"
    assert len(landed) < len(refs), "the pools were sized to overlap — a race that never happened"

    with engine.connect() as connection:
        total = connection.execute(
            text("SELECT count(*) FROM note WHERE owner_id = :owner"), {"owner": owner}
        ).scalar_one()
    assert total == len(landed), "the database's own count agrees with what the workers observed"
