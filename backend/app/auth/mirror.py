"""``team``'s JIT mirror (ADR 0011, R16.5) — the identity-side mirror this module used to hold
alongside it (``SqlAlchemyPrincipalMirror``, ADR 0002's step 4) was retired by KAN-1740: kaya's own
`KayaAccount` rows are created at login time (`app/identity/manager.py`'s `UserManager`), never
just-in-time on a note request, so there is no principal to mirror into a foreign-key-satisfying row
anymore. This is what's left, and it was never part of that mechanism — it existed beside it only by
proximity in the old module layout.
"""

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Team


def ensure_team_mirrored(session: Session, team_id: int) -> None:
    """Makes a pandan team id addressable as a foreign key, creating the mirror row just-in-time if
    it doesn't exist yet (ADR 0011, R16.5).

    A plain function rather than a class: there is no ``TeamMirror`` Protocol to satisfy, because
    nothing here ever needs faking behind a seam (there is no external upstream in this call —
    `TeamAccessResolver` already confirmed membership before this runs, over its own seam).
    ``ON CONFLICT DO NOTHING`` because two callers creating their first note in a team at once must
    not race a read-then-insert into an ``IntegrityError`` — the same reasoning R16.5's original
    identity-mirror sibling used, before KAN-1740 retired it.

    Called from ``app/api/notes.py``'s ``create_note``, and only after the caller's membership is
    confirmed — this function does not itself check anything, it only makes the id addressable, the
    same separation of concerns ``app/models/team.py``'s module docstring draws between "who may
    set this" and "does a row exist to point at".
    """
    statement = insert(Team).values(id=team_id).on_conflict_do_nothing(index_elements=[Team.id])
    session.execute(statement)
    # Not committed here: `create_note`'s own transaction covers the note insert and this row
    # together, and there is no route that could roll back the note while wanting the team row to
    # survive — the two either both land or neither does.
