"""Database plumbing: exactly one engine and one session factory.

ADR 0001 forecloses an async engine. Pandan carries a second, async engine only because
``fastapi-users`` has an async-only user store; kaya delegates identity to pandan and has no user
store, so there is nothing to be async for. If you find yourself adding ``create_async_engine``
here, that is the signal something upstream has drifted — not a reason to add it.

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
