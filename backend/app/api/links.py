"""``/api/v1/notes/{ref}/links`` and ``/backlinks`` — KAN-566, SLICES §V5 build-plan step 6.

Two routes that answer two questions about the same table from opposite ends, and the interesting
thing about them is which half of each one is allowed to touch the network.

**Backlinks never do.** "Which notes link to this one" is a join over ``note_link`` and ``note``,
both of them kaya's own, so it is answerable with pandan stopped, on a cold cache, forever. That is
the card's headline sentence and it is a property of the SQL rather than a behaviour anything here
arranges — ``app.auth.notes_linking_to`` is the whole implementation and it makes no call.

**Outbound links do, for the pandan-shaped rows only, and this is ADR 0003's line.** A
``[[KAN-501]]`` edge is stored the moment the body is saved (KAN-562) and carries no title,
because deciding whether pandan has a card by that number is a network call and the reconciler
is forbidden from making one.
So the title and the column KAN-567's pill needs are resolved *here*, on the read, through KAN-564's
``CardEpicResolver`` — this module is that class's first caller, and the module docstring it was
written with names it as such.

Three things keep that from becoming the dependency ADR 0003 forbids:

1. **``resolve()`` never raises for a network reason.** A timeout, a dead host, the total deadline
   or the request cap all leave a ref mapped to ``None``, which is byte-identical to the answer for
   a ticket pandan genuinely does not have. So there is no ``try``/``except`` in this file and there
   must not be one: a handler here would be a second opinion about a decision KAN-564 already made,
   and the first thing it would do is disagree. ``/links`` is a `200` with unresolved rows, never a
   `503`.
2. **The local rows are read first and are never at stake.** Every edge appears in the response
   whatever pandan did. Resolution only ever fills three nullable fields, so an outage subtracts
   decoration from a complete answer rather than turning the answer into an error (Q26).
3. **No Postgres connection is held across the upstream call.** See ``_release_the_connection``.

**Nothing resolved here is written back.** ``note_link.resolved_id`` stays ``NULL`` for every
KAN-/EPIC-kind row, exactly as KAN-562 left it, and that is a decision rather than an omission.
KAN-564's cache is keyed on ``(sha256(bearer), ticket_number)`` *because* an answer about a pandan
ticket is only true for the caller who asked — one caller's resolution of ``KAN-99`` must not be
reachable through another caller's bearer. A column on a shared table is exactly that leak with a
longer TTL, and it would also make a card's title a thing kaya stores and has to invalidate. So the
resolution lives in the per-caller cache and nowhere else. A **NOTE**-kind ``resolved_id`` is the
opposite case and is persisted, by KAN-563, because the target is kaya's own row and the id is what
survives a rename.

### Why this is a second module rather than three more lines in ``notes.py``

``app/api/notes.py``'s docstring makes four promises about itself, and one of them is "no route
builds a note query". These routes keep that promise the same way — the query is
``app.auth.notes_linking_to`` — but they break a different property that file has by accident and
relies on: every route in it is wiring over one session and nothing else. These two take a bearer
and an upstream client, which is a different blast radius, and the phase split below is the only
non-trivial control flow anywhere under ``app/api/``. It reads as what it is in its own file and
would read as an exception in that one.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.refs import NoteFromRef
from app.api.schemas import LinkList, LinkRead, NoteList, NoteRead
from app.auth import Principal, get_principal, notes_linking_to, notes_named_by_id
from app.db import get_session
from app.integrations.card_resolution import ResolvedTicket, classify_ref
from app.integrations.dependencies import CallerBearer, CardResolver
from app.models.note_link import TARGET_KIND_NOTE, NoteLink

router = APIRouter(prefix="/api/v1", tags=["links"])

CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
DbSession = Annotated[Session, Depends(get_session)]


@dataclass(frozen=True, slots=True)
class Edge:
    """One stored ``note_link`` row, as plain data with no session behind it.

    A deliberate copy of three columns rather than the ORM object itself, and the copy is what makes
    the phase split below checkable instead of merely intended. An ORM instance is a live handle: it
    can lazy-load, it belongs to a ``Session``, and a function holding one is a function that might
    touch the database no matter what its signature says. ``link_records`` takes these, so "the
    resolution phase cannot reach Postgres" is a fact about what is *in scope* rather than a rule
    somebody follows — the same argument ``aggregates.attach_summary`` makes for taking exactly one
    parameter.
    """

    target_kind: str
    target_ref: str
    resolved_id: int | None


@dataclass(frozen=True, slots=True)
class NoteTarget:
    """A resolved NOTE-kind edge's target, as the two things a caller can act on."""

    ref: str
    title: str


