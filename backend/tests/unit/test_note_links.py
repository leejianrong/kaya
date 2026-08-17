"""``note_link`` reconciliation, in the fast layer — KAN-562, SLICES §V5's unit row.

``plan_note_link_changes`` is pure (no session, no query), so every case below is a
`Note`/`NoteLink` built in memory, the same shape ``test_note_concurrency.py`` uses for ADR 0009.
``reconcile_note_links`` is the thin wrapper that turns a plan into `session.add`/`session.delete`
calls; it is exercised here against a `FakeSession` that records what it was asked to do rather than
against a real Postgres — the same split ``app/api/concurrency.py`` makes between ``note_conflict``
and ``enforce_precondition``.

No database: nothing here queries, and nothing here should need to.
"""

from collections.abc import Sequence
from typing import Any

from app.models import Note
from app.models.note_link import NoteLink
from app.note_links import NoteLinkPlan, plan_note_link_changes, reconcile_note_links
from app.wikilinks import find_wikilinks


def link(*, id: int, source_note_id: int = 1, kind: str, ref: str) -> NoteLink:
    """A ``NoteLink`` built in memory, unattached to any session — the reconciler's-eye view of an
    existing row."""
    return NoteLink(id=id, source_note_id=source_note_id, target_kind=kind, target_ref=ref)


def refs_for(body: str) -> list[Any]:
    return find_wikilinks(body)


# --- The pure diff ----------------------------------------------------------------------------


def test_no_existing_rows_and_no_links_in_the_body_changes_nothing() -> None:
    plan = plan_note_link_changes([], refs_for("just prose, no brackets"))

    assert plan == NoteLinkPlan(to_delete=(), to_add=())


def test_a_brand_new_note_has_everything_to_add_and_nothing_to_delete() -> None:
    """The create-note case: no prior rows, so the general diff degenerates to "everything found is
    new" without needing its own branch (``reconcile_note_links``'s docstring)."""
    plan = plan_note_link_changes([], refs_for("blocked by [[KAN-1]], see also [[EPIC-2]]"))

    assert plan.to_delete == ()
    assert set(plan.to_add) == {("KAN", "KAN-1"), ("EPIC", "EPIC-2")}


def test_an_unchanged_link_is_named_in_neither_list() -> None:
    """The property the whole card is about: a link present before and after the save is not in
    ``to_delete`` (it survives) and not in ``to_add`` (it is not re-created) — the reconciler must
    never issue a statement that mentions it at all."""
    existing = [link(id=7, kind="KAN", ref="KAN-1")]

    plan = plan_note_link_changes(existing, refs_for("still mentions [[KAN-1]] here"))

    assert plan.to_delete == ()
    assert plan.to_add == ()


def test_a_removed_link_is_queued_for_deletion_by_the_same_row_object() -> None:
    """Not by a rebuilt copy — the actual `NoteLink` the caller will hand to `session.delete`, which
    is what lets the wrapper delete it without a second lookup."""
    stale = link(id=7, kind="KAN", ref="KAN-1")

    plan = plan_note_link_changes([stale], refs_for("no longer mentions anything"))

    assert plan.to_delete == (stale,)
    assert plan.to_delete[0] is stale
    assert plan.to_add == ()


def test_an_added_link_is_queued_as_a_bare_kind_and_ref_pair() -> None:
    """Nothing to look up for an insert — a new row is built from exactly these two values plus the
    note's own id, which the diff does not have and does not need."""
    plan = plan_note_link_changes([], refs_for("newly mentions [[EPIC-9]]"))

    assert plan.to_add == (("EPIC", "EPIC-9"),)
    assert plan.to_delete == ()


def test_a_typical_edit_adds_removes_and_leaves_one_alone() -> None:
    """One of each, in a single diff — the shape an actual edit produces."""
    existing = [
        link(id=1, kind="KAN", ref="KAN-1"),  # stays
        link(id=2, kind="EPIC", ref="EPIC-9"),  # removed
    ]
    body = "still [[KAN-1]], now also [[KAN-2]]"  # KAN-1 stays, EPIC-9 gone, KAN-2 new

    plan = plan_note_link_changes(existing, refs_for(body))

    assert plan.to_delete == (existing[1],)
    assert plan.to_add == (("KAN", "KAN-2"),)


def test_repeated_occurrences_of_the_same_target_collapse_to_one_edge() -> None:
    """A body that writes ``[[KAN-1]]`` twice has one relationship to KAN-1, not two — the same
    reason a citation list does not grow a second entry for a second footnote to the same source."""
    body = "see [[KAN-1]] for context, and again [[KAN-1]] right here"
    assert len(refs_for(body)) == 2, "the parser itself reports every occurrence"

    plan = plan_note_link_changes([], refs_for(body))

    assert plan.to_add == (("KAN", "KAN-1"),)


def test_case_and_whitespace_variants_of_the_same_reference_are_one_edge() -> None:
    """`WikilinkRef.canonical` is what the diff keys on, and it is already case-normalised
    (``app/wikilinks.py``), so ``[[kan-1]]`` and ``[[ KAN-1 ]]`` name the same edge as
    ``[[KAN-1]]``."""
    body = "[[kan-1]] and [[ KAN-1 ]] and [[KAN-1]]"

    plan = plan_note_link_changes([], refs_for(body))

    assert plan.to_add == (("KAN", "KAN-1"),)


