"""``POST /auth/test-login`` against a real Postgres (KAN-1791) — the e2e-only cookie-session seam
that replaced the browser paste-a-token flow, mirroring pandan's own shipped
``E2E_AUTH_BYPASS``/``_register_test_login`` (``pandan/backend/app/users.py``) line for line, since
the two apps hit the identical problem for the identical reason: GitHub OAuth is kaya's only login
path, and there is no scripted way through a real consent screen in CI.

Built the same way ``tests/unit/test_identity_router.py`` builds its two apps — a bare ``FastAPI()``
plus ``install_identity_routes(app, settings=...)`` — rather than the real ``app.main.app``, so this
route's registration does not depend on which process-wide env var happened to be set the first
time ``app.main`` was ever imported in this test process. ``get_async_session``
(``app/identity/db.py``) still resolves the real throwaway Postgres regardless of that choice,
because it reads the cached ``get_settings()``/``get_async_engine()`` singletons the
``database_url`` fixture already repoints — the same thing ``test_identity_manager.py`` relies on.

**No ``import app.*`` at module top** — see ``tests/integration/conftest.py``'s package docstring
convention (PR #17's trap).
"""

from pathlib import Path
from typing import Any

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config() -> Any:
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


@pytest.fixture
def client(database_url: str) -> Any:
    from alembic import command
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.identity import install_identity_routes

    command.upgrade(_alembic_config(), "head")

    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        KAYA_E2E_AUTH_BYPASS="1",
        KAYA_AUTH_SECRET="test-auth-secret",
    )
    app = FastAPI()
    install_identity_routes(app, settings=settings)
    return TestClient(app)


def test_mints_a_real_cookie_session_that_authenticates_users_me(client: Any) -> None:
    """The whole point: the same `kayaauth` cookie `/auth/github/callback` would set, so every
    other route in the app (`get_current_active_user`, `/users/me`) treats this session identically
    to a real GitHub login — nothing downstream can tell the difference.

    `example.com`, not `.test`: this was caught by actually running the suite, not by reasoning
    about it — `UserCreate`'s `EmailStr` (fastapi-users' schema this route validates the body
    against) rejects an RFC 2606 reserved-for-testing domain as a "special-use or reserved name",
    and `scripts/test-e2e.sh`'s own direct-DB account seed bypasses that validation entirely, so it
    never would have caught the mismatch either. `frontend/e2e/fixtures.ts`'s `E2E_EMAIL` has the
    same fix and the same comment.
    """
    response = client.post(
        "/auth/test-login",
        json={"email": "kan1791-e2e@example.com"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "kayaauth" in response.cookies

    me = client.get("/users/me")
    assert me.status_code == 200
    assert me.json()["email"] == "kan1791-e2e@example.com"


def test_a_second_login_from_the_same_email_reuses_the_account(client: Any) -> None:
    """Mirrors `test_identity_manager.py`'s own "a second login reuses the row" claim for the
    GitHub path — Playwright's cleanup helpers call this seam per owning user on every run, so a
    repeat call minting a second, unrelated account would silently fork "the e2e user" in two."""
    first = client.post(
        "/auth/test-login",
        json={"email": "kan1791-repeat@example.com"},
        follow_redirects=False,
    )
    first_me = client.get("/users/me").json()

    second = client.post(
        "/auth/test-login",
        json={"email": "kan1791-repeat@example.com"},
        follow_redirects=False,
    )
    second_me = client.get("/users/me").json()

    assert first.status_code == 302
    assert second.status_code == 302
    assert first_me["id"] == second_me["id"], "a repeat test-login must not create a second account"