def outbound_edges(session: Session, note_id: int) -> tuple[Edge, ...]:
    """Every wikilink edge stored for ``note_id``, in a **deterministic** order.

    ``select(NoteLink)`` is built here rather than in ``app/auth/authorization.py`` because it names
    no ``Note``, which is the boundary ``tests/unit/test_no_unscoped_note_query.py`` actually draws
    — see that file, and note that ``app/note_links.py``'s reconciler already reads this table the
    same way. The scoping is ``note_id``, which arrived from ``NoteFromRef`` and has therefore
    already been through ``authorize_note``; there is no owner column on this table to filter on
    (``app/models/note_link.py``), so the authorization happens one layer up, on the note, and this
    query inherits it. Reached any other way it would inherit nothing.

    **The order is ``(target_kind, target_ref)`` and it is load-bearing rather than tidy.** The
    obvious key, insertion order by ``note_link.id``, is not reproducible at all: the reconciler
    builds its insert list from a ``set`` of ``(kind, ref)`` pairs
    (``app/note_links.py``'s ``_desired_targets``), and Python randomises string hashing per
    process, so the same body saved twice on two workers stores its edges in two different orders.
    Two clients rendering one note's pills in different orders is exactly the class of thing SLICES
    §V4's "identical queries return results in a deterministic order" forbids, one endpoint over.
    The pair is unique per source note by the table's own constraint, so it is a total order and
    needs no third column — the one place in this repository where a tie-break is genuinely
    unnecessary, said out loud because everywhere else it is not.
    """
    rows = session.scalars(
        select(NoteLink)
        .where(NoteLink.source_note_id == note_id)
        .order_by(NoteLink.target_kind.asc(), NoteLink.target_ref.asc())
    ).all()
    return tuple(
        Edge(
            target_kind=row.target_kind,
            target_ref=row.target_ref,
            resolved_id=row.resolved_id,
        )
        for row in rows
    )


def note_targets(session: Session, owner_id: UUID, edges: Iterable[Edge]) -> dict[int, NoteTarget]:
    """``id -> (ref, title)`` for the notes this note's resolved NOTE-kind edges point at.

    One batched query rather than one per edge, the same trade ``app/note_links.py``'s
    ``_notes_by_title`` makes and for the same reason: a note rarely links to more than a handful of
    others, and there is still no reason to pay a round trip each when they all scope to one owner.
    Returns ``{}`` for a note with no resolved NOTE edges, without asking Postgres anything.

    An id the statement does not answer for is simply absent, and ``link_records`` renders that edge
    unresolved. That covers the case the schema permits and nothing prevents: a target note that has
    since been **deleted**. ``resolved_id`` is not a ``ForeignKey``, so nothing cascaded and nothing
    nulled it — see ``notes_named_by_id``, which owns that argument and the owner-scoping one.
    """
    wanted = {
        edge.resolved_id
        for edge in edges
        if edge.target_kind == TARGET_KIND_NOTE and edge.resolved_id is not None
    }
    if not wanted:
        return {}
    rows = session.execute(notes_named_by_id(owner_id, wanted)).all()
    return {note_id: NoteTarget(ref=ref, title=title) for note_id, ref, title in rows}


