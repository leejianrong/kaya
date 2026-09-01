"""``note_version`` against a real Postgres — R13 (``docs/roadmap/BREADBOARD.md``),
KAN-1064/1065/1066, the same shape ``tests/integration/test_note_link_reconcile.py`` uses for its
own reconcile-on-save table.

What only a real database (and the real routes) can show: that ``create_note`` and ``update_note``
cut a row on the wire, not just in a unit test's fake session; that a title- or path-only `PATCH`
cuts nothing; that `ON DELETE CASCADE` actually removes a note's history when the note goes; and —
KAN-1066's headline claim, and the one CLAUDE.md calls out by name as the kind of thing a structural
guard does not cover — that **restoring a version through `PATCH` honours `if_updated_at` exactly
like any other edit**: a stale precondition on a restore is a `409`, not a special case that slips
through because it "isn't really an edit".

**No ``import app.*`` at module top** — see the package docstring, and pandan's PR #17 trap: a
top-level `app` import runs at collection, before the `database_url` fixture sets `DATABASE_URL`.
"""

import uuid
from collections.abc import Iterator
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

READ_VERSIONS = text(
    "SELECT id, body, created_at FROM note_version WHERE note_id = :note_id "
    "ORDER BY created_at DESC, id DESC"
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
    """The schema at head, for reading ``note_version`` directly."""
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


def versions_of(engine: Any, note_id: int) -> list[Any]:
    with engine.connect() as connection:
        return list(connection.execute(READ_VERSIONS, {"note_id": note_id}))


def list_versions(client: Any, ref: str, *, token: str = ALICE_TOKEN) -> list[dict[str, Any]]:
    response = client.get(f"{NOTES}/{ref}/versions", headers=auth(token))
    assert response.status_code == 200, response.text
    return response.json()["versions"]


# --- Cut point: create_note and update_note ------------------------------------------------------


def test_creating_a_note_cuts_its_first_version(client: Any, engine: Any) -> None:
    created = create(client, title="runbook", body="# steps")

    rows = versions_of(engine, created["id"])
    assert len(rows) == 1
    assert rows[0].body == "# steps"


def test_a_title_alone_still_cuts_a_version_for_the_default_empty_body(
    client: Any, engine: Any
) -> None:
    """R13's "no heuristic" draws no exception for a body that happens to be ``""``."""
    created = create(client, title="bare")

    rows = versions_of(engine, created["id"])
    assert len(rows) == 1
    assert rows[0].body == ""


def test_editing_the_body_cuts_a_new_version_each_time(client: Any, engine: Any) -> None:
    created = create(client, title="runbook", body="v1")

    client.patch(f"{NOTES}/{created['ref']}", json={"body": "v2"}, headers=auth())
    client.patch(f"{NOTES}/{created['ref']}", json={"body": "v3"}, headers=auth())

    rows = versions_of(engine, created["id"])
    assert [row.body for row in rows] == ["v3", "v2", "v1"], "newest first"


def test_a_title_or_path_only_edit_cuts_no_version(client: Any, engine: Any) -> None:
    created = create(client, title="runbook", body="v1")

    client.patch(f"{NOTES}/{created['ref']}", json={"title": "renamed"}, headers=auth())
    client.patch(f"{NOTES}/{created['ref']}", json={"path": "ops/moved.md"}, headers=auth())

    rows = versions_of(engine, created["id"])
    assert len(rows) == 1, "neither write touched `body`, so neither cuts a version"


def test_an_empty_patch_cuts_no_version(client: Any, engine: Any) -> None:
    created = create(client, title="runbook", body="v1")

    response = client.patch(f"{NOTES}/{created['ref']}", json={}, headers=auth())
    assert response.status_code == 200

    assert len(versions_of(engine, created["id"])) == 1


def test_writing_the_same_body_again_still_cuts_a_version(client: Any, engine: Any) -> None:
    """"No debounce, no 'only if changed' heuristic" (BREADBOARD.md's R13): a `PATCH` that sends
    `body` cuts a version whether or not the value it sent differs from what was already stored."""
    created = create(client, title="runbook", body="v1")

    client.patch(f"{NOTES}/{created['ref']}", json={"body": "v1"}, headers=auth())

    rows = versions_of(engine, created["id"])
    assert [row.body for row in rows] == ["v1", "v1"]


def test_deleting_a_note_removes_its_note_version_rows(client: Any, engine: Any) -> None:
    """``ON DELETE CASCADE``: a version has no meaning independent of the note it snapshots."""
    created = create(client, title="runbook", body="v1")
    client.patch(f"{NOTES}/{created['ref']}", json={"body": "v2"}, headers=auth())
    assert len(versions_of(engine, created["id"])) == 2

    deleted = client.delete(f"{NOTES}/{created['ref']}", headers=auth())
    assert deleted.status_code == 204

    assert versions_of(engine, created["id"]) == []


# --- List: GET /notes/{ref}/versions -------------------------------------------------------------


def test_the_versions_list_is_an_envelope_with_a_named_key(client: Any) -> None:
    created = create(client, title="runbook", body="v1")

    response = client.get(f"{NOTES}/{created['ref']}/versions", headers=auth())
    assert response.status_code == 200
    assert set(response.json()) == {"versions"}


def test_the_list_is_newest_first_with_full_bodies_and_no_second_round_trip_needed(
    client: Any,
) -> None:
    created = create(client, title="runbook", body="v1")
    client.patch(f"{NOTES}/{created['ref']}", json={"body": "v2"}, headers=auth())
    client.patch(f"{NOTES}/{created['ref']}", json={"body": "v3"}, headers=auth())

    versions = list_versions(client, created["ref"])
    assert [v["body"] for v in versions] == ["v3", "v2", "v1"]
    # Every row is a complete record — this card's preview design call (`NoteVersionRead`'s
    # docstring): a preview is a client-side selection over rows already in hand.
    assert all(set(v) == {"id", "body", "created_at"} for v in versions)


def test_a_note_with_only_its_own_creation_still_lists_one_version(client: Any) -> None:
    created = create(client, title="fresh")

    assert len(list_versions(client, created["ref"])) == 1


def test_another_users_note_history_is_a_403_not_a_leak(client: Any) -> None:
    created = create(client, token=ALICE_TOKEN, title="alice's")

    response = client.get(f"{NOTES}/{created['ref']}/versions", headers=auth(BOB_TOKEN))
    assert response.status_code == 403


def test_a_missing_notes_history_is_a_404(client: Any) -> None:
    response = client.get(f"{NOTES}/NOTE-999999/versions", headers=auth())
    assert response.status_code == 404


# --- Restore: PATCH with an old version's body, KAN-1066 -----------------------------------------


def test_restoring_a_version_is_a_plain_patch_that_writes_the_chosen_body(
    client: Any, engine: Any
) -> None:
    created = create(client, title="runbook", body="original")
    client.patch(f"{NOTES}/{created['ref']}", json={"body": "a mistake"}, headers=auth())

    versions = list_versions(client, created["ref"])
    original_version = next(v for v in versions if v["body"] == "original")

    current = client.get(f"{NOTES}/{created['ref']}", headers=auth()).json()
    restored = client.patch(
        f"{NOTES}/{created['ref']}",
        json={"body": original_version["body"], "if_updated_at": current["updated_at"]},
        headers=auth(),
    )

    assert restored.status_code == 200
    assert restored.json()["body"] == "original"
    assert restored.json()["title"] == "runbook", "restore touches only body, exactly like edit"

    # KAN-1064's cut point does not know or care that this write was a restore: it cut a third
    # version, so "undo a bad restore" already works with no extra code — see
    # `app/note_versions.py`.
    rows = versions_of(engine, created["id"])
    assert [row.body for row in rows] == ["original", "a mistake", "original"]


def test_a_stale_precondition_on_a_restore_is_a_409_exactly_like_any_other_edit(
    client: Any, engine: Any
) -> None:
    """KAN-1066's headline behavioural claim, and the one CLAUDE.md warns a *structural* guard
    cannot cover on its own: BREADBOARD.md says a restore "goes through the same 409 precondition
    as any other edit", and the only way to know that is true is to make it fire and watch it.

    Two readers, exactly `test_two_writers_read_one_note_and_the_second_gets_a_409_with_both_bodies`
    in `test_notes_api.py` — except the second writer is not typing a fresh rewrite, it is
    restoring an older version, and the precondition must not treat that any differently.
    """
    created = create(client, title="runbook", body="v1")
    client.patch(f"{NOTES}/{created['ref']}", json={"body": "v2"}, headers=auth())

    versions = list_versions(client, created["ref"])
    v1 = next(v for v in versions if v["body"] == "v1")

    # Alice reads the note (getting the `v2` precondition) but someone else writes again before
    # her restore of `v1` reaches the server.
    stale = client.get(f"{NOTES}/{created['ref']}", headers=auth()).json()["updated_at"]
    client.patch(
        f"{NOTES}/{created['ref']}",
        json={"body": "v3, written concurrently"},
        headers=auth(),
    )

    refused = client.patch(
        f"{NOTES}/{created['ref']}",
        json={"body": v1["body"], "if_updated_at": stale},
        headers=auth(),
    )

    assert refused.status_code == 409
    conflict = refused.json()["error"]
    assert conflict["code"] == "note_conflict"
    assert conflict["attempted"]["body"] == "v1"
    assert conflict["stored"]["body"] == "v3, written concurrently"

    # Nothing was written: the note still holds the concurrent write, and no fourth version exists.
    current = client.get(f"{NOTES}/{created['ref']}", headers=auth()).json()
    assert current["body"] == "v3, written concurrently"
    rows = versions_of(engine, created["id"])
    assert [row.body for row in rows] == ["v3, written concurrently", "v2", "v1"]


def test_restoring_with_no_precondition_is_a_plain_overwrite_same_as_any_other_edit(
    client: Any,
) -> None:
    """A restore is exactly `PATCH {"body": ...}` — omitting `if_updated_at` is as unguarded here
    as it is for a normal edit (ADR 0009: the precondition is opt-in, not a tax on every caller)."""
    created = create(client, title="runbook", body="v1")
    client.patch(f"{NOTES}/{created['ref']}", json={"body": "v2"}, headers=auth())

    restored = client.patch(f"{NOTES}/{created['ref']}", json={"body": "v1"}, headers=auth())

    assert restored.status_code == 200
    assert restored.json()["body"] == "v1"
