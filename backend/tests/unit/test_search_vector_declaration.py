"""The model's declaration of ``search_vector``, pinned — because Alembic will not do it.

This file exists because of a mutation that came back **green** on KAN-557, and the green was the
finding. The assumption going in was CLAUDE.md's second inherited trap: declare the column in
``app/models/note.py`` or the next ``alembic revision --autogenerate`` drops it. Half of that is
true and was watched:

- **Delete the column declaration** and autogenerate emits ``op.drop_index(...)`` +
  ``op.drop_column('note', 'search_vector')``. So the declaration really does protect the column.
- **Delete only the ``Computed(...)``**, leaving the column declared, and autogenerate emits
  ``pass``. Alembic does not compare a generated column's expression at all — it is not part of the
  autogenerate diff — so a model that has forgotten the column is *generated* looks identical to one
  that has not.

That matters more than it sounds, because ``Computed`` in the model is what tells SQLAlchemy the
column is server-maintained. Without it the ORM would treat ``search_vector`` as an ordinary column
it may write, and the only thing standing between that and a corrupt index would be Postgres
refusing the statement at runtime — a `500` on somebody's save rather than a red build. And nothing
else would notice: the integration suite would still pass, because the *database* is still right.
The database being right is exactly the trap; the model is what the application acts on.

So the expression is pinned in two directions. The migration's literal and the model's literal are
compared byte for byte, read out of the migration's AST rather than by importing it (an Alembic
revision may not be imported for its constants — it is a script with a ``revision`` identity, and
importing one is how a test starts depending on migration load order). And the model's ``Computed``
is asserted to exist, to be ``persisted``, and to carry that same string.

Fast layer: this is all metadata, so it costs nothing and runs on every push. The behaviour it
stands in for — Postgres actually maintaining and refusing the column — is in
``tests/integration/test_note_search_vector.py``, where it needs a database.
"""

import ast
from pathlib import Path

from app.models import Note
from app.models.note import SEARCH_VECTOR_EXPRESSION

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "0002_note_search_vector_and_its_gin_index.py"
)


def module_level_literal(source: str, name: str) -> object:
    """The value of a module-level ``name = <literal>`` assignment, without executing the module."""
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} is not assigned at module level — did it get renamed?")


def test_the_migration_and_the_model_hold_the_same_expression() -> None:
    """Byte for byte. Alembic's autogenerate diff does not cover this, so something has to."""
    assert MIGRATION.exists(), "migration 0002 moved; this guard now proves nothing"

    in_the_migration = module_level_literal(
        MIGRATION.read_text(encoding="utf-8"), "SEARCH_VECTOR_EXPRESSION"
    )

    assert in_the_migration == SEARCH_VECTOR_EXPRESSION, (
        "the model's generating expression and migration 0002's have diverged. The database keeps "
        "whichever one the migration wrote, so the model is now lying about the schema and no "
        "autogenerate run will say so."
    )


def test_the_model_declares_the_column_as_a_stored_generated_column() -> None:
    """The half of the trap autogenerate does not cover, watched directly.

    Losing ``Computed`` here does not change the database and does not change any autogenerate diff.
    What it changes is what SQLAlchemy believes it may write.
    """
    column = Note.__table__.c.search_vector

    assert column.computed is not None, (
        "`search_vector` is no longer declared `Computed`, so SQLAlchemy now believes it may write "
        "the column. Autogenerate will not notice this and the integration suite will stay green, "
        "because the database is still correct — see this module's docstring."
    )
    assert column.computed.persisted is True, "`persisted=False` is VIRTUAL, which Postgres refuses"
    assert str(column.computed.sqltext) == SEARCH_VECTOR_EXPRESSION
    assert column.nullable is False


def test_the_column_is_deferred_so_a_list_read_does_not_carry_it() -> None:
    """Not correctness, but a decision with a reason, so it is pinned where the reason is.

    Every list read in the product is ``notes_owned_by(principal)``, i.e. ``select(Note)``. Without
    ``deferred`` that ships a body-sized tsvector per row to no reader at all.
    """
    assert Note.__mapper__.get_property("search_vector").deferred is True


def test_the_gin_index_is_declared_with_the_name_the_migration_gives_it() -> None:
    """Autogenerate *does* compare indexes, by name — so a mismatch reads as a drop plus an add."""
    indexes = {index.name: index for index in Note.__table__.indexes}

    assert "ix_note_search_vector" in indexes
    index = indexes["ix_note_search_vector"]
    assert [column.name for column in index.columns] == ["search_vector"]
    assert index.dialect_options["postgresql"]["using"] == "gin"
