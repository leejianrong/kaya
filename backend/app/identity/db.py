"""The second engine ADR 0012 adds — async, and used by nothing outside this package.

``app/db.py``'s module docstring calls a top-level ``create_async_engine`` there "the signal
something upstream has drifted." ADR 0012 is that drift, deliberately: ``fastapi-users``' user
store is async-only (the same constraint pandan ADR 0011 hit and solved the same way — "two
engines, one database"), so kaya needs exactly one async engine, quarantined to exactly the code
that needs it.

**Same ``DATABASE_URL``, same psycopg v3 driver.** SQLAlchemy's ``postgresql+psycopg`` dialect is
unusual in supporting both ``create_engine`` and ``create_async_engine`` off the identical URL
scheme — there is no second connection string to keep in sync with the sync one in ``app/db.py``,
and no risk of the two engines quietly pointing at different databases.

Built lazily, for the same reason ``app/db.py.get_engine`` is: a module-level engine binds
``DATABASE_URL`` at import time, before the integration suite's fixture has provisioned its
throwaway Postgres.
"""

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings


@lru_cache(maxsize=1)
def get_async_engine() -> AsyncEngine:
    """The one async engine. Built on first use, then cached for the process."""
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache(maxsize=1)
def get_async_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_async_engine(), expire_on_commit=False)


async def get_async_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding an async session, closed on the way out."""
    async with get_async_sessionmaker()() as session:
        yield session


def reset_async_engine() -> None:
    """Drop the cached async engine. For fixtures that repoint ``DATABASE_URL``.

    Mirrors ``app/db.py.reset_engine`` — kept as a separate function rather than folded into it,
    since a test exercising only the sync board path has no reason to know this package exists.
    """
    get_async_sessionmaker.cache_clear()
    get_async_engine.cache_clear()
