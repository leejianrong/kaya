"""``note.search_vector`` against a real Postgres 17 — KAN-557, SLICES §V4's integration row.

Everything about a generated column is a claim about what Postgres does, so there is nothing here
the fast layer could have asserted. ``Computed(..., persisted=True)`` in the model and
``GENERATED ALWAYS AS (...) STORED`` in migration ``0002`` are both *descriptions*; the property
the card actually buys — "must update on edit with no application-level reindex step" — is only
visible from a database that has recomputed the value.

Four things are proven, and they are deliberately different claims:

1. **The column is generated and stored**, read out of the catalogue rather than inferred. A plain
   ``tsvector`` column populated once by the migration would satisfy every "is it there?" assertion
   and then go stale on the first edit.
2. **It follows a real edit through the real route.** The edit that matters is the one the product
   performs, so the body and title edits below go through ``PATCH /api/v1/notes/{ref}`` — full
   Starlette, the principal resolver, the ref resolver and the ORM write path. A raw-SQL ``UPDATE``
   would pass while the ORM did something that bypassed the column, which is the failure mode a
   trigger-based or application-side reindex has and this one is supposed not to.
3. **Nothing can write it.** That is what makes "no reindex step" un-bypassable rather than merely
   unnecessary: Postgres refuses the write, so a well-meaning future maintenance script cannot put a
   wrong value in.
4. **It finds notes**, by a word in the body and by a word in the title, with the title ranking
   higher. Present-but-useless is the quiet failure of a search column, and the weighting in
   particular is invisible from everything else here — KAN-558's ranking rests on it.

There is no endpoint in this card (KAN-558 owns ``?q=``), so the queries below are direct. That is
the right shape: what is under test is the column, and a route would put a second thing in the way.

**No ``import app.*`` at module top** — see the package docstring, and pandan's PR #17 trap.
"""

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, text

BACKEND_ROOT = Path(__file__).resolve().parents[2]

ALICE_TOKEN = "a-caller-supplied-string-kaya-does-not-parse"
ALICE_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")

NOTES = "/api/v1/notes"

# `user` is reserved in Postgres, so every hand-written statement against it quotes the name.
INSERT_USER = text('INSERT INTO "user" (id, email) VALUES (:id, :email)')
INSERT_NOTE = text(
    "INSERT INTO note (owner_id, title, body) VALUES (:owner_id, :title, :body) RETURNING ref"
)
# `::text` because psycopg has no Python type for `tsvector` and Postgres' own rendering
# (`'runbook':1A 'step':2B`) is exactly what needs asserting — the lexemes *and* their weights.
READ_VECTOR = text("SELECT search_vector::text FROM note WHERE ref = :ref")


class FakeUpstream:
    """Pandan, faked at the HTTP boundary (ADR 0002's Protocol seam). Kaya holds no credential."""

    def __init__(self) -> None:
        self.known: dict[str, Any] = {}

    def introspect(self, bearer: str) -> Any:
        return self.known.get(bearer)


def _alembic_config() -> Any:
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


@pytest.fixture
def upstream() -> FakeUpstream:
    return FakeUpstream()


@pytest.fixture
def engine(database_url: str) -> Any:
    """The schema at head and an empty ``note`` table, for the tests that need no HTTP."""
    from alembic import command

    from app.db import get_engine

    command.upgrade(_alembic_config(), "head")
    engine = get_engine()
    with engine.begin() as connection:
        connection.execute(text('TRUNCATE TABLE note, "user" CASCADE'))
        connection.execute(INSERT_USER, {"id": ALICE_ID, "email": "alice@example.com"})
    return engine