def test_an_unresolvable_link_is_never_named_for_deletion_by_this_function() -> None:
    """"Unresolved" and "removed" are different facts (the card's own distinction). A link with no
    ``resolved_id`` that is *still in the body* must not be queued for deletion — the diff decides
    presence in the text alone, never `resolved_id`."""
    still_unresolved = link(id=3, kind="KAN", ref="KAN-999999")
    assert still_unresolved.resolved_id is None

    plan = plan_note_link_changes([still_unresolved], refs_for("blocked on [[KAN-999999]]"))

    assert plan.to_delete == ()
    assert plan.to_add == ()


def test_everything_removed_leaves_nothing_to_add_and_everything_to_delete() -> None:
    existing = [link(id=1, kind="KAN", ref="KAN-1"), link(id=2, kind="EPIC", ref="EPIC-2")]

    plan = plan_note_link_changes(existing, refs_for("no links here anymore"))

    assert set(plan.to_delete) == set(existing)
    assert plan.to_add == ()


def test_the_diff_key_is_kind_and_ref_only_never_source_note_id() -> None:
    """`plan_note_link_changes` does not filter by `source_note_id` at all — it trusts `existing` to
    already be scoped to one note, which is `reconcile_note_links`'s job via its `WHERE`. Documented
    here rather than left implicit: a row from a *different* note sharing the same `(kind, ref)`
    would be treated as the same edge if it were ever handed in alongside this note's own rows,
    which is exactly why the wrapper's query matters and the diff itself carries no such guard."""
    from_a_different_note = link(id=1, source_note_id=42, kind="KAN", ref="KAN-1")

    plan = plan_note_link_changes([from_a_different_note], refs_for("[[KAN-1]]"))

    assert plan.to_delete == ()
    assert plan.to_add == ()


# --- The session-touching wrapper --------------------------------------------------------------


class FakeResult:
    def __init__(self, rows: Sequence[NoteLink]) -> None:
        self._rows = list(rows)

    def all(self) -> list[NoteLink]:
        return self._rows


class FakeSession:
    """Enough of a ``Session`` for the wrapper: something that answers a `select` with canned rows
    and records what it is asked to add or delete. It does not inspect the statement it is handed —
    the query's shape is trivial (``select(NoteLink).where(NoteLink.source_note_id == note.id)``)
    and is not what this file is testing."""

    def __init__(self, existing: Sequence[NoteLink]) -> None:
        self.existing = existing
        self.added: list[NoteLink] = []
        self.deleted: list[NoteLink] = []

    def scalars(self, statement: Any) -> FakeResult:
        return FakeResult(self.existing)

    def add(self, obj: NoteLink) -> None:
        self.added.append(obj)

    def delete(self, obj: NoteLink) -> None:
        self.deleted.append(obj)


def a_note(*, id: int = 99, body: str) -> Note:
    """A ``Note`` with just enough populated to reconcile against — the same "bare in-memory ORM
    object" pattern ``test_note_concurrency.py``'s ``stored_note`` uses."""
    return Note(id=id, body=body)


def test_reconcile_adds_new_links_for_a_note_with_no_prior_rows() -> None:
    session = FakeSession(existing=[])
    note = a_note(body="mentions [[KAN-1]] and [[EPIC-2]]")

    reconcile_note_links(session, note)

    assert session.deleted == []
    assert {(row.target_kind, row.target_ref) for row in session.added} == {
        ("KAN", "KAN-1"),
        ("EPIC", "EPIC-2"),
    }
    assert all(row.source_note_id == 99 for row in session.added)
    assert all(row.resolved_id is None for row in session.added), "never resolved by this card"


def test_reconcile_deletes_removed_links_and_leaves_the_rest_alone() -> None:
    kept = link(id=1, source_note_id=99, kind="KAN", ref="KAN-1")
    removed = link(id=2, source_note_id=99, kind="EPIC", ref="EPIC-9")
    session = FakeSession(existing=[kept, removed])
    note = a_note(body="still [[KAN-1]], nothing else")

    reconcile_note_links(session, note)

    assert session.deleted == [removed]
    assert session.deleted[0] is removed, "the same row object, not a rebuilt lookalike"
    assert session.added == []
    assert kept not in session.deleted, "an untouched link must never reach session.delete"


def test_reconcile_on_a_note_with_no_links_at_all_touches_nothing() -> None:
    session = FakeSession(existing=[])
    note = a_note(body="just prose")

    reconcile_note_links(session, note)

    assert session.added == []
    assert session.deleted == []


def test_reconcile_removes_every_row_when_every_link_is_deleted_from_the_body() -> None:
    existing = [
        link(id=1, source_note_id=99, kind="KAN", ref="KAN-1"),
        link(id=2, source_note_id=99, kind="EPIC", ref="EPIC-2"),
    ]
    session = FakeSession(existing=existing)
    note = a_note(body="")

    reconcile_note_links(session, note)

    assert set(session.deleted) == set(existing)
    assert session.added == []