def ticket_refs(edges: Iterable[Edge]) -> tuple[str, ...]:
    """The pandan-shaped refs among ``edges``, in order, for one ``CardEpicResolver.resolve`` call.

    Classified with ``card_resolution.classify_ref`` rather than by comparing ``target_kind``
    against ``"KAN"``/``"EPIC"``, so the question asked here is the same question the resolver will
    ask itself about the same string. ``target_kind`` is a plain, unconstrained column
    (``app/models/note_link.py``) precisely so a future kind is a value and not a migration; a row
    carrying a kind this build has never heard of is therefore possible, and it must not be handed
    to pandan on the strength of not being ``"NOTE"``. ``resolve`` would map it to ``None`` anyway —
    the two agreeing is the point, not the safety net.

    Duplicates are left in: ``resolve`` de-duplicates order-preservingly and one distinct ref cannot
    appear twice for one source note anyway (the table's unique constraint). Filtering here as well
    would be a second implementation of a guarantee two other layers already give.
    """
    return tuple(edge.target_ref for edge in edges if classify_ref(edge.target_ref) is not None)


def link_records(
    edges: Sequence[Edge],
    targets: dict[int, NoteTarget],
    tickets: dict[str, ResolvedTicket | None],
) -> list[LinkRead]:
    """The response rows: every edge, resolved as far as its two lookups managed. **Pure.**

    No session, no resolver, no bearer — the three things it would need to make anything worse than
    a wrong answer, and none of them are in scope. That is what lets every rule below be asserted in
    the no-infrastructure test layer against dicts built by hand, and it is why the route reads as
    three phases rather than as one function that does everything in the order it thought of.

    An edge missing from both lookups renders with three nulls, and the two lookups are read
    **without a fallback between them**: a NOTE edge never consults ``tickets`` and a pandan edge
    never consults ``targets``. That sounds obvious and is the one line where the id collision
    ``app/models/note_link.py``'s ``TARGET_KIND_NOTE`` docstring describes would arrive, since
    ``resolved_id`` means different things in different namespaces.
    """
    records: list[LinkRead] = []
    for edge in edges:
        if edge.target_kind == TARGET_KIND_NOTE:
            target = targets.get(edge.resolved_id) if edge.resolved_id is not None else None
            records.append(
                LinkRead(
                    target_kind=edge.target_kind,
                    target_ref=edge.target_ref,
                    resolved_ref=target.ref if target else None,
                    title=target.title if target else None,
                    column=None,
                )
            )
            continue

        ticket = tickets.get(edge.target_ref)
        records.append(
            LinkRead(
                target_kind=edge.target_kind,
                target_ref=edge.target_ref,
                resolved_ref=ticket.ticket_number if ticket else None,
                title=ticket.title if ticket else None,
                column=ticket.column if ticket else None,
            )
        )
    return records


def _release_the_connection(session: Session) -> None:
    """End the read transaction so the pooled connection is **not** held across the upstream call.

    This is the third of the three things keeping ``/links`` inside ADR 0003, and it is the one with
    no visible symptom until it matters. ``app/auth/single_flight.py`` records the shape of the
    failure: sync handlers run in Starlette's 40-thread pool, so without care 40 concurrent requests
    on one slow upstream hold 40 workers — and, here, 40 *connections* — for the whole of that
    upstream's budget. Kaya's engine has SQLAlchemy's default pool (5, plus 10 overflow), so about
    fifteen concurrent ``/links`` calls against a pandan that is merely slow would exhaust it, and
    the next note **save** would block waiting for a connection. That is ADR 0003's rule — "a note
    must save with pandan completely down" — broken from inside kaya, by a decoration, exactly as
    KAN-666 describes it one layer over.

    ``commit`` rather than ``close`` or ``rollback``, and the choice is not arbitrary. All three
    return the connection to the pool; only ``commit`` leaves the ORM objects usable, because
    ``app/db.py``'s sessionmaker sets ``expire_on_commit=False`` — ``rollback`` and ``close`` both
    expire, so either would turn a later attribute read into a lazy load, i.e. into the connection
    checkout this function exists to avoid, or into a ``DetachedInstanceError``. Nothing after this
    call reads an ORM attribute today (the phase split above is what guarantees that), so the choice
    only matters for the edit somebody makes later — which is when it matters most.

    Committing a read-only transaction writes nothing. It is a ``COMMIT`` on a transaction with no
    statements to undo, which is how "I am finished with the database" is spelled.
    """
    session.commit()


