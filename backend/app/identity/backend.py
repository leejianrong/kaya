"""Cookie transport, the DB-backed session strategy, and the GitHub OAuth client.

Everything here is a **builder function**, not a module-level singleton. `Settings` values
(`kaya_cookie_secure`, the OAuth client id/secret) must be read fresh from `get_settings()` at call
time rather than baked in at import — the same reason `app/db.py`'s engine and
`app/auth/dependencies.py`'s cache are built lazily: a value read at import time is whatever the
environment said before a test fixture had a chance to change it, and this module is exercised by
tests that toggle "OAuth configured" on and off (KAN-1738's graceful-boot-without-credentials
requirement, mirroring pandan ADR 0011).
"""

from typing import Annotated

from fastapi import Depends, Response
from fastapi_users.authentication import AuthenticationBackend, CookieTransport
from fastapi_users.authentication.strategy.db import AccessTokenDatabase, DatabaseStrategy
from fastapi_users_db_sqlalchemy.access_token import SQLAlchemyAccessTokenDatabase
from httpx_oauth.clients.github import GitHubOAuth2
from starlette.responses import RedirectResponse

from app.config import Settings
from app.identity.manager import AsyncSessionDep
from app.identity.models import KayaSession

COOKIE_NAME = "kayaauth"
"""Distinct from `kaya.token` (kaya-client's bearer, `lib/auth.ts`'s `sessionStorage` key) and from
pandan's own `kanbanauth` cookie — the two apps no longer share a credential (ADR 0012), so nothing
requires the names to coincide, and the two origins are separate besides."""

POST_LOGIN_REDIRECT = "/tokens"
"""Where a successful `/auth/github/callback` sends the browser — the one page that can mint a
`kaya_pat_…` from a fresh cookie session."""


class RedirectingCookieTransport(CookieTransport):
    """`CookieTransport.get_login_response` is a bare `204`, correct for a `fetch()`-driven login
    but not for `/auth/github/callback`: the browser lands there by a full-page navigation GitHub
    itself makes after the consent screen, so a `204` leaves the tab on a blank page rather than
    back in the app. Overrides only the login half — `get_logout_response` is untouched and stays
    `204`, because `Tokens.svelte`'s `signOut()` calls it with `fetch()`, never a navigation, and a
    redirect there would be `fetch()` silently following it rather than the caller getting the
    empty body it expects.

    `/auth/login` shares this same transport (one `AuthenticationBackend` per `build_auth_backend`
    call) but never reaches this method in practice — `app/identity/router.py`'s own comment: it
    has no password to check, so it always answers `400` before `backend.login()` is ever called.
    """

    async def get_login_response(self, token: str) -> Response:
        response = RedirectResponse(url=POST_LOGIN_REDIRECT, status_code=302)
        return self._set_login_cookie(response, token)


def build_cookie_transport(settings: Settings) -> CookieTransport:
    return RedirectingCookieTransport(
        cookie_name=COOKIE_NAME,
        cookie_secure=settings.kaya_cookie_secure,
        cookie_httponly=True,
        cookie_samesite="lax",
    )


def build_database_strategy(
    access_token_db: AccessTokenDatabase[KayaSession],
) -> DatabaseStrategy:
    """No `lifetime_seconds` cap — logout (a row delete) is the revocation mechanism, matching
    pandan ADR 0011's own choice; an additional expiry would just be a second, redundant knob."""
    return DatabaseStrategy(access_token_db)


async def get_access_token_db(session: AsyncSessionDep):
    yield SQLAlchemyAccessTokenDatabase(session, KayaSession)


AccessTokenDbDep = Annotated[
    AccessTokenDatabase[KayaSession], Depends(get_access_token_db)
]


async def get_database_strategy(access_token_db: AccessTokenDbDep) -> DatabaseStrategy:
    return build_database_strategy(access_token_db)


def build_auth_backend(settings: Settings) -> AuthenticationBackend:
    return AuthenticationBackend(
        name="kaya-cookie",
        transport=build_cookie_transport(settings),
        get_strategy=get_database_strategy,
    )


def oauth_configured(settings: Settings) -> bool:
    """Mirrors pandan ADR 0011's graceful boot: both halves of a credential, or neither."""
    return bool(settings.kaya_github_oauth_client_id and settings.kaya_github_oauth_client_secret)


def build_github_oauth_client(settings: Settings) -> GitHubOAuth2:
    assert oauth_configured(settings), "call only when oauth_configured(settings) is True"
    return GitHubOAuth2(
        settings.kaya_github_oauth_client_id,  # type: ignore[arg-type]
        settings.kaya_github_oauth_client_secret,  # type: ignore[arg-type]
        # httpx-oauth's own default is `["user", "user:email"]` — GitHub's plain `user` scope is
        # read/write (its own consent screen: "full access, including read and write access to all
        # user data"), and kaya only ever reads a profile to resolve an id/email at login
        # (`fastapi_users`' base `UserManager.oauth_callback`, which calls nothing but
        # `GitHubOAuth2.get_id_email` — no write, no follow). `read:user` is the read-only
        # equivalent of `user`; `user:email` is kept because a private email address needs it
        # regardless (GitHub's own scope table: `read:user` alone does not return one).
        scopes=["read:user", "user:email"],
    )
