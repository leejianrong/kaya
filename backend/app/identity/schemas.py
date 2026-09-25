"""The Pydantic contract fastapi-users' routers serialize `KayaAccount` through.

Kept as thin, empty subclasses — `fastapi-users`' own `schemas.BaseUser*` already carry exactly
the fields the login/session flow needs (`id`, `email`, `is_active`, `is_superuser`,
`is_verified`); a project-specific field would go here the day one exists, not before.
"""

import uuid

from fastapi_users import schemas


class UserRead(schemas.BaseUser[uuid.UUID]):
    pass


class UserCreate(schemas.BaseUserCreate):
    pass


class UserUpdate(schemas.BaseUserUpdate):
    pass
