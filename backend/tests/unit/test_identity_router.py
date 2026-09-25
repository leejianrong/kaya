"""ADR 0012 (KAN-1738)'s graceful boot: the GitHub OAuth routes exist only when both halves of the
credential are set, mirroring pandan ADR 0011's own tested behaviour.

`install_identity_routes` takes `settings` directly rather than reading `get_settings()` (see
`app/identity/router.py`'s own docstring), which is what lets this file build two different
`FastAPI()` apps — one configured, one not — in the same process with no env-var monkeypatching
and no `get_settings.cache_clear()`.

No database anywhere in this file. `GET /auth/github/authorize` builds an authorization URL and
sets a CSRF cookie; neither touches `kaya_account` or the async engine, so this is exactly the kind
of "no infrastructure" case dev-playbook's fast layer is for. A test that needs a real login (a
`KayaAccount` row, a `kaya_session` row surviving logout-as-delete) belongs in
`tests/integration/test_identity_manager.py`, against the real Postgres this package's async engine
actually needs.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.identity import install_identity_routes

UNCONFIGURED = Settings(_env_file=None)  # type: ignore[call-arg]

CONFIGURED = Settings(  # type: ignore[call-arg]
    _env_file=None,
    KAYA_GITHUB_OAUTH_CLIENT_ID="test-client-id",
    KAYA_GITHUB_OAUTH_CLIENT_SECRET="test-client-secret",
    KAYA_AUTH_SECRET="test-auth-secret",
)


def _app(settings: Settings) -> FastAPI:
    app = FastAPI()
    install_identity_routes(app, settings=settings)
    return app


def test_oauth_routes_do_not_register_without_both_credentials() -> None:
    client = TestClient(_app(UNCONFIGURED))

    response = client.get("/auth/github/authorize")

    assert response.status_code == 404


def test_the_app_still_boots_and_serves_other_identity_routes_without_oauth_credentials() -> None:
    """Unset credentials are a missing *feature*, never a missing *app* (mirrors pandan ADR 0011's
    "graceful boot without credentials" and `app/config.py`'s R2/`spa_dist` fields)."""
    client = TestClient(_app(UNCONFIGURED))

    # `/auth/logout` needs an authenticated session to do anything, but the route itself exists
    # and answers `401` rather than `404` — the distinction this test is actually pinning.
    response = client.post("/auth/logout")

    assert response.status_code == 401


def test_oauth_authorize_route_registers_once_both_credentials_are_set() -> None:
    client = TestClient(_app(CONFIGURED))

    response = client.get("/auth/github/authorize")

    assert response.status_code == 200
    body = response.json()
    assert body["authorization_url"].startswith("https://github.com/login/oauth/authorize")
    assert "test-client-id" in body["authorization_url"]


def test_oauth_state_is_signed_with_the_configured_auth_secret() -> None:
    """The state parameter is an itsdangerous-signed token, not a bare client secret leaking into
    a URL — a coarse but real check that `kaya_auth_secret` is actually the thing signing it."""
    client = TestClient(_app(CONFIGURED))

    response = client.get("/auth/github/authorize")

    body = response.json()
    assert "state=" in body["authorization_url"]
    assert "test-client-secret" not in body["authorization_url"]
    assert "test-auth-secret" not in body["authorization_url"]


def test_a_missing_secret_half_of_the_credential_also_disables_oauth() -> None:
    half_configured = Settings(  # type: ignore[call-arg]
        _env_file=None,
        KAYA_GITHUB_OAUTH_CLIENT_ID="test-client-id",
    )

    client = TestClient(_app(half_configured))

    assert client.get("/auth/github/authorize").status_code == 404


def test_every_identity_route_falls_under_a_reserved_spa_prefix() -> None:
    """`app/spa.py`'s own guard (`test_spa_single_origin.py`) walks the real `app.main` app; this
    pins the narrower claim that every route *this installer* adds is one `/auth` or `/users`
    already covers, so the two tests can't drift apart silently."""
    from app.spa import is_reserved

    app = _app(CONFIGURED)
    paths = {route.path for route in app.routes if hasattr(route, "path")}

    assert paths, "the walker found nothing — the guard would pass vacuously"
    assert all(is_reserved(path) for path in paths), paths
