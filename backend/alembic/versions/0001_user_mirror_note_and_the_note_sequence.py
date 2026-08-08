"""user mirror, note, and the NOTE- sequence

Revision ID: 0001
Revises:
Create Date: 2026-08-08

The first revision, and the one that fixes note identity (ADR 0008). Two tables and one sequence:

- ``user`` — the mirror of pandan's identity. Kaya has no user store (ADR 0002); this table exists
  so a note can have an owner and a foreign key can have something to point at. ``id`` therefore
  has **no default**: the value is pandan's UUID, supplied by the caller.
- ``note_ref_seq`` — the source of ``NOTE-n``. Created before ``note``, because ``note.ref``'s
  server default calls ``nextval`` on it. **Alembic autogenerate does not detect sequences**, so it
  is written by hand here and dropped by hand below; nothing will remind you.
- ``note`` — the notes themselves.

Generated with ``alembic revision --autogenerate`` against an empty Postgres 17 and then edited
(the sequence, and these comments). The autogenerate diff against this schema is asserted empty by
``tests/integration/test_alembic.py::test_autogenerate_would_not_drop_anything``, so the hand edits
cannot have drifted from the models.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None

# ---------------------------------------------------------------------------------------------
#  THE `NOTE-` PREFIX AND `note_ref_seq` ARE PERMANENT. DO NOT RENAME EITHER, HERE OR ANYWHERE.
#
#  Every ref this sequence hands out is immutable and is never reused — that is precisely what
#  makes a ref safe to write into a wikilink, a `note_link` edge, an export, an agent transcript or
#  somebody's own notes. It is also what makes the prefix impossible to change afterwards: there is
#  no migration that can rewrite the refs that already left the database, so a rename turns every
#  one of them into a dangling identifier.
#
#  Pandan hit this during a full rebrand and recorded the outcome in its ADR 0018 §"What is
#  deliberately NOT renamed": `KAN-` stayed while everything around it was renamed. If a future
#  rebrand of kaya reaches this migration hunting for the last un-renamed thing — this is not an
#  oversight, and "finishing the job" here damages data. Leave it. (ADR 0008 §Decision requires
#  this comment; the model in `app/models/note.py` carries its twin.)
# ---------------------------------------------------------------------------------------------
NOTE_REF_SEQUENCE = sa.Sequence("note_ref_seq", start=1)


def upgrade() -> None:
    """Upgrade schema."""
    # `user` is a reserved word in Postgres. Alembic quotes every identifier it emits, so this is
    # safe; hand-written SQL against this table must quote it — `FROM "user"`, `\d "user"`.
    op.create_table(
        "user",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user")),
    )

    # Before `note`: the column default below calls `nextval` on it.
    op.execute(sa.schema.CreateSequence(NOTE_REF_SEQUENCE))

    op.create_table(
        "note",
        sa.Column("id", sa.Integer(), nullable=False),
        # The ref is allocated by Postgres inside the INSERT, not assembled in Python. That is what
        # makes it atomic under concurrency and non-reusing across a rollback.
        sa.Column(
            "ref",
            sa.String(length=32),
            server_default=sa.text("'NOTE-' || nextval('note_ref_seq')"),
            nullable=False,
        ),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("path", sa.String(length=1024), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # RESTRICT, not CASCADE: a `user` row is a mirror, and a cleanup job that prunes mirrors
        # must not be able to delete prose as a side effect.
        sa.ForeignKeyConstraint(
            ["owner_id"], ["user.id"], name=op.f("fk_note_owner_id_user"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_note")),
        sa.UniqueConstraint("ref", name=op.f("uq_note_ref")),
    )
    # Postgres does not index the referencing side of a foreign key on its own, and every note read
    # is scoped by owner.
    op.create_index(op.f("ix_note_owner_id"), "note", ["owner_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema.

    Reverse order, and the sequence is dropped explicitly — it is not owned by the column, so
    dropping `note` leaves it behind and the next upgrade fails on "relation already exists".
    Proven by `tests/integration/test_migration_0001.py::test_downgrade_leaves_a_clean_schema`.
    """
    op.drop_index(op.f("ix_note_owner_id"), table_name="note")
    op.drop_table("note")
    op.execute(sa.schema.DropSequence(NOTE_REF_SEQUENCE))
    op.drop_table("user")
