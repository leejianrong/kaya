"""KAN-1814's formatter on the wire, against a real Postgres: ``PATCH`` with ``format: true`` and
``GET /notes/{ref}/format-check``.

What only the real routes and database can show: that a format-only write cuts exactly one version
and restamps ``updated_at`` only when the body really changed; that it is refused with a `409` under
a stale precondition even though no ``body`` was sent (ADR 0009, via ``guards_the_body``); that
``note_link`` is still reconciled from the *formatted* body and its edges survive; and that
``format-check`` writes nothing at all.

**No ``import app.*`` at module top** — see ``test_note_versions_api.py``'s docstring.
"""

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from tests.integration.auth_helpers import override_get_principal, seed_kaya_account

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


def _alembic_config() -> Any:
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


@pytest.fixture
def engine(database_url: str) -> Any:
    """The schema at head, for reading ``note_version`` directly."""
    from alembic import command

    from app.db import get_engine

    command.upgrade(_alembic_config(), "head")
    return get_engine()


@pytest.fixture
def client(database_url: str) -> Iterator[Any]:
    """The real app with identity faked (`override_get_principal`, KAN-1740), exactly as
    ``test_notes_api.py`` builds it."""
    from alembic import command
    from fastapi.testclient import TestClient

    from app.auth.principal import Principal
    from app.db import get_sessionmaker
    from app.main import app

    command.upgrade(_alembic_config(), "head")

    def empty() -> None:
        with get_sessionmaker()() as session:
            session.execute(text("TRUNCATE TABLE note, kaya_account CASCADE"))
            session.commit()

    empty()
    with get_sessionmaker()() as session:
        seed_kaya_account(session, id=ALICE_ID, email="alice@example.com")
        seed_kaya_account(session, id=BOB_ID, email="bob@example.com")
    known_principals = {
        ALICE_TOKEN: Principal(id=ALICE_ID, email="alice@example.com"),
        BOB_TOKEN: Principal(id=BOB_ID, email="bob@example.com"),
    }
    override_get_principal(app, known_principals)
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
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


UNFORMATTED = "#  Runbook\n* one\n* two\n\nSee [[KAN-12]] and [[Other Note]].\n"
FORMATTED = "# Runbook\n\n- one\n- two\n\nSee [[KAN-12]] and [[Other Note]].\n"

READ_EDGES = text(
    "SELECT target_kind, target_ref FROM note_link WHERE source_note_id = :note_id "
    "ORDER BY target_kind, target_ref"
)


def edges_of(engine: Any, note_id: int) -> list[tuple[str, str]]:
    with engine.connect() as connection:
        return [tuple(row) for row in connection.execute(READ_EDGES, {"note_id": note_id})]


def patch(client: Any, ref: str, **payload: Any) -> Any:
    return client.patch(f"{NOTES}/{ref}", json=payload, headers=auth())


def test_format_alone_formats_the_stored_body_in_one_write(client: Any, engine: Any) -> None:
    created = create(client, body=UNFORMATTED)

    response = patch(client, created["ref"], format=True)

    assert response.status_code == 200, response.text
    assert response.json()["body"] == FORMATTED
    assert response.headers["X-Kaya-Format"] == "formatted"
    assert client.get(f"{NOTES}/{created['ref']}", headers=auth()).json()["body"] == FORMATTED
    assert [row.body for row in versions_of(engine, created["id"])] == [FORMATTED, UNFORMATTED]


def test_format_with_a_body_stores_the_formatted_version_of_that_body(client: Any) -> None:
    created = create(client, body="old")

    response = patch(client, created["ref"], body=UNFORMATTED, format=True)

    assert response.status_code == 200, response.text
    assert response.json()["body"] == FORMATTED


def test_without_the_flag_the_body_is_stored_byte_for_byte(client: Any) -> None:
    created = create(client, body="old")

    response = patch(client, created["ref"], body=UNFORMATTED)

    assert response.json()["body"] == UNFORMATTED
    assert "X-Kaya-Format" not in response.headers


def test_an_already_formatted_note_is_not_restamped_or_versioned(client: Any, engine: Any) -> None:
    created = create(client, body=FORMATTED)

    response = patch(client, created["ref"], format=True)

    assert response.status_code == 200, response.text
    assert response.headers["X-Kaya-Format"] == "unchanged"
    assert response.json()["updated_at"] == created["updated_at"]
    assert len(versions_of(engine, created["id"])) == 1


def test_a_stale_precondition_refuses_a_format_only_write(client: Any, engine: Any) -> None:
    created = create(client, body=UNFORMATTED)
    stale = "2000-01-01T00:00:00.000000+00:00"

    response = patch(client, created["ref"], format=True, if_updated_at=stale)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "note_conflict"
    assert client.get(f"{NOTES}/{created['ref']}", headers=auth()).json()["body"] == UNFORMATTED
    assert len(versions_of(engine, created["id"])) == 1


def test_a_current_precondition_lets_a_format_only_write_through(client: Any) -> None:
    created = create(client, body=UNFORMATTED)

    response = patch(client, created["ref"], format=True, if_updated_at=created["updated_at"])

    assert response.status_code == 200, response.text
    assert response.json()["body"] == FORMATTED


def test_link_edges_are_reconciled_from_the_formatted_body_and_survive(
    client: Any, engine: Any
) -> None:
    created = create(client, body=UNFORMATTED)
    before = edges_of(engine, created["id"])

    patch(client, created["ref"], format=True)

    assert before == [("KAN", "KAN-12"), ("NOTE", "Other Note")]
    assert edges_of(engine, created["id"]) == before


def test_format_check_reports_a_change_and_writes_nothing(client: Any, engine: Any) -> None:
    created = create(client, body=UNFORMATTED)

    response = client.get(f"{NOTES}/{created['ref']}/format-check", headers=auth())

    assert response.status_code == 200, response.text
    assert response.json()["changed"] is True
    assert response.json()["changed_lines"] > 0
    after = client.get(f"{NOTES}/{created['ref']}", headers=auth()).json()
    assert after["body"] == UNFORMATTED
    assert after["updated_at"] == created["updated_at"]
    assert len(versions_of(engine, created["id"])) == 1


def test_format_check_on_a_formatted_note_says_unchanged(client: Any) -> None:
    created = create(client, body=FORMATTED)

    body = client.get(f"{NOTES}/{created['ref']}/format-check", headers=auth()).json()

    assert body == {"changed": False, "changed_lines": 0, "reason": None}


def test_format_check_of_someone_elses_note_is_refused(client: Any) -> None:
    created = create(client, body=UNFORMATTED)

    response = client.get(f"{NOTES}/{created['ref']}/format-check", headers=auth(BOB_TOKEN))

    assert response.status_code in (403, 404)
    assert "changed" not in response.json()
