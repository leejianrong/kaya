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

from fastapi import Depends
from fastapi_users.authentication import AuthenticationBackend, CookieTransport
from fastapi_users.authentication.strategy.db import AccessTokenDatabase, DatabaseStrategy
from fastapi_users_db_sqlalchemy.access_token import SQLAlchemyAccessTokenDatabase
from httpx_oauth.clients.github import GitHubOAuth2

from app.config import Settings
from app.identity.manager import AsyncSessionDep
from app.identity.models import KayaSession

COOKIE_NAME = "kayaauth"
"""Distinct from `kaya.token` (kaya-client's bearer, `lib/auth.ts`'s `sessionStorage` key) and from
pandan's own `kanbanauth` cookie — the two apps no longer share a credential (ADR 0012), so nothing
requires the names to coincide, and the two origins are separate besides."""


def build_cookie_transport(settings: Settings) -> CookieTransport:
    return CookieTransport(
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
    )
