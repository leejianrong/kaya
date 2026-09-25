"""Kaya's own authorization server (ADR 0012, KAN-1738).

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

**What this card does not yet do.** No note/team/attachment route depends on the identity this
package resolves — ``authorize_note`` still runs off the pandan-introspected principal (ADR 0002)
until KAN-1740 retires that path. Pandan's own ADR 0011 shipped with the identical gap ("V6 only
adds login... board authorization arrives in V8"); this mirrors that sequencing on purpose rather
than landing a bigger, harder-to-review PR that changes login and authorization at once.
"""

from app.identity.router import install_identity_routes

__all__ = ["install_identity_routes"]
