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

`/links` and `/backlinks` landed in KAN-566 and are **not** in this file: see ``app/api/links.py``,
which argues the split. The short version is that they are the only routes under ``app/api/`` that
take a bearer and an upstream client as well as a session, so the three-phase body that follows from
that reads as what it is in its own module and as an exception here. They did depend on
``NoteFromRef`` and inherit ADR 0008 for free, exactly as this docstring predicted.

``/versions`` landed in KAN-1064 and **is** in this file, unlike ``/links``/``/backlinks`` — it
needs no bearer and no upstream client, just a scoped read over ``note_version``
(``app/note_versions.py``), so it is the plain wiring this module's docstring describes rather than
the exception ``links.py`` is.

Deliberately absent: paging of any shape.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.concurrency import enforce_precondition
from app.api.refs import NoteFromRef
from app.api.schemas import (
    NoteCreate,
    NoteList,
    NoteRead,
    NoteUpdate,
    NoteVersionList,
    NoteVersionRead,
)
from app.api.search import SearchTerm
from app.auth import (
    Principal,
    TeamAccessResolver,
    get_principal,
    get_team_access_resolver,
    notes_matching,
    notes_owned_by,
)
from app.db import get_session
from app.integrations.dependencies import CallerBearer
from app.models import Note
from app.note_links import reconcile_note_links, resolve_pending_note_links
from app.note_versions import cut_version, note_versions

router = APIRouter(prefix="/api/v1", tags=["notes"])

CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
DbSession = Annotated[Session, Depends(get_session)]
CurrentTeamResolver = Annotated[TeamAccessResolver, Depends(get_team_access_resolver)]


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

    KAN-563: the same call also resolves any of *this* note's own ``[[Some Title]]`` links against
    notes that already exist, and ``resolve_pending_note_links`` afterward points any *other* note's
    still-unresolved link at this one, in case this note's title is exactly what one was waiting
    for. Both stay inside this same transaction for the reason above — a resolution landing without
    the note it names, or the reverse, is a state nothing here may produce.

    R13/KAN-1064: ``cut_version`` snapshots the created body as the note's first ``note_version``
    row, in the same transaction, so a note's history starts at creation rather than at its first
    edit. Every note gets one, even ``NoteCreate``'s default empty body — "on every body write, no
    heuristic" (BREADBOARD.md's R13) draws no exception for a body that happens to be ``""``.
    """
    note = Note(owner_id=principal.id, **payload.model_dump())
    session.add(note)
    session.flush()
    reconcile_note_links(session, note)
    resolve_pending_note_links(session, note)
    cut_version(session, note)
    session.commit()
    session.refresh(note)

    # The canonical form, which the ref resolver accepts back verbatim (ADR 0008's round trip).
    response.headers["Location"] = f"{router.prefix}/notes/{note.ref}"
    return NoteRead.of(note)


@router.get("/notes", summary="List the caller's notes, or search them with ?q=")
def list_notes(
    principal: CurrentPrincipal,
    session: DbSession,
    term: SearchTerm,
    bearer: CallerBearer,
    team_resolver: CurrentTeamResolver,
) -> NoteList:
    """Every note the caller owns, newest first — or, with ``?q=``, the ones that match it.

    Scoped in SQL by ``notes_owned_by``, not filtered afterwards: SLICES §V1 asks for another user's
    note to be *omitted* rather than fetched and hidden, and only the ``WHERE`` can say which
    happened. Composing here cannot lose that clause (KAN-535), and ``notes_matching`` composes onto
    the very same statement, so KAN-558's "another user's matching note must never appear" is that
    one clause rather than a second implementation of it.

    **Team membership is resolved before this session has run a single query** (ADR 0011, R16.3) —
    unlike the single-note path in ``app/api/refs.py``, there is no owner check to fail first and
    defer on, since a list has to know every team it should widen for before it can build the
    ``WHERE``. No connection is held across the call for the same reason it never is in
    ``resolve_note``: nothing here has queried yet, so there is nothing to release.

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
    team_ids = team_resolver.member_of(bearer) if bearer is not None else frozenset()
    statement = (
        notes_owned_by(principal, team_ids).order_by(Note.updated_at.desc(), Note.id.desc())
        if term is None
        else notes_matching(principal, term, team_ids)
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


@router.get(
    "/notes/{ref}/versions",
    summary="Every version of a note's body, newest first",
)
def list_note_versions(note: NoteFromRef, session: DbSession) -> NoteVersionList:
    """R13/KAN-1064: every snapshot ``cut_version`` has ever cut for this note.

    A four-line route over ``app/note_versions.py``'s ``note_versions``, the same shape every other
    route in this file is — the query, the scoping and the order are all decided one module away.
    ``note.id`` has already been through ``NoteFromRef`` and therefore ``authorize_note`` by the
    time it reaches ``note_versions``, which is what lets that function build a statement over a
    table with no owner column of its own and still be correctly scoped (see its docstring, and
    ``app/models/note_version.py``'s).

    Full bodies, not snippets: see ``NoteVersionRead``'s docstring for the preview-endpoint design
    call this response shape *is* — there is no separate preview route, on purpose.

    A note with exactly one save (its own creation) still returns one row, never an empty list —
    ``create_note`` cuts a version too, so "no history yet" is not a state this note can be in once
    it exists.
    """
    statement = note_versions(note.id)
    return NoteVersionList(
        versions=[NoteVersionRead.of(version) for version in session.scalars(statement)]
    )


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
    title- or path-only edit does not scan anything: ``find_wikilinks`` / ``find_note_title_links``
    read the body, and a save that never changed it cannot have changed what the body links to.

    KAN-563: a write that touches ``title`` calls ``resolve_pending_note_links`` — a rename can
    make this note satisfy some *other* note's still-unresolved ``[[Some Title]]`` link, and that
    other row would otherwise wait forever for a save of its own that has no reason to happen. This
    runs independently of whether ``body`` also changed in the same request, and it runs after
    ``note.title`` has already been assigned above, so it always resolves against the new value.

    R13/KAN-1064/1066: a write that touches ``body`` also calls ``cut_version`` — a snapshot of the
    body this write just set, in the same transaction as the update it belongs to. A title- or
    path-only edit cuts nothing, matching the wikilink reconcile immediately above it: neither one
    has a reason to run over a body that did not change. **This is also how a restore works** —
    KAN-1066's "restore a version" is nothing more than this same route called with ``body`` set to
    an old version's content, so a restore is guarded by the identical precondition, reconciles
    wikilinks the identical way, and cuts its own new version the identical way. No branch in this
    function knows or needs to know that a particular call was a restore.
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
            cut_version(session, note)
        if "title" in changes:
            resolve_pending_note_links(session, note)
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