@pytest.fixture
def client(database_url: str, upstream: FakeUpstream) -> Iterator[Any]:
    """The real app with pandan swapped out, exactly as ``test_notes_api.py`` builds it.

    A fresh ``PrincipalCache`` per test, because the cache is process-wide by design and one
    surviving a ``TRUNCATE`` serves a principal whose mirror row no longer exists — the next INSERT
    then fails on the foreign key, which reads as a flake and is not one.
    """
    from typing import Annotated

    from alembic import command
    from fastapi import Depends
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from app.auth.cache import PrincipalCache
    from app.auth.dependencies import get_resolver, reset_auth
    from app.auth.mirror import SqlAlchemyPrincipalMirror
    from app.auth.principal import Principal
    from app.auth.resolver import PrincipalResolver
    from app.auth.single_flight import SingleFlight
    from app.db import get_session, get_sessionmaker
    from app.main import app

    command.upgrade(_alembic_config(), "head")

    def empty() -> None:
        with get_sessionmaker()() as session:
            session.execute(text('TRUNCATE TABLE note, "user" CASCADE'))
            session.commit()

    empty()
    reset_auth()
    upstream.known[ALICE_TOKEN] = Principal(id=ALICE_ID, email="alice@example.com")
    cache = PrincipalCache(positive_ttl=60.0, negative_ttl=10.0)
    single_flight = SingleFlight()

    def resolver(session: Annotated[Session, Depends(get_session)]) -> PrincipalResolver:
        return PrincipalResolver(
            upstream=upstream,
            mirror=SqlAlchemyPrincipalMirror(session),
            cache=cache,
            single_flight=single_flight,
        )

    app.dependency_overrides[get_resolver] = resolver
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        reset_auth()
        empty()


def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {ALICE_TOKEN}"}


def create(client: Any, **fields: str) -> dict[str, Any]:
    fields.setdefault("title", "a note")
    response = client.post(NOTES, json=fields, headers=auth())
    assert response.status_code == 201, response.text
    return response.json()


def vector_of(engine: Any, ref: str) -> str:
    with engine.connect() as connection:
        return connection.execute(READ_VECTOR, {"ref": ref}).scalar_one()


def insert(engine: Any, *, title: str, body: str = "") -> str:
    with engine.begin() as connection:
        return connection.execute(
            INSERT_NOTE, {"owner_id": ALICE_ID, "title": title, "body": body}
        ).scalar_one()


# --- The column is what it claims to be -----------------------------------------------------------


def test_the_column_is_a_stored_generated_column(engine: Any) -> None:
    """Read out of the catalogue, not inferred from behaviour.

    ``attgenerated`` is ``'s'`` for stored and ``''`` for a plain column, so this is the one
    assertion that tells a generated column apart from one somebody populated once by hand — the
    mutation that breaks the card while leaving every "the value is right" test green on insert.
    """
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT a.attgenerated, a.attnotnull, t.typname, "
                "       pg_get_expr(d.adbin, d.adrelid) AS expression "
                "FROM pg_attribute a "
                "JOIN pg_type t ON t.oid = a.atttypid "
                "LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum "
                "WHERE a.attrelid = 'note'::regclass AND a.attname = 'search_vector'"
            )
        ).one()

    assert row.attgenerated == "s", "the column is not GENERATED ... STORED"
    assert row.typname == "tsvector"
    assert row.attnotnull is True, "the `coalesce` makes NOT NULL free; see migration 0002"

    # The expression, as Postgres re-rendered it. Both source columns and both weights are in it.
    assert "to_tsvector" in row.expression
    assert "'english'" in row.expression
    assert "title" in row.expression and "body" in row.expression
    assert "'A'" in row.expression and "'B'" in row.expression
    assert "path" not in row.expression, "`path` is deliberately not searchable (ADR 0008)"


def test_the_gin_index_is_on_the_search_vector(engine: Any) -> None:
    """GIN, and over the right column. An index on the wrong column is a fast query for nothing."""
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT am.amname, "
                "       array_agg(a.attname ORDER BY a.attnum) AS columns "
                "FROM pg_class i "
                "JOIN pg_index ix ON ix.indexrelid = i.oid "
                "JOIN pg_am am ON am.oid = i.relam "
                "JOIN pg_attribute a ON a.attrelid = ix.indrelid AND a.attnum = ANY(ix.indkey) "
                "WHERE i.relname = 'ix_note_search_vector' "
                "GROUP BY am.amname"
            )
        ).one()

    assert row.amname == "gin", "GiST would be lossy here; see migration 0002"
    assert list(row.columns) == ["search_vector"]


# --- It maintains itself --------------------------------------------------------------------------


def test_the_vector_is_populated_by_the_insert_alone(engine: Any) -> None:
    """A hand-written INSERT naming only ``title`` and ``body``. No application code involved."""
    ref = insert(engine, title="runbook", body="restart the pods")

    vector = vector_of(engine, ref)

    # `'runbook':1A` — position 1, weight A, because the title is the first thing concatenated.
    assert "'runbook':1A" in vector
    # And stemmed: `pods` is stored as `pod`, which is why a search for `pod` finds this note.
    assert "'pod'" in vector


