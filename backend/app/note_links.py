"""Reconciling ``note_link`` against a note's body on every save — KAN-562, SLICES §V5 step 2.
KAN-563 adds note-to-note resolution by title on top: still no network call, because a title
lookup is a local ``SELECT`` and never crosses ADR 0003's line.

Split into a pure diff and a thin session-touching wrapper around it, the same shape
``app/api/concurrency.py`` already uses for ADR 0009 (``note_conflict`` builds the value,
``enforce_precondition`` is the two lines that fetch and apply it). The reason is the same one:
the diff is the part with a rule in it — *which* edges survive a save — and a rule is worth being
able to assert against rows built in memory, with no session, no engine and no migration having
run. The wrapper is deliberately uninteresting: read the current rows, call the pure function, apply
what it says. KAN-563 keeps the same split for its own rule — *which* of a save's brand-new NOTE
edges already has a matching note — via `resolved_ids_for_additions`, pure over a plain `dict` a
caller built however it likes; only the dict-building query is DB-touching, and it is exercised at
the integration layer rather than against a fake, for the reason given below.

**Nothing here makes a network call, and nothing ever will inside this module.** ADR 0003 forbids
kaya blocking on pandan for anything, and reconciling this table on every save is exactly the
operation where that rule is easiest to break by accident — "insert the edge, then go check whether
pandan actually has a card by that number" reads as one step and is two, and the second one is a
request this module must never make. Deciding whether a **pandan** target resolves is KAN-564's
job, against the caller's own PAT, cached; every KAN-/EPIC-kind row `reconcile_note_links` inserts
still carries `resolved_id = NULL`, and every row it leaves alone still keeps whatever `resolved_id`
KAN-564 last gave it — this module never reads that column to decide a KAN-/EPIC-kind deletion and
never writes to one on an update path, only on insert. A **NOTE**-kind row is the one case this
module itself may write `resolved_id` for, and only because the target is kaya's own database: no
request leaves this process to answer "does a note titled *T* exist for this owner?"

**"Unresolved" and "removed" are different facts, and the diff is built to keep them apart.** A
link the parser still finds in the body keeps its row regardless of whether anything has ever
resolved it — that is simply not this function's decision to make. A row is deleted for exactly one
reason: the `(kind, ref)` pair it names is no longer among what `find_wikilinks` /
`find_note_title_links` report for the current body. Nothing here inspects `resolved_id` to decide
a deletion, which is what keeps an UNRESOLVED link from being pruned as though it were an error.

**A NOTE-kind edge is resolved from two directions, and neither one ever touches `resolved_id` once
it is set.** `reconcile_note_links` resolves *forward*: a brand-new ``[[Some Title]]`` in the note
being saved is checked, immediately, against the owner's existing notes, so a link to something that
already exists does not have to wait for a second save to stop being NULL.
`resolve_pending_note_links` resolves *backward*: when a note is created, or renamed, every other
still-unresolved NOTE-kind row across the owner's notes that names the (possibly new) title is
pointed at it — this is what makes "a link to a title that doesn't exist yet resolves once a
matching note is created" true, since nothing would otherwise ever revisit note A's row just
because note B, created later, happens to satisfy it. Both directions share one guard,
`resolved_id IS NULL`, which is what keeps a rename of the *target* from disturbing a link that
already resolved to it (SLICES §V5: "renaming a note leaves existing backlinks to it intact") — the
pointer is an id, survives the rename by construction, and this module's backward pass only ever
fills a gap, never overwrites a value that is already there.

**Title is not unique (`app/models/note.py`), so an ambiguous match needs a tie-break, and it is the
same direction this codebase uses everywhere else one is needed** (KAN-558's search rank, the
unfiltered list order): newest wins. `_notes_by_title` orders by `Note.id` ascending and builds the
lookup dict by iterating in that order, so a later, larger id overwrites an earlier one in the
dict — the most recently created note with a shared title is the one a new link resolves to.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth.authorization import note_ids_owned_by, notes_titled
from app.models import Note
from app.models.note_link import NoteLink
from app.wikilinks import NoteTitleLink, WikilinkRef, find_note_title_links, find_wikilinks

Ref = WikilinkRef | NoteTitleLink
"""Either shape a save's parse pass can hand back — see `app/wikilinks.py`'s "KAN-563's answer" for
why they are two dataclasses rather than one. `plan_note_link_changes` needs nothing from either
beyond the `(kind, canonical)` pair both expose, so it is written against this union rather than
against `WikilinkRef` alone."""


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


def _desired_targets(refs: Iterable[Ref]) -> set[tuple[str, str]]:
    """Every distinct ``(kind, canonical)`` pair `refs` names, occurrence count discarded.

    A body that writes ``[[KAN-1]]`` twice has one relationship to KAN-1, not two — the same reason
    a citation list does not grow a second entry for a second footnote to the same source.
    `find_wikilinks` / `find_note_title_links` report every occurrence, because KAN-567's `[[`
    autocomplete needs the individual spans; the collapse from occurrences to edges happens here,
    once, rather than being left for every caller of this module to remember. `ref.kind` and
    `ref.canonical` are the one attribute pair both `WikilinkRef` and `NoteTitleLink` expose, which
    is what lets this loop not care which dataclass any given `ref` actually is.
    """
    return {(ref.kind, ref.canonical) for ref in refs}


def plan_note_link_changes(existing: Sequence[NoteLink], refs: Iterable[Ref]) -> NoteLinkPlan:
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


def _notes_by_title(session: Session, owner_id: UUID, titles: set[str]) -> dict[str, int]:
    """One ``title -> id`` per requested title, among `owner_id`'s own notes — the one DB-touching
    step `resolved_ids_for_additions` needs and does not do itself, so that function can stay pure.

    A single batched ``SELECT ... WHERE title IN (...)`` rather than one query per title: a save
    rarely adds more than a handful of NOTE-kind links, but there is no reason to pay for a
    round trip per one when they all scope to the same owner. Title is not unique
    (`app/models/note.py`), so ordering by `Note.id` ascending and letting the dict comprehension's
    last-write-wins semantics do the work is the tie-break argued in the module docstring: the
    newest note sharing a title is the one a new link resolves to.

    Not unit-tested against a fake session — see the module docstring's note on why this
    particular DB-touching step is proven at the integration layer instead.

    ``Note`` is named through ``app.auth.authorization.notes_titled`` and never through a
    ``select(Note, ...)`` built here — ``tests/unit/test_no_unscoped_note_query.py`` requires every
    note query to be built in that one module, `notes_owned_by`'s guard extended to this card's own
    reads rather than carved around.
    """
    if not titles:
        return {}
    rows = session.execute(notes_titled(owner_id, titles).order_by(Note.id.asc())).all()
    return {title: note_id for title, note_id in rows}


def resolved_ids_for_additions(
    to_add: Iterable[tuple[str, str]], title_to_id: Mapping[str, int]
) -> dict[tuple[str, str], int]:
    """Which of `to_add`'s NOTE-kind keys already have a matching note, according to `title_to_id`
    — a lookup the caller built once per save (`_notes_by_title`), so this function makes no query
    of its own and is safe to call with a plain `dict` no session ever touched.

    A KAN-/EPIC-kind key never appears in the result, on purpose: ADR 0003 forbids deciding whether
    pandan has a card here, and `title_to_id` — a mapping of *note* titles — has no way to answer
    that question even if this function tried to ask it. A NOTE-kind key whose title is not in
    `title_to_id` is simply absent from the result too, which is what leaves its row's `resolved_id`
    `NULL` rather than some sentinel — "not found yet" and "not asked about" read identically to the
    caller, which is exactly ADR 0003's degrade-to-unresolved posture applied one layer down.
    """
    return {
        (kind, ref): title_to_id[ref]
        for kind, ref in to_add
        if kind == "NOTE" and ref in title_to_id
    }


def reconcile_note_links(session: Session, note: Note) -> None:
    """Apply `plan_note_link_changes` for `note`'s current body against what is already stored.

    Callable for a brand-new note as freely as for an edit: a note with no prior rows simply has an
    empty `existing`, so every desired target lands in `to_add` and nothing lands in `to_delete` —
    "everything found is new" falls out of the general diff rather than needing its own branch. The
    one precondition is `note.id` being populated, which for a just-inserted note means the caller
    has already flushed (`app/api/notes.py`'s `create_note` does, before calling this).

    KAN-563: a brand-new NOTE-kind row is resolved *immediately*, against the owner's notes as they
    stand right now (a just-flushed, not-yet-committed note is visible to this query inside the same
    transaction, which is what lets a note that links to its own title resolve on its own first
    save) — see `resolved_ids_for_additions`. A KAN-/EPIC-kind row is untouched by any of this and
    keeps carrying `resolved_id = NULL`, exactly as before this card.

    Objects are added and deleted on `session` but **not committed here** — that is the caller's
    transaction to close, the same way `enforce_precondition` never commits either. Folding the
    write into the same transaction as the note's own save is what keeps the two consistent: a
    reconcile that failed partway through must not leave a note whose stored body and stored edges
    disagree, and the only way to guarantee that without a second transaction is to never open one.
    """
    existing = session.scalars(
        select(NoteLink).where(NoteLink.source_note_id == note.id)
    ).all()
    refs: list[Ref] = [*find_wikilinks(note.body), *find_note_title_links(note.body)]
    plan = plan_note_link_changes(existing, refs)

    for row in plan.to_delete:
        session.delete(row)

    note_titles = {ref for kind, ref in plan.to_add if kind == "NOTE"}
    title_to_id = _notes_by_title(session, note.owner_id, note_titles)
    resolved = resolved_ids_for_additions(plan.to_add, title_to_id)

    for target_kind, target_ref in plan.to_add:
        session.add(
            NoteLink(
                source_note_id=note.id,
                target_kind=target_kind,
                target_ref=target_ref,
                resolved_id=resolved.get((target_kind, target_ref)),
            )
        )


def resolve_pending_note_links(session: Session, note: Note) -> None:
    """Point every still-unresolved NOTE-kind edge naming `note.title`, among `note.owner_id`'s own
    notes, at `note.id`.

    KAN-563's *backward* resolution pass: call this whenever a note's title lands — on create, and
    on any update whose payload includes `title` — so a link written before its target existed
    stops waiting for someone to re-save the note that contains it. `app/api/notes.py` is the only
    caller, in the same transaction as the note's own write, for the same reason
    `reconcile_note_links` never commits: a resolution that landed and a note write that didn't (or
    the reverse) is a state nothing here may produce.

    The ``resolved_id IS NULL`` guard is the whole of "a rename of the target never disturbs an
    edge that already resolved to something" (SLICES §V5's own wording) — a row this statement
    would otherwise touch again is filtered out before it can be, which is what keeps a rename from
    reaching backlinks pointed at the *old* title-holder, or repeatedly reassigning a row that
    settled the first time a matching title appeared. `Note.title` (never `target_ref`) is the
    match key, and it is compared exactly, case included — see the module docstring's
    `_notes_by_title` paragraph for the equivalent forward-direction lookup.

    The owner-scoping subquery is `app.auth.authorization.note_ids_owned_by`, not a
    `select(Note.id)` built here, for the same structural reason `_notes_by_title` reaches for
    `notes_titled` instead of its own — see that function's docstring for the cross-owner leak this
    guards against.
    """
    session.execute(
        update(NoteLink)
        .where(
            NoteLink.target_kind == "NOTE",
            NoteLink.target_ref == note.title,
            NoteLink.resolved_id.is_(None),
            NoteLink.source_note_id.in_(note_ids_owned_by(note.owner_id)),
        )
        .values(resolved_id=note.id)
    )
