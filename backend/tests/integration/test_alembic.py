"""Alembic actually runs, against a real Postgres.

There are no revisions yet (KAN-533 writes `0001`), so `upgrade head` is a no-op — but a no-op
that fully exercises `env.py`: it loads the config, imports the models package, resolves the URL
from `app.config` and opens a connection. Everything that would break the day a real migration
lands breaks here first.

The second test is the trap itself. Autogenerate compares the live database against
`Base.metadata`; if `env.py` ever stops importing the models, that metadata comes back empty and
the diff turns into "drop everything". With no tables on either side the diff must be empty, and
the assertion tightens on its own as soon as a model exists.
"""

from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config():
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


@pytest.mark.usefixtures("database_url")
def test_upgrade_head_runs_against_a_real_database() -> None:
    from alembic import command

    command.upgrade(_alembic_config(), "head")


@pytest.mark.usefixtures("database_url")
def test_autogenerate_would_not_drop_anything() -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from app.db import get_engine
    from app.models import Base

    with get_engine().connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)

    dropped = [op for op in diff if isinstance(op, tuple) and str(op[0]).startswith("remove_")]
    assert dropped == [], f"autogenerate wants to drop things: {dropped}"
    assert diff == [], f"unexpected schema drift: {diff}"
