"""Reconciling ``note_link`` against a note's body on every save — KAN-562, SLICES §V5 step 2.

Split into a pure diff and a thin session-touching wrapper around it, the same shape
``app/api/concurrency.py`` already uses for ADR 0009 (``note_conflict`` builds the value,
``enforce_precondition`` is the two lines that fetch and apply it). The reason is the same one:
the diff is the part with a rule in it — *which* edges survive a save — and a rule is worth being
able to assert against rows built in memory, with no session, no engine and no migration having
run. The wrapper is deliberately uninteresting: read the current rows, call the pure function, apply
what it says.

**Nothing here makes a network call, and nothing ever will inside this module.** ADR 0003 forbids
kaya blocking on pandan for anything, and reconciling this table on every save is exactly the
operation where that rule is easiest to break by accident — "insert the edge, then go check whether
pandan actually has a card by that number" reads as one step and is two, and the second one is a
request this module must never make. Deciding whether a target resolves is KAN-564's job, against
the caller's own PAT, cached; every row `reconcile_note_links` inserts carries `resolved_id = NULL`,
and every row it leaves alone keeps whatever `resolved_id` KAN-564 last gave it — this module never
reads that column to decide anything and never writes to it on an update path, only on insert.

**"Unresolved" and "removed" are different facts, and the diff is built to keep them apart.** A
link the parser still finds in the body keeps its row regardless of whether anything has ever
resolved it — that is simply not this function's decision to make. A row is deleted for exactly one
reason: the `(kind, ref)` pair it names is no longer among what `find_wikilinks` reports for the
current body. Nothing here inspects `resolved_id` to decide a deletion, which is what keeps an
UNRESOLVED link from being pruned as though it were an error.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Note
from app.models.note_link import NoteLink
from app.wikilinks import WikilinkRef, find_wikilinks


@dataclass(frozen=True)
class NoteLinkPlan:
    """What reconciling one note's edges requires doing, and nothing about how to do it.

    ``to_delete`` holds the actual `NoteLink` rows to remove — not just their keys — because the
    caller needs the identity-mapped ORM objects to hand to `session.delete`, and building a plan
    that named only keys would make the wrapper re-look them up. ``to_add`` holds bare
    `(target_kind, target_ref)` pairs instead, because there is nothing to look up: a new row is
    built from exactly these two values plus the note's own id, which the diff does not have and
    does not need.

    Deliberately absent: anything that would leave `resolved_id` alone. A `NoteLink` this plan does
    not mention is the third, unnamed case — "leave it exactly as it is" — and that is the state the
    reconciler must default to, not one it has to be told to reach.
    """

    to_delete: tuple[NoteLink, ...]
    to_add: tuple[tuple[str, str], ...]


def _desired_targets(refs: Iterable[WikilinkRef]) -> set[tuple[str, str]]:
    """Every distinct ``(kind, canonical)`` pair `refs` names, occurrence count discarded.

    A body that writes ``[[KAN-1]]`` twice has one relationship to KAN-1, not two — the same reason
    a citation list does not grow a second entry for a second footnote to the same source.
    `find_wikilinks` reports every occurrence, because KAN-567's `[[` autocomplete needs the
    individual spans; the collapse from occurrences to edges happens here, once, rather than being
    left for every caller of this module to remember.
    """
    return {(ref.kind, ref.canonical) for ref in refs}


def plan_note_link_changes(
    existing: Sequence[NoteLink], refs: Iterable[WikilinkRef]
) -> NoteLinkPlan:
    """The diff, as a pure function: no session, no query, safe to call on rows built in memory.

    `existing` is keyed the same way the table's own unique constraint is —
    ``(target_kind, target_ref)`` — and compared against `_desired_targets`. A key present in both
    is an edge that survives the save **completely untouched**: it is named in neither `to_delete`
    nor `to_add`, so the wrapper never issues a statement that mentions it, `resolved_id` cannot be
    disturbed, and the row's own identity (its `id`, and any timestamp a later card adds) survives
    the round trip byte for byte. A key in `existing` but not in the desired set is a link the body
    no longer contains, so its row is queued for deletion regardless of whether it was ever resolved
    — deletion here is driven by presence in the text, never by `resolved_id`. A key in the desired
    set but not in `existing` is queued for insertion.

    Duplicate keys in `existing` are not expected — the table's unique constraint forbids them — but
    if two rows ever did share a key, the later one in `existing` wins the dict-building pass below
    and the earlier is treated as though it were not there (i.e. queued for deletion if its key is
    not desired). That is a property of `dict`'s last-write-wins construction rather than a decision
    made for its own sake; the constraint is what actually prevents the situation.
    """
    desired = _desired_targets(refs)
    current = {(row.target_kind, row.target_ref): row for row in existing}

    to_delete = tuple(row for key, row in current.items() if key not in desired)
    to_add = tuple(key for key in desired if key not in current)

    return NoteLinkPlan(to_delete=to_delete, to_add=to_add)


def reconcile_note_links(session: Session, note: Note) -> None:
    """Apply `plan_note_link_changes` for `note`'s current body against what is already stored.

    Callable for a brand-new note as freely as for an edit: a note with no prior rows simply has an
    empty `existing`, so every desired target lands in `to_add` and nothing lands in `to_delete` —
    "everything found is new" falls out of the general diff rather than needing its own branch. The
    one precondition is `note.id` being populated, which for a just-inserted note means the caller
    has already flushed (`app/api/notes.py`'s `create_note` does, before calling this).

    Objects are added and deleted on `session` but **not committed here** — that is the caller's
    transaction to close, the same way `enforce_precondition` never commits either. Folding the
    write into the same transaction as the note's own save is what keeps the two consistent: a
    reconcile that failed partway through must not leave a note whose stored body and stored edges
    disagree, and the only way to guarantee that without a second transaction is to never open one.
    """
    existing = session.scalars(
        select(NoteLink).where(NoteLink.source_note_id == note.id)
    ).all()
    plan = plan_note_link_changes(existing, find_wikilinks(note.body))

    for row in plan.to_delete:
        session.delete(row)

    for target_kind, target_ref in plan.to_add:
        session.add(
            NoteLink(source_note_id=note.id, target_kind=target_kind, target_ref=target_ref)
        )
