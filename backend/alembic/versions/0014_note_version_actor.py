"""note_version actor columns

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-10

KAY-138 (ADR 0015 precondition 1). Six nullable columns on `note_version`: who made each save and
through which token. **No backfill, on purpose**: a row cut before this migration has no actor and
every client renders it as "before tracking". `actor_token_id` has no foreign key so revoking a
token never erases or nulls the record of what it did.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "note_version",
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
    )
    op.add_column("note_version", sa.Column("actor_channel", sa.String(length=16), nullable=True))
    op.add_column("note_version", sa.Column("actor_token_id", sa.BigInteger(), nullable=True))
    op.add_column(
        "note_version", sa.Column("actor_token_prefix", sa.String(length=32), nullable=True)
    )
    op.add_column(
        "note_version", sa.Column("actor_token_name", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "note_version", sa.Column("actor_token_kind", sa.String(length=32), nullable=True)
    )
    op.create_foreign_key(
        op.f("fk_note_version_actor_user_id_kaya_account"),
        "note_version",
        "kaya_account",
        ["actor_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        op.f("fk_note_version_actor_user_id_kaya_account"), "note_version", type_="foreignkey"
    )
    for column in (
        "actor_token_kind",
        "actor_token_name",
        "actor_token_prefix",
        "actor_token_id",
        "actor_channel",
        "actor_user_id",
    ):
        op.drop_column("note_version", column)
