"""Integration fixtures: a throwaway Postgres 17, provisioned by the suite itself.

Self-provisioning via testcontainers rather than a CI service block, so `pytest tests/integration`
is the same command locally and in CI (dev-playbook §A6).

**Nothing imports `app.*` at module top in this package.** A top-level import runs at collection
time, before the fixture below sets `DATABASE_URL`, so the engine binds to whatever the developer
happened to have running. It passes locally and fails in CI. That is pandan's PR #17 trap, and the
only reliable defence is the placement rule: every `import app.*` goes inside a test or fixture
body.
"""

import os
from collections.abc import Iterator

import pytest
from testcontainers.community.postgres import PostgresContainer

# Matches docker-compose.yml. ADR 0001 pins psycopg v3, so the driver is `psycopg`, not `psycopg2`.
POSTGRES_IMAGE = "postgres:17-alpine"


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    with PostgresContainer(POSTGRES_IMAGE, driver="psycopg") as postgres:
        url = postgres.get_connection_url()
        previous = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = url

        # Inside a fixture body, after the environment is set — see the module docstring.
        from app.db import reset_engine

        reset_engine()
        try:
            yield url
        finally:
            reset_engine()
            if previous is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = previous
