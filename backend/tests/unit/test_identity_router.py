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

E2E_BYPASS = Settings(  # type: ignore[call-arg]
    _env_file=None,
    KAYA_E2E_AUTH_BYPASS="1",
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


def test_oauth_authorize_requests_read_only_scopes_not_httpx_oauths_readwrite_default() -> None:
    """`httpx_oauth.clients.github.GitHubOAuth2`'s own default is `["user", "user:email"]` —
    GitHub's plain `user` scope is read/write (its consent screen literally says so), and kaya
    only ever reads a profile to resolve an id/email at login. `read:user` is the read-only
    equivalent."""
    client = TestClient(_app(CONFIGURED))

    response = client.get("/auth/github/authorize")

    body = response.json()
    assert "scope=read%3Auser+user%3Aemail" in body["authorization_url"]
    assert "scope=user+user" not in body["authorization_url"]


def test_oauth_state_is_signed_with_the_configured_auth_secret() -> None:
    """The state parameter is an itsdangerous-signed token, not a bare client secret leaking into
    a URL — a coarse but real check that `kaya_auth_secret` is actually the thing signing it."""
    client = TestClient(_app(CONFIGURED))

    response = client.get("/auth/github/authorize")

    body = response.json()
    assert "state=" in body["authorization_url"]
    assert "test-client-secret" not in body["authorization_url"]
    assert "test-auth-secret" not in body["authorization_url"]


def test_declining_the_github_consent_screen_redirects_home_not_a_raw_json_body() -> None:
    """`/auth/github/callback` is a browser-navigated redirect target, reached only after GitHub's
    own consent screen — never a `fetch()` call. Clicking "Cancel" there sends GitHub back with
    `error=access_denied`, which used to fall through to the API's generic `{"error": {...}}` JSON
    handler and leave the tab sitting on a bare JSON body. It now redirects to `/` instead — the
    same `POST_LOGIN_REDIRECT` a successful callback uses — carrying the reason as a query param
    `Landing.svelte` reads and clears."""
    client = TestClient(_app(CONFIGURED))

    response = client.get(
        "/auth/github/callback?error=access_denied&state=irrelevant",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/?oauth_error=access_denied"


def test_a_missing_secret_half_of_the_credential_also_disables_oauth() -> None:
    half_configured = Settings(  # type: ignore[call-arg]
        _env_file=None,
        KAYA_GITHUB_OAUTH_CLIENT_ID="test-client-id",
    )

    client = TestClient(_app(half_configured))

    assert client.get("/auth/github/authorize").status_code == 404


def test_test_login_route_is_absent_without_the_bypass_flag() -> None:
    """KAN-1791: `POST /auth/test-login` (the e2e-only session seam, mirroring pandan's own shipped
    `E2E_AUTH_BYPASS`/`_register_test_login`) only exists when `KAYA_E2E_AUTH_BYPASS` is set —
    absent from both `UNCONFIGURED` and `CONFIGURED` above, neither of which sets it. A `404` here
    the same way a genuinely unknown path answers, never an auth-required `401` or `403`, is the
    property that matters: a prod deployment that never sets the flag has no bypass surface at all
    for anything to probe."""
    client = TestClient(_app(UNCONFIGURED))

    response = client.post("/auth/test-login", json={"email": "nobody@example.test"})

    assert response.status_code == 404


def test_test_login_route_registers_once_the_bypass_flag_is_set() -> None:
    """A structural check only, mirroring `test_every_identity_route_falls_under_a_reserved_spa_
    prefix` below — a real login (creating a `KayaAccount`, setting the `kayaauth` cookie) needs the
    async engine's real Postgres and belongs in `tests/integration/`, the same split
    `test_identity_manager.py`'s own module docstring already draws for every other login path."""
    app = _app(E2E_BYPASS)

    paths = {route.path for route in app.routes if hasattr(route, "path")}

    assert "/auth/test-login" in paths


def test_every_identity_route_falls_under_a_reserved_spa_prefix() -> None:
    """`app/spa.py`'s own guard (`test_spa_single_origin.py`) walks the real `app.main` app; this
    pins the narrower claim that every route *this installer* adds is one `/auth` or `/users`
    already covers, so the two tests can't drift apart silently."""
    from app.spa import is_reserved

    app = _app(CONFIGURED)
    paths = {route.path for route in app.routes if hasattr(route, "path")}

    assert paths, "the walker found nothing — the guard would pass vacuously"
    assert all(is_reserved(path) for path in paths), paths
