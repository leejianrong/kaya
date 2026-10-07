"""The one reusable "who is this cookie session" dependency for routes outside `app/identity/`
itself. `app/api/tokens.py` is the first, and so far only, consumer.

**Not `fastapi_users.current_user(active=True)`, deliberately.** That factory method returns a
*freshly built* async function every time it's called, which is fine inside
`app/identity/router.py` (an ordinary function, called once per app boot with a concrete
`Settings`) but has no *stable, importable* form `app/api/tokens.py` could hand to
`Depends(...)` at module level without calling something at import time — precisely the trap
`app/db.py`'s lazy engine and this package's own settings-at-call-time discipline exist to avoid.

So this is a **hand-written equivalent** for the one-backend (cookie) case, built entirely from
already-stable, already-lazy pieces this package exports: `get_user_manager` and
`get_database_strategy` (both plain, importable async functions — see `app/identity/backend.py`),
plus the raw `Request.cookies` read `CookieTransport` itself would do. Reading `request.cookies`
directly, rather than resolving `KAYA_COOKIE_SECURE`/`cookie_name` through a `CookieTransport`
instance, is safe because *sending* a cookie is where those settings matter (`Secure`,
`SameSite`, `HttpOnly`) — *reading* one back is a plain name lookup, and `COOKIE_NAME` is a
constant, not a `Settings` field.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi_users.authentication.strategy.db import DatabaseStrategy

from app.identity.backend import COOKIE_NAME, get_database_strategy
from app.identity.manager import UserManager, get_user_manager
from app.identity.models import KayaAccount

UserManagerDep = Annotated[UserManager, Depends(get_user_manager)]
DatabaseStrategyDep = Annotated[DatabaseStrategy, Depends(get_database_strategy)]


async def get_current_active_user(
    request: Request,
    user_manager: UserManagerDep,
    strategy: DatabaseStrategyDep,
) -> KayaAccount:
    """`401` with no cookie, an unknown/expired token, or an inactive account — never a `403`,
    matching pandan's own `require_user`/`GET /api/v1/me` precedent: there is nothing to be
    forbidden *from* here, only a caller who either is or isn't recognised."""
    token = request.cookies.get(COOKIE_NAME)
    user = await strategy.read_token(token, user_manager) if token is not None else None
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    return user
