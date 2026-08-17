"""``/api/v1/notes`` — the five routes, and nothing else.

Every decision with teeth in it lives one module away: identity in ``refs.py``, authorization in
``app/auth/authorization.py``, the error shape in ``errors.py``, the payload in ``schemas.py``. What
is left here is genuinely just wiring, which is the point — a route that is four lines long has
nowhere to hide a fifth spelling of a rule.

Four things to notice, because all four are load-bearing:

- **No route parses an identifier.** ``NoteFromRef`` resolves it, checks it and hands back a
  ``Note``. That is ADR 0008's "resolve centrally, not per call site" made unavoidable rather than
  merely recommended: there is no identifier in scope to get wrong.
- **No route builds a note query.** A list composes onto ``notes_owned_by``, which already carries
  ``WHERE owner_id = :caller``; ``tests/unit/test_no_unscoped_note_query.py`` fails the build if
  this file ever names ``Note`` inside a ``select()``. Search (KAN-558) is ``notes_matching``, which
  is that same statement with two clauses added, so it is one ``WHERE`` and not two.
- **No route decides a conflict.** ADR 0009's precondition is one call to ``enforce_precondition``,
  so a second write endpoint gets the guarantee by making the same call rather than by
  reimplementing a comparison.
- **No route decides what an empty ``?q=`` means.** ``app/api/search.py`` does, before this module
  is reached, and hands the list route ``None`` or a term that is known to be non-blank.

Deliberately absent, with the card that owns each: `/links` + `/backlinks` (KAN-566, which will
depend on ``NoteFromRef`` and inherit ADR 0008 for free), and paging of any shape.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.concurrency import enforce_precondition
from app.api.refs import NoteFromRef
from app.api.schemas import NoteCreate, NoteList, NoteRead, NoteUpdate
from app.api.search import SearchTerm
from app.auth import Principal, get_principal, notes_matching, notes_owned_by
from app.db import get_session
from app.models import Note
from app.note_links import reconcile_note_links

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

    KAN-562: the body's ``[[KAN-n]]`` / ``[[EPIC-n]]`` wikilinks are recorded in ``note_link`` in
    the same transaction as the note itself, via ``reconcile_note_links``. The explicit ``flush()``
    before that call is load-bearing — it is what makes ``note.id`` (the edges' foreign key)
    available before the transaction commits, rather than relying on the implicit flush inside
    ``commit()`` to have happened first.
    """
    note = Note(owner_id=principal.id, **payload.model_dump())
    session.add(note)
    session.flush()
    reconcile_note_links(session, note)
    session.commit()
    session.refresh(note)

    # The canonical form, which the ref resolver accepts back verbatim (ADR 0008's round trip).
    response.headers["Location"] = f"{router.prefix}/notes/{note.ref}"
    return NoteRead.of(note)


@router.get("/notes", summary="List the caller's notes, or search them with ?q=")
def list_notes(principal: CurrentPrincipal, session: DbSession, term: SearchTerm) -> NoteList:
    """Every note the caller owns, newest first — or, with ``?q=``, the ones that match it.

    Scoped in SQL by ``notes_owned_by``, not filtered afterwards: SLICES §V1 asks for another user's
    note to be *omitted* rather than fetched and hidden, and only the ``WHERE`` can say which
    happened. Composing here cannot lose that clause (KAN-535), and ``notes_matching`` composes onto
    the very same statement, so KAN-558's "another user's matching note must never appear" is that
    one clause rather than a second implementation of it.

    **Two orders, because they answer two different questions, and each one is deterministic.**

    - No ``q``: ``updated_at DESC, id DESC``. The second column is not decoration — two notes
      written inside one transaction share an ``updated_at`` (``now()`` is transaction start time,
      per the model's own comment), so without a tie-break the order would be whatever Postgres felt
      like, and V4's "identical queries return results in a deterministic order" would already be
      false here. ``KayaClient.list_notes``' docstring depends on this order.
    - With ``q``: ``ts_rank DESC, id DESC``. Relevance is the only useful order for a search and a
      meaningless one for a list, so this is one order per request rather than one rule bent twice.
      The tie-break is the same column for the same reason; see ``notes_matching``, which owns both
      halves of the search order so they cannot be applied separately.

    The branch below chooses a **statement** and stops — the shape ``app/api/refs.py``'s
    ``resolve_note`` uses, for the same reason: one ``session.scalars``, one ``NoteList``, so there
    is no second code path in which projection, scoping or the envelope could differ. What ``?q=``
    means when it is empty is decided in ``app/api/search.py`` and has already happened by the time
    this function runs.

    No paging parameter: no card has asked for one, and ``next_cursor`` is additive to this envelope
    when one does. It is deliberately not added *with* search either — a `limit` would need a
    documented interaction with ranking, and that is a second undiscussed contract.
    """
    statement = (
        notes_owned_by(principal).order_by(Note.updated_at.desc(), Note.id.desc())
        if term is None
        else notes_matching(principal, term)
    )
    return NoteList(notes=[NoteRead.of(note) for note in session.scalars(statement)])


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

    **Two write semantics, and which one you get is the caller's choice** (ADR 0009). Send
    ``if_updated_at`` and the write is guarded: an ``updated_at`` that has moved on is a `409`
    carrying both versions, and nothing is written. Omit it and the write is a plain
    last-write-wins overwrite — specified, so that `curl` and a `kaya note edit` that omits
    `--if-updated-at` both work without a read-first dance. The precondition is a guarantee
    available to clients that want it, not a tax on every caller, so do not make it required.

    The guard runs **before** anything is applied, which is what makes a refused write atomic: a
    `PATCH` carrying a title and a body is rejected whole rather than leaving the title applied and
    the body not. See ``app/api/concurrency.py`` for why a metadata-only write is unguarded even
    when it carries a stale precondition.

    KAN-562: a write that touches ``body`` reconciles ``note_link`` in the same transaction —
    removed wikilinks disappear, added ones appear, and one left untouched is not re-written. A
    title- or path-only edit does not scan anything: ``find_wikilinks`` reads the body, and a save
    that never changed it cannot have changed what the body links to.
    """
    enforce_precondition(session, note, payload)

    changes = payload.changes()
    for field, value in changes.items():
        setattr(note, field, value)

    # An empty PATCH is a legal no-op and must not restamp `updated_at` — that value is ADR 0009's
    # concurrency token, and a write that moves it without changing anything would invalidate every
    # other client's precondition for no reason. SQLAlchemy would emit no UPDATE anyway; committing
    # only when something changed says so out loud.
    if changes:
        if "body" in changes:
            reconcile_note_links(session, note)
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
