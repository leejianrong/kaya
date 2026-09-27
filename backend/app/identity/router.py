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

from fastapi import FastAPI, Request
from fastapi_users import FastAPIUsers
from httpx_oauth.integrations.fastapi import OAuth2AuthorizeCallbackError
from starlette.responses import RedirectResponse

from app.config import Settings, get_settings
from app.identity.backend import build_auth_backend, build_github_oauth_client, oauth_configured
from app.identity.manager import get_user_manager
from app.identity.schemas import UserRead, UserUpdate

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
    page mid-navigation cannot do anything with it. `/tokens` is the only page that can currently
    reach this route (`Tokens.svelte`'s `signIn`), so it is where a declined or failed attempt
    sends you back, with a query param that page reads and clears rather than a raw exception body.
    """
    reason = exc.detail if exc.detail == _DECLINED else "oauth_failed"
    return RedirectResponse(url=f"/tokens?oauth_error={reason}", status_code=302)


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
