"""``/api/v1/tokens`` end to end: real routes, real Postgres, real HTTP (ADR 0012, KAN-1739).

Gated on kaya's own cookie-session identity, not a pandan bearer — so unlike `test_notes_api.py`,
what's overridden here is `get_current_active_user`, never the pandan-introspection resolver. This
mirrors exactly how `test_notes_api.py` injects a `FakeUpstream` at the one seam ADR 0002 made a
`Protocol`: the seam under test is kaya's own, `get_current_active_user`, and no test in this file
drives a real GitHub OAuth handshake to reach it — that machinery is `test_identity_manager.py`'s
job, already covered there.

**No `import app.*` at module top** — see `tests/integration/conftest.py`'s package docstring
convention (PR #17's trap).
"""

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]

TOKENS = "/api/v1/tokens"


def _alembic_config() -> Any:
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


@pytest.fixture
def client(database_url: str) -> Iterator[Any]:
    """The **real** app — `app.main.app`, router and error handlers — with only "who is logged in"
    swapped out. A fresh `KayaAccount` row is inserted directly (via the sync session — the same
    shared `Base`/table `app/identity/pat.py`'s own docstring argues makes this safe) rather than
    driven through a real OAuth login, since that handshake is what `test_identity_manager.py`
    already covers."""
    from alembic import command
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    from app.db import get_sessionmaker
    from app.identity.current_user import get_current_active_user
    from app.identity.models import KayaAccount
    from app.main import app

    command.upgrade(_alembic_config(), "head")

    def empty() -> None:
        with get_sessionmaker()() as session:
            session.execute(
                text("TRUNCATE TABLE personal_access_token, kaya_account CASCADE")
            )
            session.commit()

    empty()

    account = KayaAccount(
        id=uuid.uuid4(),
        email="alice@example.com",
        hashed_password="not-a-real-hash",
        is_active=True,
        is_superuser=False,
        is_verified=False,
    )
    with get_sessionmaker()() as session:
        session.add(account)
        session.commit()
        session.refresh(account)

    app.dependency_overrides[get_current_active_user] = lambda: account
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        empty()


def test_creating_a_token_returns_the_secret_exactly_once(client: Any) -> None:
    response = client.post(TOKENS, json={"name": "laptop"})

    assert response.status_code == 201
    body = response.json()
    assert body["token"].startswith("kaya_pat_")
    assert body["name"] == "laptop"
    assert body["scope"] == "write", "write is the default scope"
    assert body["token_prefix"] == body["token"][: len(body["token_prefix"])]

    listed = client.get(TOKENS).json()
    assert len(listed) == 1
    assert "token" not in listed[0], "the secret must never reappear on a list read"
    assert listed[0]["id"] == body["id"]


def test_only_the_hash_reaches_the_database_never_the_raw_secret(client: Any) -> None:
    from sqlalchemy import select

    from app.db import get_sessionmaker
    from app.identity.pat import PersonalAccessToken, hash_token

    created = client.post(TOKENS, json={"name": "ci-bot"}).json()

    with get_sessionmaker()() as session:
        row = session.scalars(
            select(PersonalAccessToken).where(PersonalAccessToken.id == created["id"])
        ).one()

    from app.config import get_settings

    assert row.token_hash == hash_token(created["token"], get_settings().kaya_auth_secret)
    assert created["token"] not in row.token_hash


def test_a_read_scope_token_can_be_minted(client: Any) -> None:
    response = client.post(TOKENS, json={"name": "read-only agent", "scope": "read"})

    assert response.status_code == 201
    assert response.json()["scope"] == "read"


def test_revoking_a_token_makes_it_disappear_from_the_list(client: Any) -> None:
    created = client.post(TOKENS, json={"name": "temp"}).json()

    revoked = client.delete(f"{TOKENS}/{created['id']}")

    assert revoked.status_code == 204
    assert revoked.content == b""
    assert client.get(TOKENS).json() == []


def test_revoking_someone_elses_token_is_a_404_not_a_403(client: Any) -> None:
    """Deliberately the opposite of a note's owner-mismatch `403` (Q40) — see
    `app/api/tokens.py`'s own comment for why a token's existence is not a bit worth leaking."""
    import uuid as uuid_module

    from app.db import get_sessionmaker
    from app.identity.models import KayaAccount
    from app.identity.pat import PersonalAccessToken, hash_token

    other = KayaAccount(
        id=uuid_module.uuid4(),
        email="mallory@example.com",
        hashed_password="not-a-real-hash",
        is_active=True,
        is_superuser=False,
        is_verified=False,
    )
    with get_sessionmaker()() as session:
        session.add(other)
        session.commit()
        session.refresh(other)
        others_token = PersonalAccessToken(
            user_id=other.id,
            name="mallory's token",
            token_hash=hash_token("kaya_pat_not-alices-to-touch", "test-secret-does-not-matter"),
            token_prefix="kaya_pat_not-",
        )
        session.add(others_token)
        session.commit()
        session.refresh(others_token)
        other_token_id = others_token.id

    response = client.delete(f"{TOKENS}/{other_token_id}")

    assert response.status_code == 404
    # Still there — the delete must not have touched a row it refused to acknowledge.
    with get_sessionmaker()() as session:
        assert session.get(PersonalAccessToken, other_token_id) is not None


def test_a_missing_token_id_is_a_404(client: Any) -> None:
    response = client.delete(f"{TOKENS}/999999")

    assert response.status_code == 404


def test_tokens_require_a_cookie_session_never_a_bearer(database_url: str) -> None:
    """No `Authorization` header anywhere in this test — `/api/v1/tokens` doesn't look at one."""
    from alembic import command
    from fastapi.testclient import TestClient

    from app.main import app

    command.upgrade(_alembic_config(), "head")

    with TestClient(app) as client:
        response = client.get(TOKENS)

    assert response.status_code == 401


def test_an_empty_name_is_a_422(client: Any) -> None:
    response = client.post(TOKENS, json={"name": "   "})

    assert response.status_code == 422


def test_a_name_over_the_column_width_is_a_422(client: Any) -> None:
    response = client.post(TOKENS, json={"name": "x" * 256})

    assert response.status_code == 422
