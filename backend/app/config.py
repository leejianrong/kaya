"""Settings, resolved from the environment.

Per PLAN §Implementation decisions the app-level keys carry a ``KAYA_`` prefix.
``DATABASE_URL`` is deliberately unprefixed: it is the name Alembic, docker-compose and the
integration fixtures already use, and inventing a second spelling for it is how a test ends up
pointed at the wrong database.

Kaya holds no long-lived credential of its own, so nothing in here is a secret. It forwards the
caller's bearer upstream (ADR 0002); ``KAYA_PANDAN_URL`` is configuration.
"""

from functools import lru_cache
from pathlib import Path

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
    """Origin of the pandan deployment that resolves principals (ADR 0002).

    Read by ``app.auth`` to build the ``GET /api/v1/me`` URL. It is configuration, not a secret —
    it appears verbatim in the `503` body so a caller can see *which* upstream is down."""

    pandan_timeout_seconds: float = Field(
        default=10.0,
        validation_alias="KAYA_PANDAN_TIMEOUT_SECONDS",
    )
    """Deadline for one introspection call.

    Generous rather than snappy, and deliberately so: pandan's API scales to zero, so the first
    call after an idle period pays a cold start. httpx's own default is 5s, which would turn a
    normal wake-up into a `503`. It is still *bounded* — an unbounded upstream call holds a kaya
    Postgres connection for the whole request (the failure mode measured in KAN-560), and slow is
    worse than down because down fails fast."""

    principal_cache_ttl_seconds: float = Field(
        default=60.0,
        validation_alias="KAYA_PRINCIPAL_CACHE_TTL_SECONDS",
    )
    """How long a resolved principal is trusted without re-asking pandan (Q6, ASSUMED).

    This is exactly how far revocation lags, and it is the one constant to turn if that matters."""

    principal_negative_cache_ttl_seconds: float = Field(
        default=10.0,
        validation_alias="KAYA_PRINCIPAL_NEGATIVE_CACHE_TTL_SECONDS",
    )
    """How long a rejection is remembered (Q6, ASSUMED).

    Short, because it is load-shedding rather than a decision: a stray ``Authorization`` header on
    a retry loop must not become one pandan round trip per request. Kept well under the positive
    TTL so a token that was rejected because it hadn't been minted yet becomes usable quickly."""

    spa_dist: Path | None = Field(
        default=None,
        validation_alias="KAYA_SPA_DIST",
    )
    """The directory holding the built SPA, served from this same origin (ADR 0010, KAN-538).

    ``None`` — unset — means the app serves the API alone, and that is the default on purpose.
    There is no directory guessed at, no ``../frontend/dist`` tried as a fallback: the one thing
    worse than not finding a build is silently serving a months-old one out of somebody's working
    tree on the day the image's copy step breaks. The container image sets this; ``make dev`` does
    not, because Vite serves the SPA on :5173 and proxies ``/api`` back.

    Set it to ``../frontend/dist`` to run the single-artifact layout from a checkout."""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings.

    Cached so the environment is read once per process. Tests that change the environment must
    call ``get_settings.cache_clear()`` — and so must ``get_engine.cache_clear()``.
    """
    return Settings()
