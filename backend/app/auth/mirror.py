"""Step 4 of ADR 0002's resolver: the local ``user`` row, created just-in-time.

The mirror exists for one reason — a note needs an owner and a foreign key needs a row to point
at — and ``app/models/user.py`` is emphatic that nothing pandan owns gets copied here. So this
module's whole job is "make sure this UUID is addressable", and it is written to be *boring* under
concurrency rather than clever.

Two people's first-ever request can arrive at once, or one agent can fire six parallel calls on a
cold cache. A read-then-insert loses that race and raises ``IntegrityError`` on somebody's very
first request, which is the worst possible moment. ``ON CONFLICT DO NOTHING`` lets Postgres settle
it, and the statement is emitted through Core rather than the ORM's unit of work because the unit
of work has no way to express it.
"""

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.auth.principal import Principal
from app.models import User


class SqlAlchemyPrincipalMirror:
    """``PrincipalMirror`` over the session the request is already holding."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def ensure(self, principal: Principal) -> None:
        """Idempotent. Runs on every cache miss, not only on a user's first ever request.

        ``id`` is pandan's UUID, supplied rather than generated (``app/models/user.py``). Email is
        left alone on conflict: refreshing it would make an authentication call a write on every
        miss, and a stale display address is a smaller problem than a write amplification on the
        request path. If a mirrored email ever needs to be current, it wants its own card.
        """
        statement = (
            insert(User)
            .values(id=principal.id, email=principal.email)
            .on_conflict_do_nothing(index_elements=[User.id])
        )
        self._session.execute(statement)
        # Committed here rather than left to a route. The mirror is a precondition for the request
        # rather than part of its work, and a route that rolls back — a 409, a validation failure —
        # must not also un-mirror a user who legitimately exists.
        self._session.commit()
