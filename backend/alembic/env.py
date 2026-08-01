"""Alembic environment.

Two things here are load-bearing and both are easy to get wrong silently:

1. **`app.models` is imported**, so `Base.metadata` carries every table. Autogenerate diffs the
   database against this metadata, so a run where the models were never imported sees a database
   full of tables that "aren't in the model" and cheerfully writes a migration that DROPS them.
   The import stays even while `app/models/` is empty — the day the first model lands, this file
   must already be right.
2. **The URL comes from `app.config`**, not from `alembic.ini`. One source of truth means
   `alembic upgrade head` and the app can never disagree about which database they mean.

Sync only. ADR 0001 forecloses an async engine, so there is no async branch here.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import get_settings

# Imported for its effect on Base.metadata — see (1) above. Do not "clean up" this import.
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
