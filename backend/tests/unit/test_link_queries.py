"""KAN-566's two routes, at the layer where their rules are decidable without a database.

Three groups, and the split mirrors the module under test:

- **``link_records``**, which is pure. Every rule about what a link payload says — which lookup a
  kind reads, what an unresolved row looks like, that the two lookups never fall back to each other
  — is a property of a function over three dicts, so it belongs here rather than behind a container.
- **``notes_linking_to``**, asserted as a *statement*. The owner clause, the ``resolved_id`` match
  key and the ``target_kind`` filter are all things the compiled SQL either has or does not; the
  integration twin then proves they mean what they say against real rows.
- **``ticket_refs``**, which is where "what gets sent to pandan" is decided.

`tests/integration/test_note_links_api.py` owns everything that needs rows: the rename criterion,
the pandan-down path, the deleted-target degradation and the connection-release guarantee.

**Named `test_link_queries` rather than `test_note_links_api`** to keep its basename distinct from
that file's. There is no `__init__.py` in either test package, so pytest imports a test module under
its bare basename and two files sharing one is an `import file mismatch` the moment a single
invocation collects both. `make test` runs `tests/unit` and `make test-integration` runs
`tests/integration`, so the collision was invisible from the gate and appeared the first time
something asked for both at once — which is a thing a person debugging does, not a thing CI does.
"""

import uuid

import pytest
from sqlalchemy.dialects import postgresql

from app.api.links import Edge, NoteTarget, link_records, ticket_refs
from app.auth import notes_linking_to, notes_owned_by
from app.auth.principal import Principal
from app.integrations.card_resolution import ResolvedTicket

ALICE = Principal(id=uuid.UUID("11111111-1111-4111-8111-111111111111"), email="a@example.com")

KAN_501 = ResolvedTicket(
    kind="card", id=1, ticket_number="KAN-501", title="MCP read tools", column="in_progress"
)
EPIC_3 = ResolvedTicket(kind="epic", id=3, ticket_number="EPIC-3", title="An epic", column=None)


