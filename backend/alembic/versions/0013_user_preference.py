"""user_preference: per-account key/value preferences

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-02

KAN-1815. One additive table, `ON DELETE CASCADE` from `kaya_account`, unique on
`(user_id, key)`. **No backfill, on purpose**: an absent row means the registry default
(`app/identity/preferences.py`), which is how every existing account gets "format on save" ON.

Schema only; nothing existing is touched. Same hand-correction as `0007`/`0008`/`0010`: the
`user_id` column type is `GUID`, imported from `fastapi_users_db_sqlalchemy.generics`.
"""

from collections.abc import Sequence

import fastapi_users_db_sqlalchemy.generics
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "user_preference",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", fastapi_users_db_sqlalchemy.generics.GUID(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["kaya_account.id"],
            name=op.f("fk_user_preference_user_id_kaya_account"),
            ondelete="cascade",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_preference")),
        sa.UniqueConstraint("user_id", "key", name="uq_user_preference_user_id_key"),
    )
    op.create_index(
        op.f("ix_user_preference_user_id"), "user_preference", ["user_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_user_preference_user_id"), table_name="user_preference")
    op.drop_table("user_preference")
