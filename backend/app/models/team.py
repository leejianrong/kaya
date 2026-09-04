"""``team``: the mirror of pandan's team, existing so ``note.team_id`` has a row to point at.

R16 (``docs/roadmap/BREADBOARD.md``), KAN-1082, ADR 0011. Kaya has no team store and never will, for
exactly the reason ``app/models/user.py`` gives for the user mirror: any column beyond an id goes
stale, and the first caller to trust a stale copy would be right to be annoyed. So this table holds
**one column and nothing else** — not a name, not a role, not a member list. Team membership itself
is never mirrored either; it is resolved live, on every check, by ``TeamAccessResolver`` calling
pandan's ``GET /api/v1/teams`` (R16.2), the same "ask the source of truth, don't cache a copy of its
opinion" discipline ADR 0002 already establishes for identity.

``id`` carries no default and no server_default, matching ``User.id``'s reasoning exactly: the value
is pandan's id for the team, supplied by whichever future card JIT-inserts this row (R16.2/R16.5),
not generated here. **Unlike ``User.id``, this is a plain integer, not a UUID** — pandan's own
``Team.id`` is a ``BigInteger`` (verified against pandan's ``backend/app/models.py``), because a
team is created inside pandan's own database rather than being pandan's opinion about an identity
minted elsewhere. Mirroring the wire type is the whole point of a mirror table; getting it wrong
here would silently truncate or reject a real team id the moment one exceeds a smaller type's
range.
"""

from sqlalchemy import BigInteger
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Team(Base):
    """One row per pandan team that kaya has seen, existing only so ``note.team_id`` has something
    to reference."""

    __tablename__ = "team"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    """Pandan's id for this team, verbatim — a ``BigInteger``, matching pandan's own column type.
    Not generated here — see the module docstring."""
