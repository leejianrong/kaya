"""workspaces: workspace, workspace_member, note.workspace_id; drop teams

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-11

KAY-174 (ADR 0017), which supersedes ADR 0011. A workspace is kaya's own group of accounts that
share notes, with a `viewer`/`editor`/`owner` role per member.

Additive first, then destructive, in one revision:

- `workspace` and `workspace_member`, new.
- `note.workspace_id`, a nullable foreign key. `NULL` is a personal note, which is every note that
  exists, so nothing changes for anyone. `ON DELETE RESTRICT`: a workspace that still holds notes
  cannot be deleted, rather than silently turning each one into its creator's personal note.
- `note.team_id` and the `team` table are **dropped**, with no data carried over. Kaya never held
  team membership (it was asked of pandan live), and every existing note's `owner_id` is already
  unreachable after ADR 0012's cutover (BREADBOARD R19). Before running this against a database
  that holds real notes, count `note.team_id IS NOT NULL` (the deploy checklist has the query):
  those notes would lose their team-wide visibility.

The downgrade restores the empty `team` table and the column, not the data.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "workspace",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspace")),
    )
    op.create_table(
        "workspace_member",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('viewer', 'editor', 'owner')", name=op.f("ck_workspace_member_role")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["kaya_account.id"],
            name=op.f("fk_workspace_member_user_id_kaya_account"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspace.id"],
            name=op.f("fk_workspace_member_workspace_id_workspace"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspace_member")),
        sa.UniqueConstraint(
            "workspace_id", "user_id", name=op.f("uq_workspace_member_workspace_id")
        ),
    )
    op.create_index(
        op.f("ix_workspace_member_user_id"), "workspace_member", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_workspace_member_workspace_id"), "workspace_member", ["workspace_id"], unique=False
    )

    op.add_column("note", sa.Column("workspace_id", sa.BigInteger(), nullable=True))
    op.create_index(op.f("ix_note_workspace_id"), "note", ["workspace_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_note_workspace_id_workspace"),
        "note",
        "workspace",
        ["workspace_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.drop_constraint(op.f("fk_note_team_id_team"), "note", type_="foreignkey")
    op.drop_index(op.f("ix_note_team_id"), table_name="note")
    op.drop_column("note", "team_id")
    op.drop_table("team")


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table(
        "team",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_team")),
    )
    op.add_column("note", sa.Column("team_id", sa.BigInteger(), nullable=True))
    op.create_index(op.f("ix_note_team_id"), "note", ["team_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_note_team_id_team"), "note", "team", ["team_id"], ["id"], ondelete="RESTRICT"
    )

    op.drop_constraint(op.f("fk_note_workspace_id_workspace"), "note", type_="foreignkey")
    op.drop_index(op.f("ix_note_workspace_id"), table_name="note")
    op.drop_column("note", "workspace_id")

    op.drop_index(op.f("ix_workspace_member_workspace_id"), table_name="workspace_member")
    op.drop_index(op.f("ix_workspace_member_user_id"), table_name="workspace_member")
    op.drop_table("workspace_member")
    op.drop_table("workspace")
