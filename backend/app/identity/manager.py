"""The one place a ``KayaAccount`` is created, updated, or deleted.

``fastapi-users`` routes every mutation through a ``BaseUserManager`` subclass rather than letting
routers touch the table directly — this is that subclass, kept intentionally thin. The two secret
attributes (`reset_password_token_secret`/`verification_token_secret`) are read from `Settings` in
``__init__``, not as class attributes fixed at import time — the same lazy-read discipline
``app/db.py`` and ``app/auth/dependencies.py`` already follow, and for the same reason: a
module-level read binds to whatever ``KAYA_AUTH_SECRET`` was before a test fixture set it.

Both secrets are unused in practice — kaya's only login path is GitHub OAuth, so there is no
password to reset and no email to verify — but ``BaseUserManager`` declares them as required
attributes regardless, so a real value (never ``None``) goes here rather than a placeholder that
would silently work until the day these flows are wired up.
"""

import uuid
from typing import Annotated

from fastapi import Depends
from fastapi_users import BaseUserManager, UUIDIDMixin
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.identity.db import get_async_session
from app.identity.models import KayaAccount, KayaOAuthAccount

AsyncSessionDep = Annotated[AsyncSession, Depends(get_async_session)]


class UserManager(UUIDIDMixin, BaseUserManager[KayaAccount, uuid.UUID]):
    def __init__(self, user_db: SQLAlchemyUserDatabase) -> None:
        super().__init__(user_db)
        secret = get_settings().kaya_auth_secret
        self.reset_password_token_secret = secret
        self.verification_token_secret = secret


async def get_user_db(session: AsyncSessionDep):
    yield SQLAlchemyUserDatabase(session, KayaAccount, KayaOAuthAccount)


UserDbDep = Annotated[SQLAlchemyUserDatabase, Depends(get_user_db)]


async def get_user_manager(user_db: UserDbDep):
    yield UserManager(user_db)
