"""``/api/v1/notes`` — the five routes, and nothing else.

Every decision with teeth in it lives one module away: identity in ``refs.py``, authorization in
``app/auth/authorization.py``, the error shape in ``errors.py``, the payload in ``schemas.py``. What
is left here is genuinely just wiring, which is the point — a route that is four lines long has
nowhere to hide a fifth spelling of a rule.

Two things to notice, because both are load-bearing:

- **No route parses an identifier.** ``NoteFromRef`` resolves it, checks it and hands back a
  ``Note``. That is ADR 0008's "resolve centrally, not per call site" made unavoidable rather than
  merely recommended: there is no identifier in scope to get wrong.
- **No route builds a note query.** A list composes onto ``notes_owned_by``, which already carries
  ``WHERE owner_id = :caller``; ``tests/unit/test_no_unscoped_note_query.py`` fails the build if
  this file ever names ``Note`` inside a ``select()``.

Deliberately absent, with the card that owns each: the `409` precondition on `PATCH` (KAN-537 —
ADR 0009 specifies plain last-write-wins for a write that omits it, so what is below is the
specified behaviour and not a stub), ``?q=`` search (KAN-558/559), and `/links` + `/backlinks`
(KAN-566, which will depend on ``NoteFromRef`` and inherit ADR 0008 for free).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.refs import NoteFromRef
from app.api.schemas import NoteCreate, NoteList, NoteRead, NoteUpdate
from app.auth import Principal, get_principal, notes_owned_by
from app.db import get_session
from app.models import Note

router = APIRouter(prefix="/api/v1", tags=["notes"])

CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
DbSession = Annotated[Session, Depends(get_session)]


@router.post(
    "/notes",
    status_code=status.HTTP_201_CREATED,
    summary="Create a note",
)
def create_note(
    payload: NoteCreate,
    principal: CurrentPrincipal,
    session: DbSession,
    response: Response,
) -> NoteRead:
    """Create a note owned by the caller.

    The ``ref``, the ``id`` and both timestamps are allocated by Postgres inside the INSERT and read
    back afterwards, never assembled here — ADR 0008 §Decision, and the reason two concurrent
    writers cannot be handed the same ref.

    The owner is the resolved principal and is not a request field. There is no route by which a
    caller can file a note against somebody else's UUID.
    """
    note = Note(owner_id=principal.id, **payload.model_dump())
    session.add(note)
    session.commit()
    session.refresh(note)

    # The canonical form, which the ref resolver accepts back verbatim (ADR 0008's round trip).
    response.headers["Location"] = f"{router.prefix}/notes/{note.ref}"
    return NoteRead.of(note)


@router.get("/notes", summary="List the caller's notes")
def list_notes(principal: CurrentPrincipal, session: DbSession) -> NoteList:
    """Every note the caller owns, newest first.

    Scoped in SQL by ``notes_owned_by``, not filtered afterwards: SLICES §V1 asks for another user's
    note to be *omitted* rather than fetched and hidden, and only the ``WHERE`` can say which
    happened. Composing here cannot lose that clause (KAN-535).

    ``updated_at DESC, id DESC`` — the second column is not decoration. Two notes written inside one
    transaction share an ``updated_at`` (``now()`` is transaction start time, per the model's own
    comment), so without a tie-break the order of a page would be whatever Postgres felt like, and
    V4's "identical queries return results in a deterministic order" would already be false here.

    No paging parameter: no card has asked for one, and ``next_cursor`` is additive to this envelope
    when one does. No ``?q=``: that is KAN-558/559.
    """
    newest_first = notes_owned_by(principal).order_by(Note.updated_at.desc(), Note.id.desc())
    return NoteList(notes=[NoteRead.of(note) for note in session.scalars(newest_first)])


@router.get("/notes/{ref}", summary="Read one note by NOTE-n or by id")
def get_note(note: NoteFromRef) -> NoteRead:
    """One note, addressed as ``NOTE-12``, ``note-12`` or ``12``.

    The whole route is the dependency. Both spellings produce byte-identical bodies on a hit and
    byte-identical `404`s on a miss because there is nothing in this function that could tell them
    apart — see ``app/api/refs.py``.
    """
    return NoteRead.of(note)


@router.patch("/notes/{ref}", summary="Edit a note, or move it")
def update_note(note: NoteFromRef, payload: NoteUpdate, session: DbSession) -> NoteRead:
    """Change ``title``, ``body`` and/or ``path``. Omitted fields are left alone.

    Moving a note between folders is this route with ``{"path": "…"}`` and nothing else — one
    column, no link rewriting, nothing to break (ADR 0008). There is no separate move endpoint
    because there is no separate operation.

    **Last-write-wins, as specified.** ADR 0009 accepts a write carrying no precondition as a plain
    overwrite on purpose, so the API stays usable from `curl` without a read-first dance. KAN-537
    adds the branch for a write that *does* carry one: an ``updated_at`` that no longer matches is
    a `409` with both bodies. That branch goes beside this one; this one is not a placeholder for
    it.
    """
    changes = payload.changes()
    for field, value in changes.items():
        setattr(note, field, value)

    # An empty PATCH is a legal no-op and must not restamp `updated_at` — that value is ADR 0009's
    # concurrency token, and a write that moves it without changing anything would invalidate every
    # other client's precondition for no reason. SQLAlchemy would emit no UPDATE anyway; committing
    # only when something changed says so out loud.
    if changes:
        session.commit()
        session.refresh(note)

    return NoteRead.of(note)


@router.delete(
    "/notes/{ref}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete a note",
)
def delete_note(note: NoteFromRef, session: DbSession) -> Response:
    """Delete the note. `204`, no body — there is nothing left to describe.

    The ref is **not** returned to the sequence. Refs are never reused (ADR 0008), so a later
    ``GET NOTE-12`` for a deleted note is a `404` forever rather than somebody else's note.
    """
    session.delete(note)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
