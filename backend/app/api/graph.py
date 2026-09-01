"""``GET /api/v1/graph`` — the ``note_link`` graph, node-and-edge shaped — KAN-1050.

The read-only SPA graph view's one endpoint: every note the caller owns, as a node, and every
resolved note-to-note wikilink among them, as an edge. Cross-repo pandan `KAN`/`EPIC` links are out
of scope by design (the card's own framing) — this is the *note* graph, not a pandan-ticket graph,
so an edge here is always a `[[Some Note Title]]` reference that has resolved to another of the
caller's own notes.

**A third, small route module rather than three more lines in ``notes.py`` or ``links.py``.** It
shares ``notes.py``'s shape — one session, one principal, no bearer and no upstream client — so it
is not ``links.py``'s three-phase split; it is a `/graph`-shaped read, not a note-shaped one, so it
is not a sixth route on ``notes.py`` either. It gets its own module for the same reason `/links` and
`/backlinks` got theirs: a fourth thing under `app/api/` doing exactly what its neighbours do is
tidiness, not a rule, but a route answering a *different* question (a graph, not a note) reads as
itself in its own file.

**Pure query, no pandan.** Unlike ``links.py``, there is no upstream call here at all — a
note-to-note edge resolves at write time (KAN-563) and is read straight back, so there is nothing to
degrade and no need for that module's ``_release_the_connection`` pattern, which exists specifically
to avoid holding a connection across a *slow upstream* call this route never makes.

**No route builds a note or note_link query.** Both queries this route needs are composed, not
written: ``notes_owned_by`` (already the sanctioned factory every list route uses) and
``notes_graph_edges`` (KAN-1050's own factory, in ``app/auth/authorization.py`` beside its sibling
``notes_linking_to`` for the reason ``tests/unit/test_no_unscoped_note_query.py`` requires — every
``note``/``note_link`` query lives in that one module or nowhere).
"""

from collections.abc import Iterable
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.schemas import GraphEdge, GraphNode, GraphRead
from app.auth import Principal, get_principal, notes_graph_edges, notes_owned_by
from app.db import get_session
from app.models import Note

router = APIRouter(prefix="/api/v1", tags=["graph"])

CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
DbSession = Annotated[Session, Depends(get_session)]


def graph_read(notes: Iterable[Note], edges: Iterable[tuple[int, int]]) -> GraphRead:
    """The response, from two already-fetched, already-scoped inputs. **Pure.**

    No session, no principal — the two things that would let this do anything worse than translate
    an id to a ref, and neither is in scope. That is what lets every rule below be asserted in the
    no-infrastructure test layer against plain notes and tuples, the same split ``link_records``
    makes in ``app/api/links.py``.

    ``notes`` becomes ``nodes`` verbatim, in whatever order it arrived — the route supplies that
    order (``notes_owned_by`` composed with an ``order_by``), this function does not choose one.

    ``edges`` is id pairs, translated through a lookup built from ``notes`` and nothing else. An id
    this function cannot find in that lookup is dropped rather than raised on — the two ways that
    happens are both legitimate degradations rather than bugs: a target note deleted after the edge
    was recorded (``resolved_id`` is not a ``ForeignKey``, so nothing nulls it — the same
    dangling-id case ``app/api/links.py``'s ``note_targets`` degrades), and, in principle, a
    resolved id landing outside the caller's own notes (``notes_graph_edges``'s docstring notes
    nothing writes one that does, so this is belt-and-suspenders rather than a path this route
    expects to take). Either way the edge is simply omitted, the way an unresolved link in
    ``/links`` renders instead of raising.
    """
    by_id = {note.id: note for note in notes}
    nodes = [GraphNode(ref=note.ref, title=note.title, path=note.path) for note in by_id.values()]

    resolved_edges: list[GraphEdge] = []
    for source_id, target_id in edges:
        source = by_id.get(source_id)
        target = by_id.get(target_id)
        if source is None or target is None:
            continue
        resolved_edges.append(GraphEdge(source=source.ref, target=target.ref))

    return GraphRead(nodes=nodes, edges=resolved_edges)


@router.get("/graph", summary="The caller's notes and the wikilinks between them")
def read_graph(principal: CurrentPrincipal, session: DbSession) -> GraphRead:
    """Every note the caller owns, and every resolved note-to-note wikilink among them.

    Two queries, both owner-scoped, both composed rather than written here: the nodes are
    ``notes_owned_by`` ordered the same way ``list_notes``'s unfiltered list already is — newest
    first, with the same ``id`` tie-break, so a re-fetch of an unchanged graph does not reorder its
    nodes for no reason — and the edges are ``notes_graph_edges``. ``graph_read`` does the rest.

    A caller with no notes gets ``{"nodes": [], "edges": []}`` — an empty graph is not an error.
    """
    statement = notes_owned_by(principal).order_by(Note.updated_at.desc(), Note.id.desc())
    notes = session.scalars(statement)
    edges = session.execute(notes_graph_edges(principal)).all()
    return graph_read(notes, edges)
