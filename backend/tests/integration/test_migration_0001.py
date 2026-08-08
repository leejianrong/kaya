"""Migration `0001` against a real Postgres 17.

Two things are worth the cost of a container here, and neither can be checked from metadata:

1. **Downgrade actually undoes upgrade.** The sequence is created by hand, so it is exactly the
   kind of object a downgrade forgets — and forgetting it is invisible until someone runs
   `upgrade` a second time against the same database and hits "relation already exists".
2. **The `NOTE-` sequence allocates atomically.** ADR 0008 rests on refs being unique and never
   reused, and every alternative implementation (SELECT max + 1, a Python counter, a
   read-then-write) passes a single-threaded test and fails under two concurrent writers.

**No `import app.*` at module top** — see the package docstring. Every import is inside a body.
"""

import re
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from sqlalchemy import text

BACKEND_ROOT = Path(__file__).resolve().parents[2]

REF_PATTERN = re.compile(r"^NOTE-(\d+)$")

# `user` is a reserved word in Postgres, so every hand-written statement against it quotes the
# name. Unquoted, `INSERT INTO user` does not fail with "no such table" — Postgres reads `user` as
# CURRENT_USER and reports a syntax error somewhere else entirely, which is a bad five minutes.
INSERT_USER = text('INSERT INTO "user" (id, email) VALUES (:id, :email)')
INSERT_NOTE = text("INSERT INTO note (owner_id, title) VALUES (:owner_id, :title) RETURNING ref")


def _alembic_config():
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


@pytest.fixture
def migrated(database_url: str) -> Iterator[None]:
    """The schema at head, and back at head when the test is done.

    Deliberately not relying on some other module having migrated first: these tests are the
    migration's own, and a test file that only passes in a particular collection order is a flake
    waiting for someone to run it with `-k`.
    """
    from alembic import command

    command.upgrade(_alembic_config(), "head")
    yield
    command.upgrade(_alembic_config(), "head")


def _relations(connection) -> set[str]:
    """Every table and sequence in the public schema, as `kind:name`."""
    rows = connection.execute(
        text(
            "SELECT CASE relkind WHEN 'r' THEN 'table' ELSE 'sequence' END, relname "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND relkind IN ('r', 'S')"
        )
    ).all()
    return {f"{kind}:{name}" for kind, name in rows}


def test_upgrade_then_downgrade_leaves_a_clean_schema(migrated: None) -> None:
    """Down to base, and nothing of ours is left behind — then up again, twice-runnable.

    `alembic_version` survives on purpose: it is Alembic's own bookkeeping, and `downgrade base`
    empties it rather than dropping it.
    """
    from alembic import command

    from app.db import get_engine

    engine = get_engine()

    with engine.connect() as connection:
        after_upgrade = _relations(connection)

    assert {"table:user", "table:note", "sequence:note_ref_seq"} <= after_upgrade

    command.downgrade(_alembic_config(), "base")

    with engine.connect() as connection:
        after_downgrade = _relations(connection)
        stamped = connection.execute(text("SELECT count(*) FROM alembic_version")).scalar_one()

    assert after_downgrade == {"table:alembic_version"}, (
        f"downgrade left objects behind: {sorted(after_downgrade - {'table:alembic_version'})}"
    )
    assert stamped == 0

    # The half that catches a forgotten `DropSequence`: a second upgrade against the same database.
    command.upgrade(_alembic_config(), "head")

    with engine.connect() as connection:
        assert _relations(connection) == after_upgrade


