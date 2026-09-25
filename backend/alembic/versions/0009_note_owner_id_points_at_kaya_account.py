"""note.owner_id points at kaya_account, the user mirror is dropped

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-25

ADR 0012, KAN-1740 — the schema half of cutting kaya's identity over from pandan-introspection
(ADR 0002) to kaya's own authorization server. Per the maintainer's explicit call on this cutover
(this is dev/dogfood data, no real external users at stake): **no reconciliation, no data
migration, no dual-auth transition window.** A note created before this migration keeps its old
pandan UUID in `owner_id`, with no row anywhere to back it — that note is not reachable under
anyone's new `KayaAccount` id, and re-associating it with one is the maintainer's own problem later
if they ever want it back, not something this migration (or any code in this PR) builds tooling
for. See `docs/roadmap/BREADBOARD.md`'s R19 section for the fuller writeup, and `app/auth/`'s module
docstring for how the resolver itself changed.

Three things happen, in the only order that doesn't fail on a live database:

1. **Drop `fk_note_owner_id_user`** — the constraint has to go before the table it references can.
2. **Drop the `user` table** — ADR 0002's pandan mirror. Nothing reads or writes it any more:
   `SqlAlchemyPrincipalMirror`, its only writer, is deleted (`app/auth/mirror.py` now holds only
   the unrelated `ensure_team_mirrored`, R16). Left in place it would be exactly the "dead
   configuration" ADR 0012 says not to leave behind.
3. **Add `fk_note_owner_id_kaya_account`, `NOT VALID`** — a live foreign key for every *new*
   write, without Postgres re-validating the rows already in the table. Validating would either
   fail outright (an existing `owner_id` naming a UUID `kaya_account` has never heard of is exactly
   the expected, accepted state) or require deleting/rewriting historical notes as a side effect of
   a schema migration, which is a far more destructive default than "the constraint doesn't apply
   retroactively." A future `VALIDATE CONSTRAINT` is possible once/if the maintainer decides what,
   if anything, to do with pre-cutover notes — this migration deliberately does not decide that.

Hand-written from `alembic revision --autogenerate`'s output (which got the direction of change
right but not the two things above: the drop order, which it does not reason about at all, and
`NOT VALID`, which autogenerate has no way to know is wanted since a fresh/empty database has
nothing for the difference to matter against).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint(op.f("fk_note_owner_id_user"), "note", type_="foreignkey")
    op.drop_table("user")
    op.create_foreign_key(
        op.f("fk_note_owner_id_kaya_account"),
        "note",
        "kaya_account",
        ["owner_id"],
        ["id"],
        ondelete="RESTRICT",
        postgresql_not_valid=True,
    )


def downgrade() -> None:
    """Downgrade schema. Recreates `user` exactly as migration `0001` first shaped it — this
    reverses the schema, not the data: any note re-owned or created against `kaya_account` while
    this migration was applied does not un-become a pandan-mirror-owned note on the way back
    down."""
    op.drop_constraint(op.f("fk_note_owner_id_kaya_account"), "note", type_="foreignkey")
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
    op.create_foreign_key(
        op.f("fk_note_owner_id_user"),
        "note",
        "user",
        ["owner_id"],
        ["id"],
        ondelete="RESTRICT",
    )
