"""The engine really does reach a real Postgres 17 over psycopg v3.

Thin on purpose — there is no schema yet (KAN-533 writes migration 0001). What it proves is the
part that is easy to get wrong once and then never notice: the driver in the URL, the version of
the server the rest of the slice will be written against, and that the lazily-built engine picks
up the `DATABASE_URL` the fixture set rather than one frozen at import.
"""

import pytest
from sqlalchemy import text


@pytest.mark.usefixtures("database_url")
def test_engine_connects_to_postgres_17(database_url: str) -> None:
    from app.db import get_engine

    engine = get_engine()

    assert engine.url.render_as_string(hide_password=True).startswith("postgresql+psycopg://")

    with engine.connect() as connection:
        version = connection.execute(text("SHOW server_version")).scalar_one()
        one = connection.execute(text("SELECT 1")).scalar_one()

    assert one == 1
    assert version.startswith("17."), f"expected Postgres 17, got {version}"


@pytest.mark.usefixtures("database_url")
def test_engine_binds_to_the_fixture_database_not_a_stale_one(database_url: str) -> None:
    """The PR #17 trap, asserted rather than remembered.

    If any module in this package imported `app.*` at collection time, the cached engine would
    still point at the developer's local database and this comparison would fail.
    """
    from app.db import get_engine

    assert get_engine().url.render_as_string(hide_password=False) == database_url


@pytest.mark.usefixtures("database_url")
def test_session_factory_yields_a_usable_sync_session() -> None:
    from app.db import get_session

    sessions = get_session()
    session = next(sessions)
    try:
        assert session.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        sessions.close()
