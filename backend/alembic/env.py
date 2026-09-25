"""Alembic environment.

Three things here are load-bearing and all are easy to get wrong silently:

1. **`app.models`, `app.identity.models`, `app.identity.pat`, `app.identity.pandan_link` and
   `app.identity.device_authorization` are all imported**, so `Base.metadata` carries every table —
   board/note data and, since ADR 0012/0013 (KAN-1738/1739/1741/1743), kaya's own identity, PAT,
   linked-pandan-credential and device-flow tables too, all on the one shared `Base`
   (`app/models/base.py`). Autogenerate diffs the database against this metadata, so a run where a
   package's models were never imported sees a database full of tables that "aren't in the model"
   and cheerfully writes a migration that DROPS them.
2. **The URL comes from `app.config`**, not from `alembic.ini`. One source of truth means
   `alembic upgrade head` and the app can never disagree about which database they mean.
3. **Sync only, deliberately, even though `app/identity/db.py` now has an async engine.** ADR 0012
   quarantines async to *runtime* login/session handling; migrating the schema (including the
   identity tables) is a one-shot DDL operation with no request path to protect, so it stays on
   the same synchronous connectable this file has always used. There is no async branch here and
   none is needed — `create_async_engine` would gain nothing but a second code path to maintain.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import get_settings

# Imported for its effect on Base.metadata — see (1) above. Do not "clean up" any of these.
from app.identity import device_authorization as identity_device_authorization  # noqa: F401
from app.identity import models as identity_models  # noqa: F401
from app.identity import pandan_link as identity_pandan_link  # noqa: F401
from app.identity import pat as identity_pat  # noqa: F401
from app.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a DBAPI connection (`alembic upgrade head --sql`)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run against a live connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