def test_the_ref_sequence_allocates_atomically_under_concurrent_inserts(migrated: None) -> None:
    """Sixteen writers on their own connections, eight notes each, no coordination.

    A `SELECT max(...)` implementation hands the same number to two of them and the unique index
    turns it into an IntegrityError; a Python-side counter does the same without even that. Both
    pass a single-threaded test. This is the test that tells them apart.
    """
    from app.db import get_engine

    engine = get_engine()
    owner = uuid.uuid4()

    with engine.begin() as connection:
        connection.execute(INSERT_USER, {"id": owner, "email": f"{owner}@example.test"})

    writers, per_writer = 16, 8

    def insert_a_batch(worker: int) -> list[str]:
        # One connection per worker, so these really are concurrent sessions rather than
        # statements serialised down a single connection.
        with engine.begin() as connection:
            return [
                connection.execute(
                    INSERT_NOTE, {"owner_id": owner, "title": f"worker {worker} note {n}"}
                ).scalar_one()
                for n in range(per_writer)
            ]

    with ThreadPoolExecutor(max_workers=writers) as pool:
        refs = [ref for batch in pool.map(insert_a_batch, range(writers)) for ref in batch]

    assert len(refs) == writers * per_writer
    assert len(set(refs)) == len(refs), "a ref was handed out twice"

    malformed = [ref for ref in refs if not REF_PATTERN.match(ref)]
    assert malformed == [], f"a ref is not `NOTE-n`: {malformed}"
    matches = [REF_PATTERN.match(ref) for ref in refs]

    numbers = sorted(int(match.group(1)) for match in matches)
    # Contiguous: the sequence handed out exactly this many values and skipped none, so no writer
    # burned a value it then failed to use.
    assert numbers == list(range(numbers[0], numbers[0] + len(numbers)))


def test_a_rolled_back_insert_never_lends_its_ref_to_the_next_writer(migrated: None) -> None:
    """Sequences do not roll back, and that is the property being relied on.

    An implementation that "fixed" the resulting gaps — a counter table, a max()+1, anything
    transactional — would make two concurrent writers able to see the same next value. Gaps in
    `NOTE-n` are the price of uniqueness, and they are deliberate.
    """
    from app.db import get_engine

    engine = get_engine()
    owner = uuid.uuid4()

    with engine.begin() as connection:
        connection.execute(INSERT_USER, {"id": owner, "email": f"{owner}@example.test"})

    with engine.connect() as connection:
        abandoned = connection.execute(
            INSERT_NOTE, {"owner_id": owner, "title": "never committed"}
        ).scalar_one()
        connection.rollback()

    with engine.begin() as connection:
        kept = connection.execute(
            INSERT_NOTE, {"owner_id": owner, "title": "committed"}
        ).scalar_one()

    assert int(REF_PATTERN.match(kept).group(1)) > int(REF_PATTERN.match(abandoned).group(1))

    with engine.connect() as connection:
        surviving = connection.execute(
            text("SELECT count(*) FROM note WHERE ref = :ref"), {"ref": abandoned}
        ).scalar_one()

    assert surviving == 0, "the rolled-back row is back, which means it was never rolled back"


def test_a_note_cannot_outlive_its_owner_silently(migrated: None) -> None:
    """RESTRICT, watched rather than asserted from metadata.

    The failure this buys: a job that prunes stale mirror rows gets an error instead of quietly
    deleting somebody's prose.
    """
    from sqlalchemy.exc import IntegrityError

    from app.db import get_engine

    engine = get_engine()
    owner = uuid.uuid4()

    with engine.begin() as connection:
        connection.execute(INSERT_USER, {"id": owner, "email": f"{owner}@example.test"})
        connection.execute(INSERT_NOTE, {"owner_id": owner, "title": "keep me"})

    with pytest.raises(IntegrityError) as raised, engine.begin() as connection:
        connection.execute(text('DELETE FROM "user" WHERE id = :id'), {"id": owner})

    assert "fk_note_owner_id_user" in str(raised.value)


def test_a_note_gets_its_timestamps_and_defaults_from_the_database(migrated: None) -> None:
    """`body` and `path` have server defaults, so the API can create a note from a title alone."""
    from app.db import get_engine

    engine = get_engine()
    owner = uuid.uuid4()

    with engine.begin() as connection:
        connection.execute(INSERT_USER, {"id": owner, "email": f"{owner}@example.test"})
        connection.execute(INSERT_NOTE, {"owner_id": owner, "title": "bare"})
        row = connection.execute(
            text("SELECT body, path, created_at, updated_at FROM note WHERE title = 'bare'")
        ).one()

    assert row.body == ""
    assert row.path == ""
    assert row.created_at is not None
    assert row.created_at.tzinfo is not None, "timestamps are timestamptz, not naive"
    assert row.updated_at == row.created_at
