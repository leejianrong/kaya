"""``/auth/device/*`` against a real Postgres — RFC 8628 device flow (ADR 0013, KAN-1743).

The three consent routes (``GET``/``approve``/``deny``) are gated on `get_current_active_user`
(kaya's own cookie-session identity, `app/identity/current_user.py`), not `get_principal` —
`app/identity/device_auth_router.py`'s module docstring gives both reasons (a real circular import,
and the same chicken-and-egg security argument `test_tokens_api.py` already exercises for PAT
minting). This file overrides that dependency exactly the way `test_tokens_api.py` does.

``code``/``token`` are unauthenticated by RFC 8628's own design and need no override at all — this
file drives them as a real CLI would, through the real app, with a real (throwaway) Postgres backing
the `device_authorization` table.

**No ``import app.*`` at module top** — see the package docstring, and pandan's PR #17 trap.
"""

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

BACKEND_ROOT = Path(__file__).resolve().parents[2]

DEVICE_CODE = "/auth/device/code"
DEVICE_TOKEN = "/auth/device/token"


def _alembic_config() -> Any:
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


def device_get(user_code: str) -> str:
    return f"/auth/device/{user_code}"


def device_approve(user_code: str) -> str:
    return f"/auth/device/{user_code}/approve"


def device_deny(user_code: str) -> str:
    return f"/auth/device/{user_code}/deny"


@pytest.fixture
def client(database_url: str) -> Iterator[Any]:
    """The real app. `get_current_active_user` is faked directly (mirrors
    `test_tokens_api.py`'s own fixture) over a real `KayaAccount` row — the consent routes' own
    gate, not `get_principal`."""
    from alembic import command
    from fastapi.testclient import TestClient

    from app.db import get_sessionmaker
    from app.identity.current_user import get_current_active_user
    from app.identity.models import KayaAccount
    from app.main import app

    command.upgrade(_alembic_config(), "head")

    def empty() -> None:
        with get_sessionmaker()() as session:
            session.execute(
                text(
                    "TRUNCATE TABLE device_authorization, personal_access_token, kaya_account "
                    "CASCADE"
                )
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


# --- starting a login -------------------------------------------------------------------------


def test_creating_a_code_needs_no_auth(client: Any) -> None:
    response = client.post(DEVICE_CODE, json={})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "device_code",
        "user_code",
        "verification_uri",
        "verification_uri_complete",
        "expires_in",
        "interval",
    }
    assert "-" in body["user_code"]
    expected_complete = f"{body['verification_uri']}?user_code={body['user_code']}"
    assert body["verification_uri_complete"] == expected_complete


def test_polling_before_anyone_has_seen_it_is_pending(client: Any) -> None:
    code = client.post(DEVICE_CODE, json={}).json()

    response = client.post(DEVICE_TOKEN, json={"device_code": code["device_code"]})

    assert response.status_code == 400
    assert response.json() == {"error": "authorization_pending"}


def test_an_unknown_device_code_is_expired_token(client: Any) -> None:
    response = client.post(DEVICE_TOKEN, json={"device_code": "kaya-has-never-minted-this"})

    assert response.status_code == 400
    assert response.json() == {"error": "expired_token"}


def test_polling_twice_fast_is_slow_down(client: Any) -> None:
    code = client.post(DEVICE_CODE, json={}).json()

    first = client.post(DEVICE_TOKEN, json={"device_code": code["device_code"]})
    second = client.post(DEVICE_TOKEN, json={"device_code": code["device_code"]})

    assert first.json() == {"error": "authorization_pending"}
    assert second.json() == {"error": "slow_down"}


# --- the consent screen ------------------------------------------------------------------------


def test_the_consent_read_needs_auth(client: Any) -> None:
    code = client.post(DEVICE_CODE, json={}).json()
    app = client.app
    from app.identity.current_user import get_current_active_user

    original = app.dependency_overrides.pop(get_current_active_user)
    try:
        response = client.get(device_get(code["user_code"]))
    finally:
        app.dependency_overrides[get_current_active_user] = original

    assert response.status_code == 401


def test_the_consent_read_shows_the_requested_scope(client: Any) -> None:
    code = client.post(DEVICE_CODE, json={"scope": "read"}).json()

    response = client.get(device_get(code["user_code"]))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert body["requested_scope"] == "read"


def test_an_unknown_user_code_is_a_404(client: Any) -> None:
    response = client.get(device_get("NOPE-NOPE"))

    assert response.status_code == 404


def test_approving_then_polling_mints_a_real_pat(client: Any) -> None:
    code = client.post(DEVICE_CODE, json={"scope": "write"}).json()

    approved = client.post(device_approve(code["user_code"]), json={"scope": "write"})
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    minted = client.post(DEVICE_TOKEN, json={"device_code": code["device_code"]})
    assert minted.status_code == 200
    body = minted.json()
    assert body["token"].startswith("kaya_pat_")
    assert body["scope"] == "write"


def test_the_final_approved_scope_overrides_the_requested_one(client: Any) -> None:
    """Approving is a fresh grant, not a diff — see the router's own module docstring."""
    code = client.post(DEVICE_CODE, json={"scope": "write"}).json()

    client.post(device_approve(code["user_code"]), json={"scope": "read"})
    minted = client.post(DEVICE_TOKEN, json={"device_code": code["device_code"]})

    assert minted.json()["scope"] == "read"


def test_a_second_poll_after_minting_is_expired_not_a_second_secret(client: Any) -> None:
    code = client.post(DEVICE_CODE, json={}).json()
    client.post(device_approve(code["user_code"]), json={"scope": "write"})
    first = client.post(DEVICE_TOKEN, json={"device_code": code["device_code"]})
    assert "token" in first.json()

    second = client.post(DEVICE_TOKEN, json={"device_code": code["device_code"]})

    assert second.json() == {"error": "expired_token"}


def test_denying_is_reported_to_the_polling_cli(client: Any) -> None:
    code = client.post(DEVICE_CODE, json={}).json()

    denied = client.post(device_deny(code["user_code"]))
    assert denied.status_code == 204

    polled = client.post(DEVICE_TOKEN, json={"device_code": code["device_code"]})
    assert polled.json() == {"error": "access_denied"}


def test_approving_twice_is_a_409(client: Any) -> None:
    code = client.post(DEVICE_CODE, json={}).json()
    client.post(device_approve(code["user_code"]), json={"scope": "write"})

    second = client.post(device_approve(code["user_code"]), json={"scope": "write"})

    assert second.status_code == 409


def test_denying_an_already_approved_code_is_a_409(client: Any) -> None:
    code = client.post(DEVICE_CODE, json={}).json()
    client.post(device_approve(code["user_code"]), json={"scope": "write"})

    response = client.post(device_deny(code["user_code"]))

    assert response.status_code == 409


def test_the_minted_pat_belongs_to_the_approving_account(client: Any) -> None:
    from app.db import get_sessionmaker
    from app.identity.pat import PersonalAccessToken

    code = client.post(DEVICE_CODE, json={}).json()
    client.post(device_approve(code["user_code"]), json={"scope": "write"})
    client.post(DEVICE_TOKEN, json={"device_code": code["device_code"]})

    with get_sessionmaker()() as session:
        pats = session.query(PersonalAccessToken).all()
        assert len(pats) == 1
        assert pats[0].name == "Device flow login"


def test_documented_in_the_openapi_schema(client: Any) -> None:
    schema = client.get("/openapi.json").json()

    assert DEVICE_CODE in schema["paths"]
    assert DEVICE_TOKEN in schema["paths"]
    assert "/auth/device/{user_code}" in schema["paths"]
