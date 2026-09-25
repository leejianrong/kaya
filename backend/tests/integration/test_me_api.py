"""``GET /api/v1/me`` against a real Postgres (ADR 0012's amendment, KAN-1743, mirrors pandan's own
``GET /api/v1/me``).

`get_principal` faked directly, the same way every other integration test in this package does
(`tests/integration/auth_helpers.py`'s own module docstring) — this route's job is announcing who a
credential already resolved to, not resolving one itself.

**No ``import app.*`` at module top** — see the package docstring, and pandan's PR #17 trap.
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

ME = "/api/v1/me"


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

    override_get_principal(app, known_principals)
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        empty()


@pytest.fixture
def alice(client: Any, known_principals: dict[str, Any]) -> Any:
    from app.auth.principal import Principal

    known_principals[ALICE_TOKEN] = Principal(id=ALICE_ID, email="alice@example.com")
    return ALICE_TOKEN


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_a_valid_bearer_gets_id_and_email(client: Any, alice: str) -> None:
    response = client.get(ME, headers=bearer(alice))

    assert response.status_code == 200
    assert response.json() == {"id": str(ALICE_ID), "email": "alice@example.com"}


def test_no_bearer_is_a_401(client: Any) -> None:
    response = client.get(ME)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_an_unrecognised_bearer_is_a_401(client: Any) -> None:
    response = client.get(ME, headers=bearer("garbage-kaya-has-never-seen"))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


def test_documented_in_the_openapi_schema(client: Any) -> None:
    schema = client.get("/openapi.json").json()

    assert ME in schema["paths"]
