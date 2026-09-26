"""`/auth/device/*` end to end: real routes, real Postgres, real HTTP (ADR 0013, KAN-1743).

Gated the same way `test_tokens_api.py` is: `get_current_active_user` is overridden directly rather
than driven through a real GitHub OAuth handshake (`test_identity_manager.py`'s job), because the
seam under test here is the device-flow state machine, not the cookie session underneath it.

**No `import app.*` at module top** — see `tests/integration/conftest.py`'s package docstring
convention (PR #17's trap).
"""

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]

DEVICE_CODE = "/auth/device/code"
DEVICE_TOKEN = "/auth/device/token"


def _alembic_config() -> Any:
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


@pytest.fixture
def client(database_url: str) -> Iterator[Any]:
    """The real app with `get_current_active_user` swapped for a fixed `KayaAccount` — the human
    half of the flow. The `code`/`token` routes take no auth at all, so nothing is overridden for
    them; they are exercised as any unauthenticated caller would reach them."""
    from alembic import command
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    from app.db import get_sessionmaker
    from app.identity.current_user import get_current_active_user
    from app.identity.device_flow import poll_throttle
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
    poll_throttle._last_polled_at.clear()

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
        poll_throttle._last_polled_at.clear()


def start_login(client: Any, scope: str = "write") -> dict[str, Any]:
    response = client.post(DEVICE_CODE, json={"scope": scope})
    assert response.status_code == 200, response.text
    return response.json()


def poll(client: Any, device_code: str) -> Any:
    return client.post(DEVICE_TOKEN, json={"device_code": device_code})


def test_a_fresh_code_polls_authorization_pending(client: Any) -> None:
    code = start_login(client)

    response = poll(client, code["device_code"])

    assert response.status_code == 400
    assert response.json() == {"error": "authorization_pending"}


def test_an_unknown_device_code_is_the_same_expired_token_as_a_real_one_would_be(
    client: Any,
) -> None:
    """A stale/garbage poll must not be usable to probe whether a code ever existed."""
    response = poll(client, "this-was-never-issued")

    assert response.status_code == 400
    assert response.json() == {"error": "expired_token"}


def test_the_full_approve_and_poll_round_trip_mints_a_working_pat(client: Any) -> None:
    code = start_login(client, scope="read")
    user_code = code["user_code"]

    read = client.get(f"/auth/device/{user_code}")
    assert read.status_code == 200
    assert read.json()["status"] == "pending"
    assert read.json()["requested_scope"] == "read"

    approved = client.post(f"/auth/device/{user_code}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    minted = poll(client, code["device_code"])
    assert minted.status_code == 200
    body = minted.json()
    assert body["token"].startswith("kaya_pat_")
    assert body["scope"] == "read", "the human's approved scope, not a hardcoded default"

    listed = client.get("/api/v1/tokens").json()
    assert len(listed) == 1
    assert listed[0]["token_prefix"] == body["token_prefix"]


def test_a_second_poll_after_success_is_expired_token_not_a_second_secret(client: Any) -> None:
    """A minted PAT is shown exactly once — the same rule a token created via the Tokens UI
    already follows (R7.1)."""
    code = start_login(client)
    user_code = code["user_code"]
    client.post(f"/auth/device/{user_code}/approve")
    first = poll(client, code["device_code"])
    assert first.status_code == 200

    second = poll(client, code["device_code"])

    assert second.status_code == 400
    assert second.json() == {"error": "expired_token"}


def test_denying_makes_the_poll_answer_access_denied(client: Any) -> None:
    code = start_login(client)
    user_code = code["user_code"]

    denied = client.post(f"/auth/device/{user_code}/deny")
    assert denied.status_code == 200
    assert denied.json()["status"] == "denied"

    response = poll(client, code["device_code"])

    assert response.status_code == 400
    assert response.json() == {"error": "access_denied"}


def test_approving_an_already_resolved_code_is_a_409(client: Any) -> None:
    code = start_login(client)
    user_code = code["user_code"]
    client.post(f"/auth/device/{user_code}/deny")

    response = client.post(f"/auth/device/{user_code}/approve")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "device_code_already_resolved"


def test_a_code_no_human_has_ever_visited_is_a_404_on_the_consent_screen(client: Any) -> None:
    response = client.get("/auth/device/NOPE-CODE")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "device_code_not_found"


def test_the_consent_routes_require_a_cookie_session(client: Any) -> None:
    """The chicken-and-egg rule `app/api/tokens.py` already enforces: approving a device-flow
    login mints a token, so a `kaya_pat_…` bearer must not be able to do it on its own behalf."""
    from app.identity.current_user import get_current_active_user
    from app.main import app

    code = start_login(client)
    user_code = code["user_code"]

    # The fixture's own teardown clears every override regardless of what happens in this test, so
    # popping this one is enough — nothing needs restoring for the assertions below.
    app.dependency_overrides.pop(get_current_active_user)

    assert client.get(f"/auth/device/{user_code}").status_code == 401
    assert client.post(f"/auth/device/{user_code}/approve").status_code == 401
    assert client.post(f"/auth/device/{user_code}/deny").status_code == 401


def test_polling_faster_than_the_interval_is_slow_down(client: Any) -> None:
    code = start_login(client)

    first = poll(client, code["device_code"])
    assert first.status_code == 400
    assert first.json() == {"error": "authorization_pending"}

    second = poll(client, code["device_code"])

    assert second.status_code == 400
    assert second.json() == {"error": "slow_down"}


def test_an_outage_free_poll_after_the_interval_elapses_is_pending_again(client: Any) -> None:
    from app.identity.device_flow import poll_throttle

    code = start_login(client)
    poll(client, code["device_code"])  # first poll, records the timestamp

    # Simulate the interval having elapsed without a real sleep.
    for key in list(poll_throttle._last_polled_at):
        poll_throttle._last_polled_at[key] -= 10.0

    response = poll(client, code["device_code"])

    assert response.status_code == 400
    assert response.json() == {"error": "authorization_pending"}


def test_the_default_scope_is_write(client: Any) -> None:
    code = start_login(client)

    assert client.get(f"/auth/device/{code['user_code']}").json()["requested_scope"] == "write"
