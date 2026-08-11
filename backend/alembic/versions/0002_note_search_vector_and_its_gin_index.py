"""note search vector, and its GIN index

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-11

KAN-557 (SLICES §V4 step 1, mirroring pandan V15). Two objects and no third:

- ``note.search_vector`` — a ``tsvector`` maintained as ``GENERATED ALWAYS AS (...) STORED`` over
  ``title`` and ``body``.
- ``ix_note_search_vector`` — a GIN index over it.

**Why a generated column rather than a trigger or an application-side reindex.** The card asks for
"must update on edit with no application-level reindex step", and a stored generated column is the
only one of the three that makes that a property of the schema rather than of somebody
remembering. Postgres recomputes the value inside every INSERT and every UPDATE that touches a
source column, so the write path in ``app/api/notes.py`` neither knows nor can forget that the
column exists — and it cannot write it wrongly either, because Postgres refuses a direct write to
a generated column. A trigger behaves identically at runtime but is a second object to keep in
step with the expression; an application-side reindex would be correct only for writes that went
through the application, which is the assumption a migration, a psql session or a future batch
endpoint breaks.

**Why the expression is shaped like this.**

``setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
setweight(to_tsvector('english', coalesce(body, '')), 'B')``

- **The regconfig is an explicit literal, and it has to be.** Bare ``to_tsvector(text)`` reads
  ``default_text_search_config``, which makes it STABLE rather than IMMUTABLE, and Postgres
  refuses a stored generated column whose expression is not immutable. So ``'english'`` is not a
  shortcut taken here: inside this mechanism there is no way to make the configuration depend on a
  column at all, and per-note languages would need a trigger — giving up the guarantee above. The
  next person wondering why the language is hard-coded should know it is forced rather than
  chosen.
- **``coalesce`` is a no-op today and is kept anyway.** ``title`` and ``body`` are both ``NOT
  NULL`` (migration ``0001``), so neither can be null right now. But ``tsvector || NULL`` is
  ``NULL``, so a later ``ALTER COLUMN body DROP NOT NULL`` would not merely stop indexing empty
  bodies — it would null the **whole** vector, and the note would vanish from search, title and
  all. That failure is silent and would be found by a user rather than by a test. Two characters
  is the right price.
- **The weights go in now, deliberately.** KAN-558 has to "rank by relevance with a documented
  tie-break", and ``ts_rank`` reads its weights out of the **stored** vector. Weighting is
  therefore a storage decision, not a query one: deferring it would leave KAN-558 either unable to
  rank a title hit above a body hit, or writing a migration that recomputes every row. A title
  outranking a body is also the right default rather than a guess — ADR 0008 makes ``title`` the
  wikilink resolution key and the only human-readable field in a list row, so a title is a
  deliberate summary of a note while a body may mention a word once in passing. Postgres' default
  weights are A=1.0 and B=0.4, so ``ts_rank`` honours this with no arguments. What KAN-558 still
  owns is the **tie-break**, which is a query concern: equal ranks have to order deterministically
  (SLICES §V4), and ``note.id`` is the only column that can promise that.
  ``test_a_title_hit_outranks_a_body_hit`` is the assertion here, because a ``setweight`` that was
  dropped, or given the same letter twice, is invisible from every other test in this slice.
- **``path`` is deliberately not in the vector, and neither is ``ref``.** The card says "over
  title and body". ADR 0008 makes ``path`` mutable metadata that nothing may grow a dependency on,
  and a search that matched a folder name would make it a search key — path-as-identity arriving
  through a side door. ``ref`` is already addressable exactly, by ``app/api/refs.py``.

**GIN rather than GiST.** For ``tsvector`` GIN is lossless: an ``@@`` lookup is answered from the
index with no heap recheck. GiST stores a fixed-length signature, so it produces false positives
that every query has to re-verify against the row, and it is the choice for data rewritten
constantly or too large to index exhaustively. Notes are read far more often than written, so
GIN's slower build and larger index are paid once while its faster lookup is collected forever —
which is Postgres' own recommendation for text search.

**``CONCURRENTLY`` was considered and is wrong here, twice.** It cannot run inside a transaction
block, and Alembic wraps a migration in one, so it would need the migration to opt out of its own
atomicity. And it would buy nothing even then: ``ADD COLUMN`` with a stored generated column
rewrites the table under ``ACCESS EXCLUSIVE``, so the blocking operation in this migration is the
column, not the index. A concurrent index behind a full table rewrite is ceremony.

**Hand-written, not autogenerated.** Autogenerate does not render this DDL the way it wants to be
read, and its output does not pass ruff (KAN-692 is open on the missing ``post_write_hook``). The
twin declaration in ``app/models/note.py`` is what keeps a *later* autogenerate from proposing to
drop this column — watched, not assumed: with the column removed from the model, autogenerate emits
``op.drop_index`` + ``op.drop_column``. ``tests/integration/test_alembic.py``
::``test_autogenerate_would_not_drop_anything`` is the standing check, and see the note on
``SEARCH_VECTOR_EXPRESSION`` below for the thing that check cannot see.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TSVECTOR

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None

SEARCH_VECTOR_EXPRESSION = (
    "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('english', coalesce(body, '')), 'B')"
)
"""The generating expression, byte for byte the string ``app.models.note`` declares.

Not imported from there, and not imported from here into there: a migration describes the schema at
one moment in history and has to keep working after the model has moved on, which is why an Alembic
revision never imports the models.

**Autogenerate does not hold the two copies together, and that was measured rather than assumed.**
Deleting the ``Computed(...)`` from the model while leaving this migration alone produces an
autogenerate diff of ``pass``: Alembic compares columns, types, nullability and indexes, but not a
generated column's expression. So the guard is ``tests/unit/test_search_vector_declaration.py``,
which reads this literal out of the file's AST and compares it against the model's. Deleting the
whole *column* from the model does emit ``op.drop_column``, which is the half of CLAUDE.md's second
inherited trap that works exactly as advertised.
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "note",
        sa.Column(
            "search_vector",
            TSVECTOR(),
            sa.Computed(SEARCH_VECTOR_EXPRESSION, persisted=True),
            # NOT NULL, which the `coalesce` above makes unconditionally true. It is here as an
            # alarm rather than as a constraint: the only way to violate it is to edit the
            # expression into one that can return NULL, and then an INSERT fails loudly instead of
            # storing a note that silently cannot be found.
            nullable=False,
        ),
    )
    # `op.f()` marks the name as final, exactly as `0001` does for `ix_note_owner_id`. It is spelled
    # out rather than left to `Base`'s `ix_%(column_0_label)s` convention because the model has to
    # name it too (autogenerate compares index names), and the value here is what that convention
    # would produce for this column anyway.
    op.create_index(
        op.f("ix_note_search_vector"),
        "note",
        ["search_vector"],
        unique=False,
        postgresql_using="gin",
    )


def downgrade() -> None:
    """Downgrade schema.

    Reverse order. Dropping the column would take the index with it, but the drop is explicit so
    this reads as the mirror of ``upgrade`` — and so that a later index over some *other* column
    cannot be silently orphaned by an edit here. Proven by
    ``tests/integration/test_note_search_vector.py``
    ::``test_downgrade_removes_the_column_and_the_index``, which runs it.
    """
    op.drop_index(op.f("ix_note_search_vector"), table_name="note")
    op.drop_column("note", "search_vector")
