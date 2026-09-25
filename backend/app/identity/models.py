"""The three tables ``fastapi-users`` needs, on kaya's own shared ``Base`` (ADR 0012).

**Not named ``user``/``oauth_account``/``accesstoken``** — fastapi-users' own defaults — because
when these were written, ``user`` was still kaya's pandan-mirror table (``app/models/user.py``,
ADR 0002), load-bearing for every existing note's ``owner_id``. Naming these
``kaya_account``/``kaya_oauth_account``/``kaya_session`` up front meant the two tables never
collided, and by the time KAN-1740 dropped the `user` mirror entirely and re-pointed note ownership
at `kaya_account` instead, no rename was needed to get there.

Both mixins fastapi-users ships (``SQLAlchemyBaseOAuthAccountTableUUID``,
``SQLAlchemyBaseAccessTokenTableUUID``) hard-code their foreign key at ``"user.id"`` — written for
the common case where the library's own default table name is used verbatim. Since ours isn't,
``user_id`` is redeclared on both to point at ``kaya_account.id`` instead; everything else about
the mixins (columns, types, the ``GUID`` type decorator that renders as a native Postgres ``uuid``)
is untouched.

Imported from ``alembic/env.py`` for the same reason ``app/models/__init__.py``'s own docstring
gives: metadata that never saw these classes produces an autogenerate run that drops them.
"""


from fastapi_users.db import SQLAlchemyBaseOAuthAccountTableUUID, SQLAlchemyBaseUserTableUUID
from fastapi_users_db_sqlalchemy.access_token import SQLAlchemyBaseAccessTokenTableUUID
from fastapi_users_db_sqlalchemy.generics import GUID
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, relationship

from app.models.base import Base


class KayaOAuthAccount(SQLAlchemyBaseOAuthAccountTableUUID, Base):
    """One row per OAuth provider linked to a ``KayaAccount`` — today, only ``"github"``.

    Provider modularity (ADR 0011's own reasoning, mirrored): adding a second provider later is
    another row shape this table already has room for, not a schema change.
    """

    __tablename__ = "kaya_oauth_account"

    @declared_attr
    def user_id(cls) -> Mapped[GUID]:
        # Overrides the mixin's hard-coded `ForeignKey("user.id", ...)` — see module docstring.
        return mapped_column(
            GUID, ForeignKey("kaya_account.id", ondelete="cascade"), nullable=False
        )


class KayaAccount(SQLAlchemyBaseUserTableUUID, Base):
    """A human who has logged into kaya directly (ADR 0012) — the identity, since KAN-1740's
    cutover, that ``note.owner_id`` points at (migration ``0009``). ``id`` is minted here
    (fastapi-users' own ``uuid4`` default), not supplied by a caller — the opposite of the
    now-retired ``user`` mirror table's contract (ADR 0002), and correctly so: this table is the
    identity, not a copy of one kept elsewhere.
    """

    __tablename__ = "kaya_account"

    oauth_accounts: Mapped[list[KayaOAuthAccount]] = relationship(
        "KayaOAuthAccount", lazy="joined"
    )


class KayaSession(SQLAlchemyBaseAccessTokenTableUUID, Base):
    """One row per live cookie session — the ``DatabaseStrategy`` table (ADR 0012, mirroring
    pandan ADR 0011's ``access_token``). Deleting the row is what makes logout an **instant**
    revocation, unlike a self-verifying JWT a server can't invalidate before it expires on its own.
    """

    __tablename__ = "kaya_session"

    @declared_attr
    def user_id(cls) -> Mapped[GUID]:
        # Overrides the mixin's hard-coded `ForeignKey("user.id", ...)` — see module docstring.
        return mapped_column(
            GUID, ForeignKey("kaya_account.id", ondelete="cascade"), nullable=False
        )


__all__ = ["KayaAccount", "KayaOAuthAccount", "KayaSession"]
