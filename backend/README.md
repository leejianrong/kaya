# kaya backend

FastAPI over **sync** SQLAlchemy and psycopg v3, with Alembic wired up from day one
([ADR 0001](../docs/adr/0001-stack-inherited-from-pandan.md)).

Right now: an app that boots and serves `GET /health`, migration `0001` (the `user` mirror, `note`,
and the `NOTE-` sequence — KAN-533), and `app/auth/` — the principal resolver (KAN-534) plus
`authorize_note` and the owner-scoped list statement (KAN-535). **There is still nothing under
`/api/v1`**, so nothing in the app depends on any of it yet; the routes are KAN-536, and they are
written against these seams rather than the other way round (ADR 0005).

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

**Every list of notes composes onto `app.auth.authorization.notes_owned_by`.** The owner filter is a
`WHERE` on the statement, not a pass over rows Postgres already returned, so another user's note is
never fetched. `tests/unit/test_no_unscoped_note_query.py` fails if `Note` reaches a `select()`
anywhere else in `app/`. Fetching a *single* note unscoped is fine and necessary — that is what
lets `authorize_note` answer `403` rather than `404` for someone else's.

## Migrations

`alembic/env.py` imports `app.models` so `--autogenerate` sees the metadata; without that import it
would emit a migration that drops every table.

```bash
uv run alembic revision --autogenerate -m "..."
uv run alembic upgrade head
```
