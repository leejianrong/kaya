"""``workspace`` and ``workspace_member``: kaya's own tenant tier (ADR 0017, KAY-174).

A workspace is a named group of accounts that share notes. It replaces ADR 0011's pandan-sourced
teams: membership is now a local table, so no permission decision calls pandan.

**No ``owner_id`` on a workspace**, like pandan's (ADR 0021). A workspace is administered by whoever
holds the ``owner`` role, and may have several. A workspace must always keep at least one, which the
membership routes enforce (``409``); nothing at this layer can.

**Roles reuse pandan's vocabulary**, ``viewer`` / ``editor`` / ``owner``, and map to the access
ladder ``READ < WRITE < MANAGE`` in ``app/auth/authorization.py``. One mapping, so a role means the
same thing in every place it is read.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

ROLE_VIEWER = "viewer"
ROLE_EDITOR = "editor"
ROLE_OWNER = "owner"
VALID_ROLES = (ROLE_VIEWER, ROLE_EDITOR, ROLE_OWNER)

MAX_NAME_LEN = 255


class Workspace(Base):
    __tablename__ = "workspace"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    name: Mapped[str] = mapped_column(String(MAX_NAME_LEN), nullable=False)
    """Display only. Not unique: two groups may reasonably both call theirs "Platform"."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class WorkspaceMember(Base):
    """One row per (workspace, account). ``ON DELETE CASCADE`` on both sides: deleting a workspace
    drops its memberships, and deleting an account drops theirs. A note is never touched by either,
    since ``note.workspace_id`` is ``RESTRICT``."""

    __tablename__ = "workspace_member"

    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id"),
        CheckConstraint(f"role IN {VALID_ROLES!r}", name="role"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("kaya_account.id", ondelete="CASCADE"), nullable=False, index=True
    )
    """The account. Indexed because "which workspaces is this caller in" is the subquery under every
    note list."""

    role: Mapped[str] = mapped_column(String(16), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
