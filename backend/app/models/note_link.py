"""``note_link``: one row per ``[[...]]`` wikilink a note's body contains — KAN-562, SLICES §V5
step 2, built on KAN-561's parser (``app/wikilinks.py``).

An edge, not a fact about pandan. Recording that a note's body currently contains ``[[KAN-123]]``
is local bookkeeping — it costs nothing, needs no network, and stays true regardless of whether
pandan has ever heard of ``KAN-123``. Deciding whether pandan actually has a card by that number is
a *different* operation (a network call, cached, against the caller's own PAT) and is KAN-564's job
alone. ADR 0003 forbids kaya blocking on pandan for anything, and this table is where that rule
would be easiest to break by accident — a naive "insert the edge and go verify it" implementation
reaches for a session and an HTTP client in the same breath. Nothing in this module, or in
``app/note_links.py``'s reconcile logic built on it, makes a network call. Every row this card ever
writes has ``resolved_id IS NULL``.

**Four columns, and the fourth is deliberately inert here.**

- ``source_note_id`` — the note whose body the edge came from. ``note.id``, ADR 0008's internal
  surrogate, exactly the column the model's own table names in its docstring
  ("internal joins, and the ``note_link`` edges in V4") as the reason it exists at all. Never
  ``ref``: a ref is stable too, but the id is the column every other internal join in this schema
  already uses, and there is no reason for this table to be the first exception.
- ``target_kind`` — a plain string, not a Postgres ``ENUM`` and not constrained to
  ``app.wikilinks.WIKILINK_KINDS``. Today it only ever holds ``"KAN"`` or ``"EPIC"``, but KAN-563's
  own note-to-note wikilinks (``[[Some Note Title]]``, resolved by title rather than by a pandan
  prefix) need a third value — plausibly ``"NOTE"`` — and a Postgres enum type takes a migration to
  widen while an unconstrained ``String`` does not. This column is the one place CLAUDE.md's brief
  singles out: "choose your schema so a future ``target_kind`` value fits without a migration."
- ``target_ref`` — the target's identifier *within* its kind's namespace, stored as
  ``WikilinkRef.canonical`` would render it for a pandan target: ``"KAN-123"`` / ``"EPIC-45"``, not
  the bare number. Two reasons to keep the prefix rather than strip it. First, ``canonical`` is
  exactly the string KAN-564 sends pandan to resolve the reference (see that property's own
  docstring in ``app/wikilinks.py``), so storing it verbatim means the resolution job reads this
  column and asks pandan with no reassembly step — the parser already did the normalising work
  once, and there is no reason to throw it away and let a second piece of code reconstruct it.
  Second, and more binding for the future: a ``NOTE``-kind edge (KAN-563) has no numeric part to
  reunite with a prefix — its "ref" *is* a note title — so a column that stored only a bare number
  today would need to change shape, not just widen, the day a non-numeric kind arrives. A string
  column holding "the target's identifier, however this kind spells one" needs no such change.
  Sized to ``TITLE_MAX`` (``app/api/schemas.py``) rather than to a pandan ref's few characters,
  because that title-shaped future value is exactly what has to fit in it without a migration.
- ``resolved_id`` — nullable, untouched by anything in this card. What it holds once KAN-564
  exists is that card's decision to make (a cached pandan identifier for a ``KAN``/``EPIC`` edge;
  plausibly the target note's own ``id`` for a future ``NOTE`` edge, once one resolves by title) —
  deliberately not a foreign key here, since which table (if any) it names depends on
  ``target_kind`` and no single ``ForeignKey`` can express that. What *is* settled now: this column
  is how "unresolved" is told apart from "removed". A link the parser still finds in the body keeps
  its row — with ``resolved_id`` however it was left, ``NULL`` if nothing has ever resolved it — for
  as long as the ``[[...]]`` stays in the text; it is deleted only when the wikilink itself
  disappears from a save (``app/note_links.py``'s reconcile). "Unresolvable so far" and "no longer
  referenced" are different facts, and only one of them is a reason to drop the row.

**The unique constraint is the edge's identity, and it is what makes "leave unchanged rows
untouched" possible rather than aspirational.** ``(source_note_id, target_kind, target_ref)`` is
unique, so a note that writes ``[[KAN-1]]`` twice in one body still gets exactly one row — a
relationship to KAN-1 either exists or it doesn't, the same way a citation list doesn't grow a
second entry for a second footnote to the same source. That is also what lets the reconciler compare
"what's stored" against "what the parser found" as two sets over this same key and leave the
intersection alone: without an identity narrower than the primary key, "unchanged" would have
nothing to be equal *to*, and the only implementation left is delete-everything-and-reinsert — which
is precisely the churn this card exists to avoid, since it would reset ``resolved_id`` (and any
timestamp KAN-564 adds) on every single save regardless of whether that edge actually changed.

**``ondelete="CASCADE"`` on ``source_note_id``, unlike ``note.owner_id``'s ``RESTRICT``.** The two
foreign keys answer different questions. ``owner_id → user`` protects prose from a mirror-cleanup
job that has no business deleting notes as a side effect (``app/models/note.py``).
``source_note_id → note`` is the reverse relationship: a ``note_link`` row has no meaning
independent of the note whose body it was extracted from, so deleting that note should take its
outbound edges with it exactly the way deleting a note already takes nothing else — there is no
cleanup job for which "the note is gone but its wikilink edges remain" is the correct state to
reach, and requiring ``delete_note`` to also reconcile against an empty body would be the same
operation restated at a second call site.

**No separate index on ``source_note_id``.** ``note.owner_id`` needs ``index=True`` because nothing
else indexes it (``app/models/note.py``'s comment on the same point). Here the unique constraint
above already is a composite index with ``source_note_id`` as its leading column, and Postgres can
use a composite index's prefix for a query that only names the leading column — which is exactly the
reconciler's read ("every existing edge for this note"). A second single-column index would be a
second index Postgres has to maintain on every write, covering a query the first index already
answers.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

TARGET_KIND_MAX = 16
"""Room for ``"KAN"``, ``"EPIC"`` and a plausible ``"NOTE"`` (KAN-563) with margin, not a tight fit
to today's two-value vocabulary — the whole point of this column being a plain string."""

