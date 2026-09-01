"""KAN-1050's ``/graph``, at the layer where its rules are decidable without a database.

Two groups, and the split mirrors ``test_link_queries.py``'s:

- **``notes_graph_edges``**, asserted as a *statement*. The owner clause, the ``target_kind``
  filter and the "resolved edges only" filter are all things the compiled SQL either has or does
  not — the same reason ``notes_linking_to`` is asserted this way rather than against rows.
- **``graph_read``**, which is pure. Translating an id pair into a ref pair, and deciding what an
  isolated node or a dangling id renders as, are properties of a function over plain notes and
  tuples, so they belong here rather than behind a container.

The behavioural claims that need rows — two different owners' notes never mixing in one graph, a
note with no links still appearing as a node — are `tests/integration/test_graph_api.py`'s, the
same split `test_link_queries.py`'s own docstring draws for `/links` and `/backlinks`.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.dialects import postgresql

from app.api.graph import graph_read
from app.auth import notes_graph_edges, notes_owned_by
from app.auth.principal import Principal
from app.models import Note

ALICE = Principal(id=uuid.UUID("11111111-1111-4111-8111-111111111111"), email="a@example.com")


def compiled(statement: object) -> str:
    """The statement as Postgres would see it, for asserting a clause is present."""
    return str(
        statement.compile(  # type: ignore[attr-defined]
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def predicates(statement: object) -> str:
    """Just the ``WHERE`` clause — see ``test_link_queries.py``'s twin for why a bare substring
    probe over the whole statement cannot tell a filter from a projection."""
    sql = " ".join(compiled(statement).split())
    where = sql.partition("WHERE ")[2]
    assert where, "the statement has no WHERE clause; this probe would prove nothing"
    return where.partition("ORDER BY ")[0]


# --- notes_graph_edges: the statement -------------------------------------------------------------


def test_the_graph_edges_query_is_owner_scoped_in_sql() -> None:
    """Inherited from ``notes_owned_by``, not written again — the same clause appears in both, so
    the two cannot disagree (``test_link_queries.py``'s identical argument for
    ``notes_linking_to``)."""
    scoped = predicates(notes_owned_by(ALICE))
    graph = predicates(notes_graph_edges(ALICE))

    assert f"note.owner_id = '{ALICE.id}'" in scoped
    assert f"note.owner_id = '{ALICE.id}'" in graph


def test_the_graph_edges_query_filters_on_the_note_kind() -> None:
    """This is the *note* graph, not a pandan-ticket graph (the card's own scoping) — a `KAN`/`EPIC`
    edge must never surface as an edge between two notes."""
    assert "note_link.target_kind = 'NOTE'" in predicates(notes_graph_edges(ALICE))


def test_the_graph_edges_query_excludes_unresolved_links() -> None:
    """CLAUDE.md, verbatim: "an edge with resolved_id IS NULL is a link to a title, not yet a
    note." A graph has nowhere to draw a line for a target that does not exist yet."""
    where = predicates(notes_graph_edges(ALICE))

    assert "note_link.resolved_id IS NOT NULL" in where


def test_the_graph_edges_query_does_not_filter_to_one_note() -> None:
    """The whole difference from ``notes_linking_to``: this query has no ``note_link.resolved_id =
    <n>`` clause anywhere, because a graph needs every edge among the caller's notes at once."""
    where = predicates(notes_graph_edges(ALICE))

    assert "note_link.resolved_id =" not in where, (
        "a graph edges query scoped to one note's backlinks would silently become "
        "`notes_linking_to` again"
    )


def test_the_graph_edges_query_selects_only_the_two_ids() -> None:
    """``with_only_columns`` narrows the projection — the route only ever needs an id pair to
    translate through a lookup it already has, never a full ``Note`` row twice over."""
    sql = compiled(notes_graph_edges(ALICE))

    assert sql.startswith("SELECT note_link.source_note_id, note_link.resolved_id")


@pytest.mark.parametrize(
    "clause",
    [
        "note_link.target_kind = 'NOTE'",
        "note_link.resolved_id IS NOT NULL",
        "note_link",
    ],
)
def test_the_clause_probes_are_not_vacuous(clause: str) -> None:
    """Every assertion above is a substring probe, and a substring probe proves nothing until shown
    failing against something it must not match — ``notes_owned_by`` is the positive control, the
    same table and compiler with none of this card's added clauses."""
    assert clause in predicates(notes_graph_edges(ALICE))
    assert clause not in predicates(notes_owned_by(ALICE))


# --- graph_read: the pure translation --------------------------------------------------------


def a_note(*, id: int, ref: str, title: str = "a note", path: str = "") -> Note:
    return Note(
        id=id,
        ref=ref,
        owner_id=ALICE.id,
        title=title,
        body="",
        path=path,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_every_note_becomes_a_node_whether_or_not_it_has_an_edge() -> None:
    """A note with no links still appears as a node with no edges — the two arrays are built
    independently, so an isolated note needs no special case."""
    notes = [a_note(id=1, ref="NOTE-1"), a_note(id=2, ref="NOTE-2")]

    graph = graph_read(notes, edges=[])

    assert {node.ref for node in graph.nodes} == {"NOTE-1", "NOTE-2"}
    assert graph.edges == []


def test_an_edge_is_translated_from_ids_to_refs() -> None:
    """ADR 0008: nothing internal reaches the wire. The pair the route reads from the database is
    two integers; the pair the caller sees is two refs."""
    notes = [a_note(id=1, ref="NOTE-1"), a_note(id=2, ref="NOTE-2")]

    graph = graph_read(notes, edges=[(1, 2)])

    [edge] = graph.edges
    assert (edge.source, edge.target) == ("NOTE-1", "NOTE-2")


def test_an_edge_naming_an_id_outside_the_node_set_is_dropped_not_raised() -> None:
    """Belt-and-suspenders for a resolved id landing outside the caller's own notes, and the exact
    shape a deleted target note would leave behind (``resolved_id`` is not a ``ForeignKey``, so
    nothing nulls it on delete) — degrades the same way an unresolved ``/links`` row does, never a
    `500`."""
    notes = [a_note(id=1, ref="NOTE-1")]

    graph = graph_read(notes, edges=[(1, 999)])

    assert graph.edges == []
    assert [node.ref for node in graph.nodes] == ["NOTE-1"]


def test_nodes_preserve_the_order_they_were_given() -> None:
    """``graph_read`` does not sort — the route supplies the order (``notes_owned_by`` composed
    with an ``order_by``), this function only translates."""
    notes = [a_note(id=2, ref="NOTE-2"), a_note(id=1, ref="NOTE-1")]

    graph = graph_read(notes, edges=[])

    assert [node.ref for node in graph.nodes] == ["NOTE-2", "NOTE-1"]


def test_an_empty_input_is_an_empty_graph_not_an_error() -> None:
    graph = graph_read([], edges=[])

    assert (graph.nodes, graph.edges) == ([], [])


def test_a_node_carries_ref_title_and_path_and_nothing_internal() -> None:
    notes = [a_note(id=1, ref="NOTE-1", title="Reading List", path="proj/reading.md")]

    [node] = graph_read(notes, edges=[]).nodes

    assert (node.ref, node.title, node.path) == ("NOTE-1", "Reading List", "proj/reading.md")
    assert "id" not in node.model_dump()
