# kaya backend

FastAPI over **sync** SQLAlchemy and psycopg v3, with Alembic wired up from day one
([ADR 0001](../docs/adr/0001-stack-inherited-from-pandan.md)).

Right now this is the walking skeleton from KAN-531: an app that boots, `GET /health`, and the
database and migration plumbing. There is no note model, no principal resolver and no `/api/v1`
yet — those are KAN-533, KAN-534 and KAN-535/536.

```bash
uv sync --all-extras
uv run uvicorn app.main:app --reload      # http://localhost:8000/health
uv run pytest tests/unit -q               # no infrastructure
uv run pytest tests/integration -q        # needs Docker; testcontainers provisions Postgres
uv run ruff check .
```

## Two rules this package is built around

**One engine, one pool, no async.** ADR 0001 forecloses an async engine: kaya delegates identity to
pandan, so it needs no async user store. `tests/unit/test_no_async_engine.py` fails if one appears.

**Keep `import app.*` inside a test or fixture body in `tests/integration/`.** A module-top import
runs at collection, before the fixture sets `DATABASE_URL`, so the engine binds to the wrong
database — it passes locally and fails in CI. That is pandan's "PR #17 trap".

## Migrations

Alembic is initialised with no revisions yet (KAN-533 writes `0001`). `alembic/env.py` imports
`app.models` so `--autogenerate` sees the metadata; without that import it would emit a migration
that drops every table.

```bash
uv run alembic revision --autogenerate -m "..."
uv run alembic upgrade head
```
