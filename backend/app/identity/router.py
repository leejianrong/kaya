"""Assembles kaya's own auth surface and mounts it onto a live `FastAPI` app.

Unversioned (`/auth/*`, `/users/*`), like `/health` — session/identity plumbing, not a versioned
API resource, mirroring pandan ADR 0011's own placement.

**Graceful boot without credentials (ADR 0011's phrase, mirrored by ADR 0012).** The GitHub OAuth
routes register only when both `KAYA_GITHUB_OAUTH_CLIENT_ID`/`_CLIENT_SECRET` are set. Unset, the
app still boots, `/auth/logout` and `/users/me` still exist (there is simply no way to reach a
logged-in state), and nothing about the rest of kaya notices — the same shape `app/db.py`'s
`spa_dist` and `app/config.py`'s R2 fields already use for "this feature's credential wasn't
provisioned, so the feature quietly isn't available" rather than a boot failure.

`install_identity_routes` takes `settings` as a parameter (default: read fresh) rather than
reading `get_settings()` internally at import — the whole package is built this way (see this
package's `__init__.py`), specifically so a test can build two different `FastAPI()` apps, one
with OAuth configured and one without, in the same process.
"""

from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi_users import FastAPIUsers, exceptions
from fastapi_users.authentication import AuthenticationBackend
from fastapi_users.authentication.strategy.db import DatabaseStrategy
from httpx_oauth.integrations.fastapi import OAuth2AuthorizeCallbackError
from pydantic import BaseModel
from starlette.responses import RedirectResponse, Response

from app.config import Settings, get_settings
from app.identity.backend import (
    POST_LOGIN_REDIRECT,
    build_auth_backend,
    build_github_oauth_client,
    get_database_strategy,
    oauth_configured,
)
from app.identity.manager import UserManager, get_user_manager
from app.identity.schemas import UserCreate, UserRead, UserUpdate

# The one code GitHub itself hands back when a person clicks "Cancel" on the consent screen
# (https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps —
# `error=access_denied`). Anything else `OAuth2AuthorizeCallbackError.detail` could carry is either
# `None` (no `code` and no `error` at all) or `GetAccessTokenError.message`, a string straight from
# an httpx response body — not something to forward verbatim into a redirect's query string.
_DECLINED = "access_denied"


async def _redirect_declined_oauth(
    request: Request, exc: OAuth2AuthorizeCallbackError
) -> RedirectResponse:
    """`/auth/github/callback` is reached by exactly one caller: the browser, full-page-navigated
    there by GitHub itself after the consent screen — never a `fetch()`, never the CLI, never MCP.
    The API's one error shape (`{"error": {...}}`, `app/api/errors.py`'s own docstring: "every
    failure") is a contract for a caller that can read a body; a browser sitting on a bare JSON
    page mid-navigation cannot do anything with it. Shares `POST_LOGIN_REDIRECT` with a *successful*
    callback (`RedirectingCookieTransport`) rather than its own target, so both outcomes of the one
    attempt land in the one place that can say something about either — `Landing.svelte` reads and
    clears the query param this carries, the same way `Tokens.svelte` used to before that page
    stopped being the only door to a working tab.
    """
    reason = exc.detail if exc.detail == _DECLINED else "oauth_failed"
    return RedirectResponse(url=f"{POST_LOGIN_REDIRECT}?oauth_error={reason}", status_code=302)


def install_identity_routes(app: FastAPI, settings: Settings | None = None) -> None:
    settings = settings if settings is not None else get_settings()
    backend = build_auth_backend(settings)
    users = FastAPIUsers(get_user_manager, [backend])

    # `/auth/login` has no password to check against (kaya mints no passwords, GitHub OAuth is the
    # only login path) and so always answers 400 — mounted anyway, unused, for the same reason
    # pandan ADR 0011 kept it mounted: adding a second credential type later is "another client +
    # include_router, not a reshape." `/auth/logout` is the route this card actually needs: it
    # deletes the `kaya_session` row, which is the whole revocation mechanism.
    app.include_router(users.get_auth_router(backend), prefix="/auth", tags=["identity"])
    app.include_router(
        users.get_users_router(UserRead, UserUpdate), prefix="/users", tags=["identity"]
    )

    if oauth_configured(settings):
        github_client = build_github_oauth_client(settings)
        app.include_router(
            users.get_oauth_router(
                github_client,
                backend,
                settings.kaya_auth_secret,
            ),
            prefix="/auth/github",
            tags=["identity"],
        )
        # `OAuth2AuthorizeCallbackError` is an `HTTPException` subclass and would otherwise be
        # caught by `app/api/errors.py`'s blanket `StarletteHTTPException` handler — registered
        # here, not there, so the exception (not the everywhere-else API shape) picks the more
        # specific handler, and so this browser-redirect carve-out stays visible beside the one
        # route it exists for rather than buried in the general error-handling module.
        app.add_exception_handler(OAuth2AuthorizeCallbackError, _redirect_declined_oauth)

    if settings.kaya_e2e_auth_bypass:
        _register_test_login(app, backend)


class _TestLoginBody(BaseModel):
    """Body for the e2e-only `/auth/test-login` seam — just the email to get-or-create a
    `KayaAccount` for, mirroring pandan's own `_TestLoginBody`."""

    email: str


# `Annotated[..., Depends(...)]` aliases, matching this codebase's own convention
# (`app/api/tokens.py`'s `CurrentUser`/`DbSession`) rather than `= Depends(...)` inline in the
# signature — ruff's `B008` (a mutable/call default) flags the inline form, and FastAPI's own
# examples use the `Annotated` form for exactly this reason.
_UserManagerDep = Annotated[UserManager, Depends(get_user_manager)]
_DatabaseStrategyDep = Annotated[DatabaseStrategy, Depends(get_database_strategy)]


def _register_test_login(app: FastAPI, backend: AuthenticationBackend) -> None:
    """Mount `POST /auth/test-login` — an **e2e-only** session seam, gated on
    `settings.kaya_e2e_auth_bypass` (see that field's own docstring). Gets-or-creates a
    `KayaAccount` by email and issues the same revocable cookie session the GitHub flow does, so
    Playwright can exercise the app exactly as a signed-in browser without a real GitHub consent
    screen — mirrors pandan's own `E2E_AUTH_BYPASS`/`_register_test_login`
    (`pandan/backend/app/users.py`) line for line, since the two apps hit the identical problem for
    the identical reason (no scripted path through a third-party OAuth consent screen in CI).

    Takes `backend` rather than rebuilding one, so this route logs in through the exact
    `AuthenticationBackend` (cookie name, `Secure` flag, DB-backed strategy) every other login path
    in this process uses — a second, differently-configured backend here would mint a cookie the
    rest of the app might not recognise.
    """

    @app.post("/auth/test-login", tags=["identity"], include_in_schema=False)
    async def test_login(
        payload: _TestLoginBody,
        user_manager: _UserManagerDep,
        strategy: _DatabaseStrategyDep,
    ) -> Response:
        try:
            user = await user_manager.get_by_email(payload.email)
        except exceptions.UserNotExists:
            user = await user_manager.create(
                UserCreate(email=payload.email, password="e2e-not-a-real-secret")
            )
        response = await backend.login(strategy, user)
        await user_manager.on_after_login(user)
        return response
