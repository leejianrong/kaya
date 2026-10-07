"""Database plumbing for kaya's own data: exactly one (sync) engine and one session factory.

ADR 0001 forecloses an async engine **here**. That used to be the whole story — kaya delegated
identity to pandan and had no user store, so there was nothing to be async for. ADR 0012 changes
the second half of that sentence: kaya now runs its own ``fastapi-users`` (which needs an
async-only user store, the same constraint pandan ADR 0011 hit), so a second, async engine now
exists — quarantined to ``app/identity/db.py`` and used by nothing else. If you find yourself
adding ``create_async_engine`` to *this* module, that is still the signal something has drifted:
every note/team/attachment route stays on the plain sync engine below, unconditionally.

The engine is built lazily rather than at import. A module-level ``create_engine`` binds to
whatever ``DATABASE_URL`` said at import time, which for the integration suite is *before* the
fixture provisions its throwaway Postgres.
"""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """The one engine. Built on first use, then cached for the process."""
    return create_engine(
        get_settings().database_url,
        pool_pre_ping=True,
        future=True,
    )


@lru_cache(maxsize=1)
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a sync session, rolled back and closed on the way out."""
    with get_sessionmaker()() as session:
        yield session


def reset_engine() -> None:
    """Drop the cached engine and settings. For fixtures that repoint ``DATABASE_URL``."""
    get_sessionmaker.cache_clear()
    get_engine.cache_clear()
    get_settings.cache_clear()
