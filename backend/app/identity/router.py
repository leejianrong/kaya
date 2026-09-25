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

from fastapi import FastAPI
from fastapi_users import FastAPIUsers

from app.config import Settings, get_settings
from app.identity.backend import build_auth_backend, build_github_oauth_client, oauth_configured
from app.identity.manager import get_user_manager
from app.identity.schemas import UserRead, UserUpdate


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