def compiled(statement: object) -> str:
    """The statement as Postgres would see it, for asserting a clause is present."""
    return str(
        statement.compile(  # type: ignore[attr-defined]
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def predicates(statement: object) -> str:
    """Just the ``WHERE`` clause, so a column named in the *select list* cannot satisfy — or
    falsify — an assertion about what the query filters on. ``select(Note)`` names every column of
    ``note``, ``note.title`` included, so a bare substring probe over the whole statement cannot
    tell a filter from a projection."""
    sql = " ".join(compiled(statement).split())
    where = sql.partition("WHERE ")[2]
    assert where, "the statement has no WHERE clause; this probe would prove nothing"
    return where.partition("ORDER BY ")[0]


# --- link_records: the pure rules ---------------------------------------------------------------


def test_a_resolved_note_edge_carries_the_targets_ref_and_current_title() -> None:
    """SLICES §V5's rename criterion, visible in one record: ``target_ref`` is what was typed and
    ``title`` is what the note is called now. The payload states the divergence instead of hiding
    it behind one of the two."""
    edges = (Edge(target_kind="NOTE", target_ref="Old Name", resolved_id=7),)
    targets = {7: NoteTarget(ref="NOTE-7", title="New Name")}

    [record] = link_records(edges, targets, {})

    assert record.target_ref == "Old Name"
    assert record.resolved_ref == "NOTE-7"
    assert record.title == "New Name"
    assert record.column is None


def test_an_unresolved_note_edge_is_three_nulls_and_not_an_error() -> None:
    """Q26: an unresolved link renders as one. ``resolved_id`` is ``NULL`` because no note by that
    title exists yet — ``resolve_pending_note_links`` is what changes that, later, on its own."""
    edges = (Edge(target_kind="NOTE", target_ref="Not Written Yet", resolved_id=None),)

    [record] = link_records(edges, {}, {})

    assert (record.resolved_ref, record.title, record.column) == (None, None, None)
    assert record.target_ref == "Not Written Yet"


def test_a_note_edge_whose_target_was_deleted_degrades_to_unresolved() -> None:
    """``resolved_id`` is deliberately not a ``ForeignKey``, so deleting the *target* note cascades
    nothing and nulls nothing — the id is left dangling. A `500` on a missing row would make a
    perfectly ordinary delete break every note that linked to it."""
    edges = (Edge(target_kind="NOTE", target_ref="Gone", resolved_id=999),)

    [record] = link_records(edges, {}, {})

    assert record.resolved_ref is None
    assert record.title is None


def test_a_resolved_card_carries_its_title_and_column() -> None:
    """What KAN-567's pill renders: ``KAN-501 · in_progress · "MCP read tools"``."""
    edges = (Edge(target_kind="KAN", target_ref="KAN-501", resolved_id=None),)

    [record] = link_records(edges, {}, {"KAN-501": KAN_501})

    assert record.resolved_ref == "KAN-501"
    assert record.title == "MCP read tools"
    assert record.column == "in_progress"


def test_a_resolved_epic_has_no_column_rather_than_an_invented_one() -> None:
    """``ResolvedTicket.column`` is always ``None`` for an epic, and this layer must not paper over
    the difference to make the shape uniform."""
    edges = (Edge(target_kind="EPIC", target_ref="EPIC-3", resolved_id=None),)

    [record] = link_records(edges, {}, {"EPIC-3": EPIC_3})

    assert (record.resolved_ref, record.title, record.column) == ("EPIC-3", "An epic", None)


def test_a_card_pandan_could_not_answer_for_is_unresolved_and_still_present() -> None:
    """The ADR 0003 shape at the record level: the edge is in the response either way, and an
    outage subtracts decoration rather than turning a `200` into an error. ``resolve`` maps a
    timeout, a dead host, a deadline and a genuinely-absent ticket all to ``None``, so this one case
    covers all four."""
    edges = (Edge(target_kind="KAN", target_ref="KAN-501", resolved_id=None),)

    [record] = link_records(edges, {}, {"KAN-501": None})

    assert record.target_ref == "KAN-501"
    assert (record.resolved_ref, record.title, record.column) == (None, None, None)


def test_a_ref_missing_from_the_resolver_result_entirely_is_unresolved_too() -> None:
    """Not the same input as the test above: ``resolve`` returns one entry per ref it was *given*,
    so an absent key means this module asked about something it did not send — a `.get` rather than
    a `[]` is what keeps that a null instead of a `KeyError` in a note render."""
    edges = (Edge(target_kind="KAN", target_ref="KAN-999", resolved_id=None),)

    [record] = link_records(edges, {}, {})

    assert record.resolved_ref is None


def test_the_two_lookups_never_fall_back_to_each_other() -> None:
    """The line where the id-namespace collision would arrive.

    A KAN edge carrying a ``resolved_id`` that *happens* to be a note id must not read the note
    lookup, and a NOTE edge whose title happens to look like a ticket ref must not read the ticket
    lookup. Nothing writes a KAN-kind ``resolved_id`` today, which is exactly why this is asserted
    rather than assumed — see ``app/models/note_link.py``'s ``TARGET_KIND_NOTE``.
    """
    edges = (
        Edge(target_kind="KAN", target_ref="KAN-501", resolved_id=7),
        Edge(target_kind="NOTE", target_ref="KAN-501", resolved_id=None),
    )
    targets = {7: NoteTarget(ref="NOTE-7", title="A note")}

    card, note = link_records(edges, targets, {"KAN-501": KAN_501})

    assert card.title == "MCP read tools", "a card must resolve through the ticket lookup"
    assert card.resolved_ref == "KAN-501", "and never through the note lookup its id points into"
    assert note.resolved_ref is None, "a NOTE edge must not read a ticket the resolver answered"
    assert note.title is None


def test_every_edge_reaches_the_response_in_the_order_it_was_given() -> None:
    """``link_records`` neither sorts nor drops. The order is ``outbound_edges``' — see its
    docstring for why insertion order could not be used."""
    edges = (
        Edge(target_kind="EPIC", target_ref="EPIC-3", resolved_id=None),
        Edge(target_kind="KAN", target_ref="KAN-501", resolved_id=None),
        Edge(target_kind="NOTE", target_ref="Zebra", resolved_id=None),
    )

    records = link_records(edges, {}, {})

    assert [r.target_ref for r in records] == ["EPIC-3", "KAN-501", "Zebra"]


def test_a_note_with_no_links_is_an_empty_list_not_a_null() -> None:
    assert link_records((), {}, {}) == []


# --- ticket_refs: what leaves the process -------------------------------------------------------


def test_only_pandan_shaped_refs_are_offered_to_the_resolver() -> None:
    edges = (
        Edge(target_kind="KAN", target_ref="KAN-501", resolved_id=None),
        Edge(target_kind="EPIC", target_ref="EPIC-3", resolved_id=None),
        Edge(target_kind="NOTE", target_ref="A Note Title", resolved_id=None),
    )

    assert ticket_refs(edges) == ("KAN-501", "EPIC-3")


def test_a_note_title_that_looks_like_a_pan_ref_is_not_sent_to_pandan() -> None:
    """ADR 0003 and KAN-561: ``PAN-`` is not a pandan prefix and never was (pandan ADR 0018). A
    title of ``PAN-1`` is a title."""
    edges = (Edge(target_kind="NOTE", target_ref="PAN-1", resolved_id=None),)

    assert ticket_refs(edges) == ()


def test_an_unknown_target_kind_is_classified_by_the_ref_not_by_not_being_note() -> None:
    """``target_kind`` is an unconstrained string so a future kind is a value rather than a
    migration, which means a row can carry a kind this build has never heard of. The filter asks
    ``classify_ref`` — the same question the resolver asks — instead of ``!= "NOTE"``.
    """
    edges = (
        Edge(target_kind="TAG", target_ref="urgent", resolved_id=None),
        Edge(target_kind="TAG", target_ref="KAN-7", resolved_id=None),
    )

    assert ticket_refs(edges) == ("KAN-7",), (
        "a kind this build does not know is classified by its ref, so a bare word is never "
        "offered to pandan and a ticket-shaped one still is"
    )


# --- notes_linking_to: the statement ------------------------------------------------------------


def test_the_backlinks_query_is_owner_scoped_in_sql() -> None:
    """The clause that makes "another user's note never appears in my backlinks" a property of the
    SQL. It is inherited from ``notes_owned_by`` rather than written again, so the two cannot
    disagree — asserted by finding the same rendered clause in both statements."""
    scoped = predicates(notes_owned_by(ALICE))
    backlinks = predicates(notes_linking_to(ALICE, 7))

    assert f"note.owner_id = '{ALICE.id}'" in scoped
    assert f"note.owner_id = '{ALICE.id}'" in backlinks, (
        "the clause is inherited from `notes_owned_by`, not written again, so the two cannot "
        "disagree — this asserts the *same rendered clause* appears in both"
    )


def test_the_backlinks_query_matches_on_resolved_id_and_never_on_the_title() -> None:
    """SLICES §V5's rename criterion, as a property of the statement: the match is on the id
    KAN-563 recorded, so ``note_link.target_ref`` must not appear in a ``WHERE`` comparison at
    all. The integration twin proves the behaviour; this proves there is nowhere for a title
    comparison to hide."""
    where = predicates(notes_linking_to(ALICE, 7))

    assert "note_link.resolved_id = 7" in where
    assert "note_link.target_ref" not in where, (
        "a backlink keyed on the title breaks the moment the target is renamed (Q19)"
    )
    assert "note.title" not in where, "nor on the target's own title, which a rename also moves"


def test_the_backlinks_query_filters_on_the_note_kind() -> None:
    """Unreachable today — nothing writes a KAN-kind ``resolved_id`` — and load-bearing anyway,
    because ``resolved_id``'s namespace depends on ``target_kind``."""
    assert "note_link.target_kind = 'NOTE'" in predicates(notes_linking_to(ALICE, 7))


def test_the_backlinks_query_orders_deterministically() -> None:
    """The same order and the same tie-break as the unfiltered list. ``updated_at`` alone is not a
    total order: ``now()`` is transaction start time, so two notes written in one transaction share
    a stamp."""
    sql = compiled(notes_linking_to(ALICE, 7))

    assert "ORDER BY note.updated_at DESC, note.id DESC" in sql


@pytest.mark.parametrize(
    "clause", ["note_link.resolved_id = 7", "note_link.target_kind = 'NOTE'", "note_link"]
)
def test_the_clause_probes_are_not_vacuous(clause: str) -> None:
    """Every assertion above is a substring probe, and a substring probe proves nothing until it is
    shown *failing* against something it must not match.

    ``notes_owned_by`` is the positive control: the same table, the same compiler, none of the three
    clauses this card added. Each probe that must be present in ``notes_linking_to`` is checked to
    be **absent** here, so a typo that made a probe unmatchable — a stray space, the wrong
    quoting — is caught rather than silently passing everywhere.
    """
    assert clause in predicates(notes_linking_to(ALICE, 7))
    assert clause not in predicates(notes_owned_by(ALICE))


def test_the_where_clause_probe_refuses_a_statement_it_cannot_read() -> None:
    """And the helper itself: a probe that quietly returned ``""`` would make every "not in"
    assertion above pass forever."""
    from sqlalchemy import select

    from app.models import Note

    with pytest.raises(AssertionError):
        predicates(select(Note))
