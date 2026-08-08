"""The user mirror.

Kaya has no user store and never will (ADR 0002). Identity lives in pandan; this table is a
**mirror**, written just-in-time by the principal resolver (KAN-534) from what pandan's
``GET /api/v1/me`` returned, and it exists for exactly one reason: a note needs an owner, and a
foreign key needs a row to point at.

That reason is why the columns are so few. Anything pandan owns — display name, roles, whether the
account is active — is deliberately absent, because a mirrored copy of it would go stale and the
first person to trust the stale copy would be right to be annoyed. If a future feature needs a
field, it fetches it from pandan rather than adding a column here.

``id`` carries **no default and no server_default**. The value is pandan's UUID for that user,
supplied by the caller; generating one locally would silently mint a second identity for a person
who already has one, and the two would never converge.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class User(Base):
    """One row per pandan user that kaya has seen."""

    # `user` is a reserved word in Postgres — bare `SELECT * FROM user` does not error usefully,
    # it resolves `user` to CURRENT_USER and complains about something else entirely. The name is
    # kept anyway: SQLAlchemy and Alembic quote every identifier they emit, pandan's own table is
    # `user` (fastapi-users' default), and PLAN §S1/§S2 and ADR 0008 all say "user mirror" and
    # "owner_id → user". Renaming it here would make the schema disagree with every document that
    # describes it, to buy convenience in hand-written SQL.
    #
    # THE RULE THAT COMES WITH THAT CHOICE: any hand-written SQL must quote it — `FROM "user"`,
    # and `\d "user"` in psql. Unquoted works right up until it doesn't.
    __tablename__ = "user"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True)
    """Pandan's UUID for this user, verbatim. Not generated here — see the module docstring."""

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    """Display only, and deliberately **not** unique.

    Uniqueness is pandan's to enforce, and it enforces it against the live account list. Mirroring
    the constraint would mean that if pandan ever frees an address and reassigns it, the resolver's
    JIT insert for the new user fails on a column that is not this table's identity — a login
    broken by a copy of a rule kaya does not own. 320 is the RFC-imposed ceiling on an address.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    """When *kaya first saw* this user, not when pandan created them. Different fact, same name —
    which is why it is written down here."""

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    """Last refresh of the mirror from pandan."""
