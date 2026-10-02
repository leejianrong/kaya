"""``/api/v1/preferences`` against a real Postgres (KAN-1815).

Covers the default (an account that never wrote anything reads ``format_on_save: true``, so no
backfill is needed), the round trip, partial-write semantics, per-account isolation, validation, and
that the account's deletion cascades to its preferences.

**No ``import app.*`` at module top** — see the package docstring.
"""

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from tests.integration.auth_helpers import override_get_principal, seed_kaya_account

BACKEND_ROOT = Path(__file__).resolve().parents[2]

ALICE_TOKEN = "alice-token"
BOB_TOKEN = "bob-token"
ALICE_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
BOB_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")

PREFS = "/api/v1/preferences"


def _alembic_config() -> Any:
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


@pytest.fixture
def known_principals() -> dict[str, Any]:
    return {}


@pytest.fixture
def client(database_url: str, known_principals: dict[str, Any]) -> Iterator[Any]:
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

    known_principals[ALICE_TOKEN] = Principal(id=ALICE_ID, email="alice@example.com")
    known_principals[BOB_TOKEN] = Principal(id=BOB_ID, email="bob@example.com")
    override_get_principal(app, known_principals)
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        empty()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_no_bearer_is_a_401(client: Any) -> None:
    assert client.get(PREFS).status_code == 401
    assert client.patch(PREFS, json={"format_on_save": False}).status_code == 401


def test_an_account_that_never_wrote_one_defaults_to_format_on_save_on(client: Any) -> None:
    response = client.get(PREFS, headers=bearer(ALICE_TOKEN))

    assert response.status_code == 200
    assert response.json() == {"format_on_save": True}


def test_turning_it_off_persists_and_turning_it_back_on_too(client: Any) -> None:
    off = client.patch(PREFS, json={"format_on_save": False}, headers=bearer(ALICE_TOKEN))
    assert off.status_code == 200
    assert off.json() == {"format_on_save": False}
    assert client.get(PREFS, headers=bearer(ALICE_TOKEN)).json() == {"format_on_save": False}

    on = client.patch(PREFS, json={"format_on_save": True}, headers=bearer(ALICE_TOKEN))
    assert on.json() == {"format_on_save": True}
    assert client.get(PREFS, headers=bearer(ALICE_TOKEN)).json() == {"format_on_save": True}


def test_writing_twice_is_one_row_not_two(client: Any) -> None:
    from app.db import get_sessionmaker

    for value in (False, False, True, False):
        client.patch(PREFS, json={"format_on_save": value}, headers=bearer(ALICE_TOKEN))

    with get_sessionmaker()() as session:
        count = session.execute(
            text("SELECT count(*) FROM user_preference WHERE user_id = :u"), {"u": ALICE_ID}
        ).scalar_one()
    assert count == 1


def test_an_empty_patch_changes_nothing_and_writes_no_row(client: Any) -> None:
    from app.db import get_sessionmaker

    response = client.patch(PREFS, json={}, headers=bearer(ALICE_TOKEN))

    assert response.json() == {"format_on_save": True}
    with get_sessionmaker()() as session:
        assert session.execute(text("SELECT count(*) FROM user_preference")).scalar_one() == 0


def test_one_accounts_choice_never_reaches_another(client: Any) -> None:
    client.patch(PREFS, json={"format_on_save": False}, headers=bearer(ALICE_TOKEN))

    assert client.get(PREFS, headers=bearer(BOB_TOKEN)).json() == {"format_on_save": True}


def test_an_unknown_key_or_a_non_boolean_is_a_422(client: Any) -> None:
    unknown = client.patch(PREFS, json={"theme": "dark"}, headers=bearer(ALICE_TOKEN))
    assert unknown.status_code == 422

    not_a_bool = client.patch(PREFS, json={"format_on_save": "maybe"}, headers=bearer(ALICE_TOKEN))
    assert not_a_bool.status_code == 422


def test_deleting_an_account_takes_its_preferences_with_it(client: Any) -> None:
    from app.db import get_sessionmaker

    client.patch(PREFS, json={"format_on_save": False}, headers=bearer(ALICE_TOKEN))

    with get_sessionmaker()() as session:
        session.execute(text("DELETE FROM kaya_account WHERE id = :u"), {"u": ALICE_ID})
        session.commit()
        assert session.execute(text("SELECT count(*) FROM user_preference")).scalar_one() == 0
