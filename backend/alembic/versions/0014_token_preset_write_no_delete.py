"""personal_access_token.scope and device_authorization.requested_scope gain `write-no-delete`

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-10

KAY-141. Widens two CHECK constraints from ('read', 'write') to ('read', 'write',
'write-no-delete'). **No data is touched**: every existing row keeps `read` or `write`, so no
existing token gains or loses a capability. Downgrade first narrows any `write-no-delete` row to
`read` (the safe direction: a token never gains a capability on the way down).
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW = "('read', 'write', 'write-no-delete')"
OLD = "('read', 'write')"


def _swap(table: str, column: str, name: str, values: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, f"{column} IN {values}")


def upgrade() -> None:
    _swap("personal_access_token", "scope", "scope", NEW)
    _swap("device_authorization", "requested_scope", "requested_scope", NEW)


def downgrade() -> None:
    op.execute("UPDATE personal_access_token SET scope = 'read' WHERE scope = 'write-no-delete'")
    op.execute(
        "UPDATE device_authorization SET requested_scope = 'read' "
        "WHERE requested_scope = 'write-no-delete'"
    )
    _swap("personal_access_token", "scope", "scope", OLD)
    _swap("device_authorization", "requested_scope", "requested_scope", OLD)