def test_a_body_edit_through_the_api_updates_the_vector(client: Any, engine: Any) -> None:
    """SLICES §V4's integration row, through the route a person actually uses.

    ``PATCH`` with a body is the whole card in one assertion: nothing in ``app/api/notes.py``
    mentions ``search_vector``, and the vector still moves.
    """
    created = create(client, title="runbook", body="restart the pods")
    before = vector_of(engine, created["ref"])
    assert "'pod'" in before

    edited = client.patch(
        f"{NOTES}/{created['ref']}",
        json={"body": "drain the node instead"},
        headers=auth(),
    )
    assert edited.status_code == 200, edited.text

    after = vector_of(engine, created["ref"])
    assert "'drain'" in after, "the vector did not follow the edit"
    assert "'pod'" not in after, "the old body is still indexed, so the vector was appended to"
    assert "'runbook':1A" in after, "an untouched title lost its entry"


def test_a_title_edit_through_the_api_updates_the_vector(client: Any, engine: Any) -> None:
    """The other source column, and the one whose weight has to survive the rewrite."""
    created = create(client, title="runbook", body="restart the pods")

    edited = client.patch(f"{NOTES}/{created['ref']}", json={"title": "playbook"}, headers=auth())
    assert edited.status_code == 200, edited.text

    after = vector_of(engine, created["ref"])
    assert "'playbook':1A" in after, "the new title is missing, or lost its A weight"
    assert "'runbook'" not in after
    assert "'pod'" in after, "an untouched body lost its entry"


def test_a_delete_and_recreate_does_not_need_a_reindex(client: Any, engine: Any) -> None:
    """The third write verb: a fresh note is searchable with no step in between."""
    created = create(client, title="ephemeral", body="mentions kubernetes once")
    assert client.delete(f"{NOTES}/{created['ref']}", headers=auth()).status_code == 204

    again = create(client, title="ephemeral", body="mentions kubernetes once")
    assert "'kubernet'" in vector_of(engine, again["ref"])


# --- Nothing can write it -------------------------------------------------------------------------


def test_postgres_refuses_a_direct_insert_into_the_column(engine: Any) -> None:
    """The property that makes "no reindex step" un-bypassable rather than merely unnecessary."""
    from sqlalchemy.exc import DatabaseError

    with pytest.raises(DatabaseError) as raised, engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO note (owner_id, title, search_vector) "
                "VALUES (:owner_id, :title, 'lies'::tsvector)"
            ),
            {"owner_id": ALICE_ID, "title": "smuggled"},
        )

    assert "search_vector" in str(raised.value)


def test_postgres_refuses_a_direct_update_of_the_column(engine: Any) -> None:
    """The shape a maintenance script would take, refused."""
    from sqlalchemy.exc import DatabaseError

    ref = insert(engine, title="runbook", body="restart the pods")

    with pytest.raises(DatabaseError) as raised, engine.begin() as connection:
        connection.execute(
            text("UPDATE note SET search_vector = 'lies'::tsvector WHERE ref = :ref"), {"ref": ref}
        )

    assert "search_vector" in str(raised.value)
    assert "'runbook':1A" in vector_of(engine, ref), "the refused write still changed something"


def test_the_orm_write_path_is_refused_too_rather_than_silently_ignored(engine: Any) -> None:
    """Assigning the attribute on a persistent ``Note`` fails the flush. This was worth checking.

    The expectation going in was that ``Computed`` marks the column read-only, so SQLAlchemy would
    leave an assignment out of the UPDATE and the write would be a silent no-op. It does not.
    ``Computed`` stops SQLAlchemy *generating* a value; an attribute the caller set explicitly is
    still in the dirty set and still emitted, so the statement reaches Postgres as
    ``UPDATE note SET updated_at=now(), search_vector=%(search_vector)s`` and comes back
    ``psycopg.errors.GeneratedAlways``.

    That is the better outcome and it is worth pinning: there is no layer of this stack in which
    maintaining the column by hand looks like it worked. A silent no-op would have been the more
    dangerous behaviour — a reindex script that appeared to run.

    Nothing is written, either: the transaction fails whole, so the ``updated_at`` the same
    statement carried does not move and ADR 0009's token is not disturbed by the attempt.
    """
    from sqlalchemy.exc import ProgrammingError

    from app.db import get_sessionmaker
    from app.models import Note

    ref = insert(engine, title="runbook", body="restart the pods")
    before = vector_of(engine, ref)

    with pytest.raises(ProgrammingError) as raised, get_sessionmaker()() as session:
        note = session.execute(select(Note).where(Note.ref == ref)).scalar_one()
        note.search_vector = "'lies':1A"
        session.commit()

    assert "GeneratedAlways" in type(raised.value.orig).__name__ + str(raised.value)
    assert "search_vector" in str(raised.value)
    assert vector_of(engine, ref) == before, "the refused flush still changed something"


