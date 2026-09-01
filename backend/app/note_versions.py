"""Version history for a note's body — R13 (``docs/roadmap/BREADBOARD.md``), KAN-1064/1065/1066.

A concurrent-edit conflict (ADR 0009) already stops a save from silently losing prose to a *racing*
writer. This module is the complementary guarantee: a save that was not concurrent — just wrong — is
still recoverable, because ``cut_version`` snapshots every body a save ever wrote.

**Cut point.** ``create_note`` and ``update_note`` (``app/api/notes.py``) call ``cut_version`` on
every write that touches ``body`` — no debounce, no "only if the content actually changed"
heuristic. Simpler, and cheap: a note body is small text, and pruning old versions is a separate,
later concern this card does not take on (R13's own scoping call, not an oversight).

**Reached only by joining through the parent note, never queried standalone** — the same pattern
``note_link`` uses (``app/models/note_link.py``, and CLAUDE.md's owner-scoping rule in as many
words). ``note_versions`` below builds a statement that constrains ``NoteVersion.note_id`` to a
plain ``int``, and every caller of it gets that id from ``NoteFromRef`` — which has already been
through ``authorize_note`` — so the authorization happens one layer up, on the note, and this query
inherits it rather than needing a second scoped-query surface
(``tests/unit/test_no_unscoped_note_query.py``'s Rule 3 makes the identical argument for the
identical reason about ``note_link``). Nothing here builds a ``select(Note)`` — the module never
names ``Note`` in a query at all — which is what keeps this file outside Rule 1's scope without
needing to be inside it.

**Restore is not this module's concern.** BREADBOARD.md and ADR 0008 are explicit: a restore is a
plain ``PATCH /api/v1/notes/{ref}`` with ``body`` set to the chosen version's body, going through
the same route, the same ``enforce_precondition`` and the same ``cut_version`` call every other
body write does — there is no bespoke restore endpoint and nothing in this module needs to know a
write was a restore rather than an edit. Restoring an old version is itself a save, and it cuts its
own new version the same way, which is what makes "undo a bad restore" already work with no extra
code: the version just replaced is still sitting in the table, one row above the one the restore
added.
"""

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.note import Note
from app.models.note_version import NoteVersion


def cut_version(session: Session, note: Note) -> None:
    """Snapshot ``note.body`` as a new ``note_version`` row.

    Call this **after** ``note.body`` already holds the value being saved — the value ``Note(...)``
    was constructed with in ``create_note``, or the one a `PATCH`'s ``setattr`` just assigned in
    ``update_note`` — so ``note_version.body`` is always the *result* of the write, never the value
    it replaced. ``note.id`` must already be populated: ``create_note``'s explicit ``flush()`` (the
    same one KAN-562's ``reconcile_note_links`` already depends on) or, on the update path, the id
    an already-persisted note has always had.

    Adds to the session without flushing or committing — the caller's own transaction covers this
    the same way it already covers the note write and, on `create`, the `note_link` reconcile: one
    commit, one transaction, so a version can never land without the save that produced it, or the
    reverse.
    """
    session.add(NoteVersion(note_id=note.id, body=note.body))


def note_versions(note_id: int) -> Select[tuple[NoteVersion]]:
    """Every version of ``note_id``'s body, newest first.

    Takes a plain ``int`` rather than a ``Note`` or a ``Principal``, matching
    ``app/api/links.py``'s ``outbound_edges`` — the caller already has the id, straight out of
    ``NoteFromRef``, and manufacturing a richer parameter to satisfy a convention here would be the
    tail wagging the dog.

    ``created_at DESC, id DESC``: the same list order and the same tie-break every other unranked
    list in this codebase uses (``app/api/notes.py``'s unfiltered list, ``notes_linking_to``), for
    the same reason — ``now()`` is transaction start time (``app/models/note.py``), so two versions
    cut inside one transaction would otherwise share a stamp and sort arbitrarily. Today a save cuts
    at most one version, but the tie-break costs nothing to have in place before a future batch path
    needs it.
    """
    return (
        select(NoteVersion)
        .where(NoteVersion.note_id == note_id)
        .order_by(NoteVersion.created_at.desc(), NoteVersion.id.desc())
    )