TARGET_KIND_NOTE = "NOTE"
"""KAN-563's note-to-note kind, as a name rather than a literal at each of the five places that
now test for it (``app/note_links.py``'s three, and KAN-566's ``notes_linking_to`` and
``app/api/links.py``).

It lives here, beside the column whose value it is, rather than in ``app/wikilinks.py`` beside the
parser that produces it — ``NoteTitleLink.kind`` is a ``Literal["NOTE"]`` with a default, which is
the *parser*'s statement about what it emits, and a storage value that only happens to agree with
it today is the coupling this constant exists to make explicit. The ``KAN``/``EPIC`` kinds get no
equivalent, deliberately: ``app.wikilinks.WIKILINK_KINDS`` already names that pair and this table
never singles one of them out — the only comparison anything makes against ``target_kind`` is "is
this the local kind or a pandan one?", which is one name, not three.

**KAN-566 is where this stopped being cosmetic.** ``notes_linking_to`` filters on it *and* on
``resolved_id``, and the ``target_kind`` half is the load-bearing one: ``resolved_id`` is
deliberately not a ``ForeignKey`` because which table it points at depends on this column, so
without the kind filter a KAN-kind row whose pandan card id happened to equal some note's id would
surface as a backlink to that note. Nothing writes a KAN-kind ``resolved_id`` today, which is
exactly why the guard has to be structural rather than remembered."""

TARGET_REF_MAX = 255
"""Byte-for-byte ``app/api/schemas.py``'s ``TITLE_MAX``, duplicated rather than imported: a model
does not reach into the API layer for a constant, the same direction ``app/models/note.py`` already
draws between itself and migration ``0002`` for ``SEARCH_VECTOR_EXPRESSION``. The value matters
because KAN-563's NOTE-kind edges store a note title here, and that is the value this column has to
fit without a migration the day that card lands."""


class NoteLink(Base):
    """One wikilink edge, source note to target reference, reconciled on every body save.

    See the module docstring for the argument behind every column and constraint here; what is left
    to say is what this class deliberately is *not*. It is not resolved against pandan by anything
    in its own module or in ``app/note_links.py``'s reconcile logic (ADR 0003) — every row this
    card writes carries ``resolved_id IS NULL``, always, and stays that way until KAN-564 exists to
    change it.

    **KAN-566 is now the reader**, and the access pattern it needed required no migration — which is
    what the sentence this paragraph replaces was hoping for. Two queries: ``app/api/links.py``'s
    ``outbound_edges`` reads by ``source_note_id``, served by the unique constraint's leading
    column, which is why there is still no second index; and ``app.auth.notes_linking_to`` joins
    this table to ``note`` and filters on ``(target_kind, resolved_id)``. That second one has no
    index behind it and is correct at any corpus size this product has seen. An index on
    ``(target_kind, resolved_id)`` is the thing to add when a measurement asks for one, and nothing
    has — see ``app/models/note.py``'s own comment on paying for an index on every write.
    """

    __tablename__ = "note_link"

    __table_args__ = (UniqueConstraint("source_note_id", "target_kind", "target_ref"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    """Surrogate key for the edge itself, not for the relationship it names — the *identity* of an
    edge, for the reconciler's purposes, is the unique constraint below. This exists so an untouched
    row can be shown to be **the same row** (same ``id``) across two saves, which is the property
    ``tests/integration``'s reconcile tests pin: unchanged means untouched, not deleted and
    reinserted with a new ``id`` that happens to compare equal on every other column."""

    source_note_id: Mapped[int] = mapped_column(
        ForeignKey("note.id", ondelete="CASCADE"), nullable=False
    )
    """The note whose body this edge was extracted from. ``note.id``, never ``note.ref`` — see the
    module docstring's first bullet."""

    target_kind: Mapped[str] = mapped_column(String(TARGET_KIND_MAX), nullable=False)
    """``"KAN"`` or ``"EPIC"`` today (``app.wikilinks.WIKILINK_KINDS``); a plain string so a future
    kind is a value, not a migration."""

    target_ref: Mapped[str] = mapped_column(String(TARGET_REF_MAX), nullable=False)
    """The target's identifier within ``target_kind``'s namespace — ``WikilinkRef.canonical`` for a
    pandan target, e.g. ``"KAN-123"``. See the module docstring for why the prefix is kept rather
    than stored as a bare number."""

    resolved_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """``NULL`` from this card, always. KAN-564's to fill in and to decide the meaning of; see the
    module docstring's fourth bullet. Not a ``ForeignKey``: which table it would reference depends
    on ``target_kind``, and no single constraint can express that."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    """When this edge was first recorded. Not touched by the reconciler on a save that leaves the
    edge in place — only insertion sets it, which is part of what "untouched" means here."""
