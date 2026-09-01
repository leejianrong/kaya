# kaya backend

FastAPI over **sync** SQLAlchemy and psycopg v3, with Alembic wired up from day one
([ADR 0001](../docs/adr/0001-stack-inherited-from-pandan.md)).

`GET /health`, `app/auth/` — the principal resolver (KAN-534) plus `authorize_note` and the
owner-scoped list statement (KAN-535) — and `app/api/`: the five `/api/v1/notes` routes over the
central ref resolver (KAN-536, with ADR 0009's optimistic-concurrency precondition on `PATCH`,
KAN-537), plus full-text search, wikilink resolution, a graph view and a board embed, added as later
slices and epics landed.

| Route | Notes |
|---|---|
| `POST /api/v1/notes` | `201` + `Location`. Owner is the caller; there is no field to say otherwise |
| `GET /api/v1/notes` | `{"notes": [...]}`, owner-scoped in SQL, newest first. `?q=` ranks by `ts_rank DESC, note.id DESC` (KAN-558/559) |
| `GET /api/v1/notes/{ref}` | `ref` is `NOTE-12`, `note-12` **or** `12` |
| `PATCH /api/v1/notes/{ref}` | Partial. Omitted fields are unchanged. Moving a note is `{"path": …}`. Optional `if_updated_at` → `409` on a stale one |
| `DELETE /api/v1/notes/{ref}` | `204`. The ref is never reused |
| `GET /api/v1/notes/{ref}/links` | Resolves the note's `[[wikilinks]]` against pandan with the caller's own PAT; unresolved on failure, never an error (KAN-566, ADR 0003) |
| `GET /api/v1/notes/{ref}/backlinks` | Every note linking to this one, answered from kaya's own tables — no upstream call (KAN-566) |
| `GET /api/v1/graph` | Every note the caller owns plus every resolved note-to-note link among them, node-and-edge shaped (KAN-1050) |
| `GET /embeds/board` | A live pandan board/view rendered read-only in a note; same PAT-forwarding, no-session shape as `/links` (KAN-1049) |

Building now, not yet on `main`: version history and attachments — see
[`docs/roadmap/BREADBOARD.md`](../docs/roadmap/BREADBOARD.md) R13/R14.

## The `PATCH` precondition (ADR 0009)

```bash
# Guarded: send back the `updated_at` you read.
curl -X PATCH …/api/v1/notes/NOTE-12 -d '{"body": "…", "if_updated_at": "2026-08-07T10:11:12.123456+00:00"}'

# Unguarded, and that is specified rather than a gap — no read-first dance required.
curl -X PATCH …/api/v1/notes/NOTE-12 -d '{"body": "…"}'
```

A stale precondition is a `409` whose body carries **both** versions, because "your write was
refused" is not actionable on prose:

```json
{"error": {"code": "note_conflict", "message": "NOTE-12 has changed since you read it: …",
           "attempted": {"ref": "NOTE-12", "body": "what you tried to write", "…": "…"},
           "stored":    {"ref": "NOTE-12", "body": "what is there now", "…": "…"}}}
```

Both are whole notes, so a client can diff them; "keep mine" is this same `PATCH` again with
`attempted`'s body and `stored`'s `updated_at`. Two things about the scope, both from the ADR: a
write with **no** `if_updated_at` is a plain last-write-wins overwrite, and a write touching only
`title`/`path` is unguarded even with a stale one, because metadata stays LWW. A write touching
`body` and `title` together is guarded and refused whole. See `app/api/concurrency.py`.

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
lets `authorize_note` answer `403` rather than `404` for someone else's, and it is why
`note_addressed_as_ref` / `note_addressed_as_id` live in `authorization.py` beside the scoped one
rather than next to the ref resolver that calls them.

**Every identifier goes through `app/api/refs.py`.** `NOTE-12`, `note-12` and `12` resolve in one
place, so `#NOTE-12` is a `400` and a missing note is the same `404` byte for byte whichever
spelling asked for it (ADR 0008). A route never sees a string; it depends on `NoteFromRef` and is
handed a `Note`.

**One error shape: `{"error": {"code", "message", …}}`.** `app/api/errors.py` un-nests what FastAPI
would otherwise wrap in `detail`, and covers Starlette's own `404`/`405` and body validation too, so
a client needs one parser rather than three.

## Migrations

`alembic/env.py` imports `app.models` so `--autogenerate` sees the metadata; without that import it
would emit a migration that drops every table.

```bash
uv run alembic revision --autogenerate -m "..."
uv run alembic upgrade head
```
