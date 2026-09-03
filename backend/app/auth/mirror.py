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
from app.models import Team, User


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


def ensure_team_mirrored(session: Session, team_id: int) -> None:
    """``team``'s equivalent of ``SqlAlchemyPrincipalMirror.ensure`` — ADR 0011, R16.5.

    A plain function rather than a class: there is no ``TeamMirror`` Protocol to satisfy, because
    nothing here ever needs faking behind a seam the way the identity mirror does (there is no
    external upstream in this call — `TeamAccessResolver` already confirmed membership before this
    runs, over its own seam). ``ON CONFLICT DO NOTHING`` for the identical reason
    ``SqlAlchemyPrincipalMirror`` uses it: two callers creating their first note in a team at once
    must not race a read-then-insert into an `IntegrityError`.

    Called from ``app/api/notes.py``'s ``create_note``, and only after the caller's membership is
    confirmed — this function does not itself check anything, it only makes the id addressable, the
    same separation of concerns ``app/models/team.py``'s module docstring draws between "who may
    set this" and "does a row exist to point at".
    """
    statement = insert(Team).values(id=team_id).on_conflict_do_nothing(index_elements=[Team.id])
    session.execute(statement)
    # Not committed here, unlike the principal mirror: create_note's own transaction covers the
    # note insert and this row together, and there is no route that could roll back the note while
    # wanting the team row to survive — the two either both land or neither does.