# --- It finds notes -------------------------------------------------------------------------------


def test_a_word_in_the_body_finds_the_note(engine: Any) -> None:
    """The point of the whole column, and the SLICES §V4 property nothing else here would catch."""
    wanted = insert(engine, title="an unremarkable title", body="the incident involved a runbook")
    other = insert(engine, title="something else", body="nothing to see")

    with engine.connect() as connection:
        hits = connection.execute(
            text(
                "SELECT ref FROM note "
                "WHERE search_vector @@ plainto_tsquery('english', :q) ORDER BY id"
            ),
            {"q": "runbook"},
        ).scalars()

    assert list(hits) == [wanted], f"expected only {wanted}, and {other} exists to prove scoping"


def test_a_word_in_the_title_finds_the_note(engine: Any) -> None:
    wanted = insert(engine, title="the deployment runbook", body="no body worth indexing")
    insert(engine, title="something else", body="nothing to see")

    with engine.connect() as connection:
        hits = connection.execute(
            text("SELECT ref FROM note WHERE search_vector @@ plainto_tsquery('english', :q)"),
            {"q": "runbooks"},  # plural, and it still matches: the query is stemmed too
        ).scalars()

    assert list(hits) == [wanted]


def test_a_title_hit_outranks_a_body_hit(engine: Any) -> None:
    """The ``setweight`` calls, made visible. KAN-558's ranking is built on exactly this.

    Without them both hits score identically and ``ts_rank`` has nothing to order by, which would
    leave KAN-558's "rank by relevance" resting on insertion order.
    """
    in_the_title = insert(engine, title="kubernetes", body="unrelated prose about nothing")
    in_the_body = insert(engine, title="unrelated title", body="a passing mention of kubernetes")

    with engine.connect() as connection:
        ranked = connection.execute(
            text(
                "SELECT ref, ts_rank(search_vector, plainto_tsquery('english', :q)) AS rank "
                "FROM note WHERE search_vector @@ plainto_tsquery('english', :q) "
                "ORDER BY rank DESC, id"
            ),
            {"q": "kubernetes"},
        ).all()

    assert [row.ref for row in ranked] == [in_the_title, in_the_body]
    assert ranked[0].rank > ranked[1].rank, "the A/B weights are not in the stored vector"


# --- The downgrade actually runs ------------------------------------------------------------------


def test_downgrade_removes_the_column_and_the_index(engine: Any) -> None:
    """A downgrade nobody has executed is a migration you cannot back out of.

    ``test_migration_0001`` proves the whole chain goes to base and back; this proves the *single*
    step, which is the one an operator reaches for at 3am. Back to head at the end, unconditionally,
    because a session-scoped database left one revision behind would fail every later test in a
    confusing place.
    """
    from alembic import command

    def column_and_index() -> tuple[int, int]:
        with engine.connect() as connection:
            columns = connection.execute(
                text(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_name = 'note' AND column_name = 'search_vector'"
                )
            ).scalar_one()
            indexes = connection.execute(
                text("SELECT count(*) FROM pg_class WHERE relname = 'ix_note_search_vector'")
            ).scalar_one()
        return columns, indexes

    assert column_and_index() == (1, 1)

    try:
        command.downgrade(_alembic_config(), "0001")
        assert column_and_index() == (0, 0), "downgrade left the column or the index behind"

        # And the table still works without it, which is what makes the downgrade a real escape
        # rather than a way to break the app quietly.
        assert insert(engine, title="after the downgrade", body="still writable")
    finally:
        command.upgrade(_alembic_config(), "head")

    assert column_and_index() == (1, 1)
    # Re-upgrading backfills every existing row, including the one written while it was gone.
    with engine.connect() as connection:
        backfilled = connection.execute(
            text("SELECT count(*) FROM note WHERE search_vector @@ plainto_tsquery('english', :q)"),
            {"q": "downgrade"},
        ).scalar_one()
    assert backfilled == 1, "ADD COLUMN did not compute the value for rows that already existed"
