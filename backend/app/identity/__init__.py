"""Kaya's own authorization server (ADR 0012, KAN-1738/1739).

ADR 0002 gave kaya no identity of its own: every bearer was forwarded to pandan's
``GET /api/v1/me``. ADR 0012 supersedes that — kaya mints and verifies its own credentials,
mirroring pandan ADR 0011's shape (GitHub OAuth + ``fastapi-users`` + revocable DB-backed cookie
sessions) **reimplemented independently**, not imported as a shared package, so the two apps stay
separately releasable.

This package is deliberately the *only* place ``app/db.py``'s async-engine foreclosure (ADR 0001)
does not apply — ``fastapi-users``' user store is async-only, and quarantining that requirement
here is what lets every note/team/attachment route stay on the untouched sync engine. See
``app/identity/db.py``'s module docstring for the mechanism and
``tests/unit/test_no_async_engine.py`` for the guard that enforces the quarantine.

Module layout, one-way dependency (``models`` ← ``db`` ← ``manager`` ← `backend`` ← ``router``):

- ``models.py`` — the three tables: ``kaya_account`` (the user), ``kaya_oauth_account`` (one row
  per linked OAuth provider), ``kaya_session`` (one row per live cookie session — deleting it is
  what makes logout an instant revocation, the same property pandan's ADR 0011 built this for).
- ``db.py`` — the second, async engine + session, used by nothing outside this package.
- ``manager.py`` — ``UserManager``, the one place a user is created/updated/deleted.
- ``backend.py`` — the cookie transport, the DB-backed session strategy, and the GitHub OAuth
  client — built from ``Settings``, never at import time (the same trap ``app/db.py`` and
  ``app/auth/dependencies.py`` already avoid: a module-level build binds to whatever the
  environment said before a test fixture had a chance to change it).
- ``router.py`` — ``install_identity_routes(app)``, called from ``app/main.py``. Registers the
  GitHub OAuth routes **only when** ``KAYA_GITHUB_OAUTH_CLIENT_ID``/``_CLIENT_SECRET`` are both
  set — mirroring pandan ADR 0011's "graceful boot without credentials": unset, the app still
  boots and every other route still works, login is simply unavailable.
- ``current_user.py`` — ``get_current_active_user``, a reusable cookie-session dependency for
  routes *outside* this package (``app/api/tokens.py`` is the first consumer). Hand-written rather
  than ``fastapi_users.current_user(active=True)`` — see its own module docstring for why that
  factory has no stable, importable form to hand a module-level ``Depends(...)`` to.
- ``pat.py`` / ``pat_schemas.py`` (KAN-1739, ADR 0012) — the ``personal_access_token`` table and
  the mint/hash logic for kaya's own ``kaya_pat_…`` PATs, mirroring pandan ADR 0014. **Read through
  the sync engine, not this package's async one** — see ``pat.py``'s module docstring — so it sits
  beside ``models.py`` rather than depending on anything else here at runtime.
- ``device_flow.py`` / ``device_flow_schemas.py`` / ``device_auth.py`` (KAN-1743, ADR 0013) — RFC
  8628 device-flow login: the ``device_authorization`` table, its request/response shapes, and
  ``/auth/device/*``. Mints a PAT through ``pat.py`` on the CLI's first successful poll; reads
  through the sync engine for the identical reason ``pat.py`` does.

**What KAN-1738/1739 do not yet do.** No note/team/attachment route depends on the identity this
package resolves, and no route accepts a ``kaya_pat_…`` bearer for anything — ``authorize_note``
still runs off the pandan-introspected principal (ADR 0002) until KAN-1740 retires that path and
wires a PAT bearer into its replacement. `/api/v1/tokens` (KAN-1739) is gated on the cookie-session
identity alone, precisely so minting a token has no chicken-and-egg dependency on a PAT already
existing. Pandan's own ADR 0011 shipped with the identical gap ("V6 only adds login... board
authorization arrives in V8"); this mirrors that sequencing on purpose rather than landing a
bigger, harder-to-review PR that changes login and authorization at once.
"""

from app.identity.device_auth import router as device_auth_router
from app.identity.router import install_identity_routes

__all__ = ["device_auth_router", "install_identity_routes"]