@router.get(
    "/notes/{ref}/links",
    summary="The wikilinks in a note's body, resolved where they can be",
)
def note_links(
    note: NoteFromRef,
    session: DbSession,
    bearer: CallerBearer,
    resolver: CardResolver,
) -> LinkList:
    """Every ``[[...]]`` this note's body currently contains, with what each one points at.

    Three phases, in this order, and the order is the contract: read the local rows, let go of the
    database, then ask pandan about the pandan-shaped ones. See ``_release_the_connection`` for why
    the middle phase exists, and this module's docstring for why the third one cannot fail the
    request.

    A note with no wikilinks is ``{"links": []}``. A note whose every link is unresolved is the same
    `200` with three nulls per row, because Q26 makes that a rendering and not an error, and because
    a caller cannot act differently on "pandan said no" and "pandan could not be asked" — see
    ``LinkRead.resolved_ref``, which enumerates the four ways ``null`` arrives.

    ``bearer`` being ``None`` skips resolution rather than refusing the read: unreachable in
    practice, since ``NoteFromRef`` has already resolved a principal from that same header, and the
    degradation is the honest answer anyway (``app/integrations/dependencies.py``).
    """
    edges = outbound_edges(session, note.id)
    targets = note_targets(session, note.owner_id, edges)
    refs = ticket_refs(edges)

    _release_the_connection(session)

    tickets = resolver.resolve(bearer, refs) if bearer is not None and refs else {}
    return LinkList(links=link_records(edges, targets, tickets))


@router.get(
    "/notes/{ref}/backlinks",
    summary="The notes whose body links to this one",
)
def note_backlinks(note: NoteFromRef, principal: CurrentPrincipal, session: DbSession) -> NoteList:
    """Every note of the caller's whose body contains a wikilink resolving to **this** note.

    **The whole route is one local query, and that is the card's headline claim rather than an
    implementation detail.** There is no bearer here, no resolver, no upstream and nothing to
    degrade: "which notes mention this one" is a join between two of kaya's own tables, so it is
    answerable with pandan stopped and a cold cache, and it will still be answerable if pandan is
    deleted. ``app.auth.notes_linking_to`` owns every decision — the owner scoping, the
    ``resolved_id`` match key that makes the answer survive a rename, and the ``target_kind`` filter
    that keeps two id namespaces apart.

    **It returns ``NoteList``, the same envelope a plain list returns, and that is deliberate.** A
    backlink *is* a note; wrapping it in a link-shaped record would publish a second spelling of
    something the caller can already read, and it would cost ``kaya-client`` a second noun, a second
    column set and a second hint row for no information gained. Because the envelope is the same,
    ``kaya backlinks NOTE-3 --fields ref,title`` and ``--full`` and every format work with nothing
    added anywhere (ADR 0004), and KAN-568's panel reads the type it already has.

    What that gives up, stated rather than left to be discovered: the response does not say *which*
    link in the other note pointed here, or what it was typed as. Nothing has asked — the panel
    lists notes — and it is additive to this envelope the day something does.

    **A note that links to its own title appears in its own backlinks.** That is not a special case
    being allowed through; it is the absence of one. The note genuinely contains a link that
    resolves to it (``app/note_links.py`` resolves a self-link on the note's first save, on
    purpose), and excluding it would be a rule the parser, the reconciler and the body itself all
    disagree with.

    A `404` for a note that does not exist and a `403` for somebody else's come from ``NoteFromRef``
    — the same two answers, byte for byte, as every other ref-taking route, with no ref handling in
    this function to get wrong (ADR 0008).
    """
    statement = notes_linking_to(principal, note.id)
    return NoteList(notes=[NoteRead.of(found) for found in session.scalars(statement)])
