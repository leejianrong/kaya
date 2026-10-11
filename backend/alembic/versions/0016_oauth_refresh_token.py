"""oauth_refresh_token

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-11

KAY-171 (ADR 0016). Rotating, single-use refresh tokens for the short-lived access tokens the device
flow and the authorization_code grant now mint. Additive: a new table, nothing existing changes, and
every `kaya_pat_` already issued keeps working until it is revoked.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "oauth_refresh_token",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("personal_access_token_id", sa.BigInteger(), nullable=False),
        sa.Column("client_id", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["personal_access_token_id"],
            ["personal_access_token.id"],
            name=op.f("fk_oauth_refresh_token_personal_access_token_id_personal_access_token"),
            ondelete="cascade",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_refresh_token")),
    )
    op.create_index(
        op.f("ix_oauth_refresh_token_personal_access_token_id"),
        "oauth_refresh_token",
        ["personal_access_token_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_oauth_refresh_token_token_hash"),
        "oauth_refresh_token",
        ["token_hash"],
        unique=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_oauth_refresh_token_token_hash"), table_name="oauth_refresh_token")
    op.drop_index(
        op.f("ix_oauth_refresh_token_personal_access_token_id"), table_name="oauth_refresh_token"
    )
    op.drop_table("oauth_refresh_token")
