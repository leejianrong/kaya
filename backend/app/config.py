"""Settings, resolved from the environment.

Per PLAN §Implementation decisions the app-level keys carry a ``KAYA_`` prefix.
``DATABASE_URL`` is deliberately unprefixed: it is the name Alembic, docker-compose and the
integration fixtures already use, and inventing a second spelling for it is how a test ends up
pointed at the wrong database.

Kaya holds no long-lived credential of its own, so nothing in here is a secret. It forwards the
caller's bearer upstream (ADR 0002); ``KAYA_PANDAN_URL`` is configuration.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DATABASE_URL = "postgresql+psycopg://kaya:kaya@localhost:5432/kaya"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(
        default=DEFAULT_DATABASE_URL,
        validation_alias="DATABASE_URL",
    )
    """SQLAlchemy URL. The ``+psycopg`` driver is psycopg v3 and is not interchangeable with
    ``+psycopg2``; ADR 0001 pins v3."""

    pandan_url: str = Field(
        default="https://simple-kanban-jian.fly.dev",
        validation_alias="KAYA_PANDAN_URL",
    )
    """Origin of the pandan deployment that resolves principals (ADR 0002). Unused until KAN-534."""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings.

    Cached so the environment is read once per process. Tests that change the environment must
    call ``get_settings.cache_clear()`` — and so must ``get_engine.cache_clear()``.
    """
    return Settings()
