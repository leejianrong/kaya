"""``POST /api/v1/notes/move-folder`` against real Postgres (KAN-2000).

Folders are only a view of ``note.path`` (ADR 0008), so every assertion is about paths on rows.
Identity is faked the way ``test_notes_api.py`` does; token scope is covered by
``test_token_scope_api.py``'s mutating-route table.

**No ``import app.*`` at module top** (see ``tests/integration/conftest.py``).
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
BOB_TOKEN = "a-different-caller-supplied-string"
ALICE_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
BOB_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")

NOTES = "/api/v1/notes"
MOVE = "/api/v1/notes/move-folder"


def _alembic_config() -> Any:
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


@pytest.fixture
def client(database_url: str) -> Iterator[Any]:
    from alembic import command
    from fastapi.testclient import TestClient

    from app.auth.principal import Principal
    from app.db import get_sessionmaker
    from app.main import app

    command.upgrade(_alembic_config(), "head")

    def empty() -> None:
        with get_sessionmaker()() as session:
            session.execute(text("DROP TRIGGER IF EXISTS boom ON note"))
            session.execute(text("TRUNCATE TABLE note, kaya_account CASCADE"))
            session.commit()

    empty()
    with get_sessionmaker()() as session:
        seed_kaya_account(session, id=ALICE_ID, email="alice@example.com")
        seed_kaya_account(session, id=BOB_ID, email="bob@example.com")
    override_get_principal(
        app,
        {
            ALICE_TOKEN: Principal(id=ALICE_ID, email="alice@example.com"),
            BOB_TOKEN: Principal(id=BOB_ID, email="bob@example.com"),
        },
    )
    try:
        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        empty()


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def make(client: Any, token: str, path: str, title: str | None = None) -> dict[str, Any]:
    response = client.post(
        NOTES, json={"title": title or path or "untitled", "path": path}, headers=auth(token)
    )
    assert response.status_code == 201, response.text
    return response.json()


def paths(client: Any, token: str = ALICE_TOKEN) -> dict[str, str]:
    listed = client.get(NOTES, headers=auth(token)).json()["notes"]
    return {note["title"]: note["path"] for note in listed}


def move(client: Any, source: str, target: str, token: str = ALICE_TOKEN) -> Any:
    return client.post(MOVE, json={"from": source, "to": target}, headers=auth(token))


def test_a_rename_rewrites_every_note_under_the_folder(client: Any) -> None:
    make(client, ALICE_TOKEN, "ops/runbook.md", "r")
    make(client, ALICE_TOKEN, "ops/deep/er/x.md", "x")
    make(client, ALICE_TOKEN, "elsewhere/y.md", "y")

    response = move(client, "ops", "platform/ops")

    assert response.status_code == 200, response.text
    assert response.json() == {"moved": 2}
    assert paths(client) == {
        "r": "platform/ops/runbook.md",
        "x": "platform/ops/deep/er/x.md",
        "y": "elsewhere/y.md",
    }


def test_only_the_callers_notes_move(client: Any) -> None:
    make(client, ALICE_TOKEN, "ops/a.md", "alice-note")
    make(client, BOB_TOKEN, "ops/a.md", "bob-note")

    assert move(client, "ops", "ops2").json() == {"moved": 1}

    assert paths(client) == {"alice-note": "ops2/a.md"}
    assert paths(client, BOB_TOKEN) == {"bob-note": "ops/a.md"}


def test_segment_boundary_a_b_does_not_match_a_bc(client: Any) -> None:
    make(client, ALICE_TOKEN, "a/b/n.md", "inside")
    make(client, ALICE_TOKEN, "a/bc/n.md", "sibling")
    make(client, ALICE_TOKEN, "a/b2/n.md", "other")

    assert move(client, "a/b", "z").json() == {"moved": 1}

    assert paths(client) == {"inside": "z/n.md", "sibling": "a/bc/n.md", "other": "a/b2/n.md"}


def test_a_leaf_named_like_the_folder_is_left_alone(client: Any) -> None:
    make(client, ALICE_TOKEN, "a/b", "leaf")
    make(client, ALICE_TOKEN, "a/b/c.md", "child")

    assert move(client, "a/b", "z").json() == {"moved": 1}

    assert paths(client) == {"leaf": "a/b", "child": "z/c.md"}


def test_a_nested_folder_moves_out_of_its_parent(client: Any) -> None:
    make(client, ALICE_TOKEN, "a/b/c/n.md", "n")
    make(client, ALICE_TOKEN, "a/keep.md", "keep")

    assert move(client, "a/b/c", "top").json() == {"moved": 1}

    assert paths(client) == {"n": "top/n.md", "keep": "a/keep.md"}


def test_slashes_are_normalised_on_input_and_on_stored_paths(client: Any) -> None:
    make(client, ALICE_TOKEN, "/a//b/n.md", "n")

    assert move(client, "/a/b/", "//x//").json() == {"moved": 1}

    assert paths(client) == {"n": "x/n.md"}


def test_a_move_restamps_updated_at_and_leaves_the_body_and_history_alone(client: Any) -> None:
    created = make(client, ALICE_TOKEN, "a/n.md", "n")
    ref = created["ref"]
    versions_before = client.get(f"{NOTES}/{ref}/versions", headers=auth(ALICE_TOKEN)).json()

    move(client, "a", "b")

    after = client.get(f"{NOTES}/{ref}", headers=auth(ALICE_TOKEN)).json()
    assert after["path"] == "b/n.md"
    assert after["updated_at"] > created["updated_at"]
    assert after["body"] == created["body"]
    assert after["ref"] == ref
    versions_after = client.get(f"{NOTES}/{ref}/versions", headers=auth(ALICE_TOKEN)).json()
    assert versions_after == versions_before


def test_from_equal_to_is_an_idempotent_no_op(client: Any) -> None:
    created = make(client, ALICE_TOKEN, "a/n.md", "n")

    response = move(client, "a", "/a/")

    assert response.status_code == 200
    assert response.json() == {"moved": 0}
    after = client.get(f"{NOTES}/{created['ref']}", headers=auth(ALICE_TOKEN)).json()
    assert after["updated_at"] == created["updated_at"]


def test_a_folder_with_no_notes_moves_zero(client: Any) -> None:
    make(client, ALICE_TOKEN, "a/n.md", "n")

    assert move(client, "nothing/here", "x").json() == {"moved": 0}


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("a", "a/b"),
        ("a/b", "a/b/c/d"),
        ("", "x"),
        ("x", ""),
        ("/", "x"),
        ("a/ /b", "x"),
        ("a", "x/ "),
    ],
)
def test_invalid_moves_are_a_422_in_the_standard_shape_and_write_nothing(
    client: Any, source: str, target: str
) -> None:
    make(client, ALICE_TOKEN, "a/b/n.md", "n")

    response = move(client, source, target)

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert isinstance(error["code"], str) and isinstance(error["message"], str)
    assert paths(client) == {"n": "a/b/n.md"}


def test_a_result_over_the_column_limit_is_a_422_and_writes_nothing(client: Any) -> None:
    make(client, ALICE_TOKEN, "a/" + "p" * 1000 + ".md", "long")
    make(client, ALICE_TOKEN, "a/short.md", "short")

    response = move(client, "a", "d" * 100)

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "invalid_folder_move"
    assert paths(client)["short"] == "a/short.md"


def test_a_missing_or_extra_field_is_a_422_in_the_standard_shape(client: Any) -> None:
    for body in ({"from": "a"}, {"from": "a", "to": "b", "extra": 1}):
        response = client.post(MOVE, json=body, headers=auth(ALICE_TOKEN))
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_request"


def test_no_credential_is_a_401(client: Any) -> None:
    response = client.post(MOVE, json={"from": "a", "to": "b"})

    assert response.status_code == 401
    assert "code" in response.json()["error"]


def test_a_failure_part_way_leaves_every_path_unchanged(client: Any) -> None:
    """One transaction: a row the database refuses to update rolls back the rows before it."""
    from app.db import get_sessionmaker

    make(client, ALICE_TOKEN, "a/1.md", "first")
    make(client, ALICE_TOKEN, "a/2.md", "poison")
    make(client, ALICE_TOKEN, "a/3.md", "third")
    with get_sessionmaker()() as session:
        session.execute(
            text(
                "CREATE FUNCTION boom() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
                "IF NEW.title = 'poison' AND NEW.path <> OLD.path THEN "
                "RAISE EXCEPTION 'forced failure'; END IF; RETURN NEW; END $$"
            )
        )
        session.execute(
            text("CREATE TRIGGER boom BEFORE UPDATE ON note FOR EACH ROW EXECUTE FUNCTION boom()")
        )
        session.commit()
    try:
        response = move(client, "a", "b")
        assert response.status_code == 500
        assert paths(client) == {"first": "a/1.md", "poison": "a/2.md", "third": "a/3.md"}
    finally:
        with get_sessionmaker()() as session:
            session.execute(text("DROP TRIGGER boom ON note"))
            session.execute(text("DROP FUNCTION boom()"))
            session.commit()
