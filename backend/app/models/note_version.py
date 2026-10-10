"""``note_version``: one row per body a note's `PATCH`/`POST` has ever written — R13
(``docs/roadmap/BREADBOARD.md``), KAN-1064.

A concurrent-edit conflict (ADR 0009) already stops a save from silently losing prose to a *racing*
writer. This table is the complementary guarantee: a save that was not concurrent — just wrong, a
paragraph deleted by mistake, a rewrite the author regrets — is still recoverable, because every
body a save ever produced is sitting in this table under the note it belongs to.

**Three columns, and the shape is deliberately ``note_link``'s** (``app/models/note_link.py``):

- ``note_id`` — ``note.id``, ``ON DELETE CASCADE``. A version has no meaning independent of the note
  whose body it is a snapshot of, so deleting the note takes its history with it — the identical
  argument ``note_link.source_note_id`` makes, for the identical reason (no cleanup job for which
  "the note is gone but its old bodies remain" is a state worth protecting).
- ``body`` — ``TEXT``, unbounded, the same column type and the same reasoning as ``note.body``: a
  length cap on prose is a cap on the product, and a version is exactly as long as the body it was
  cut from.
- ``created_at`` — when this snapshot was cut, i.e. when the save that produced it committed.

**No ``owner_id``, on purpose, and for the same reason ``note_link`` has none.** A version is
reached only by joining through its parent note — ``app/note_versions.py``'s ``note_versions``
composes no ``Note`` query of its own; it constrains ``note_id`` to a value that has already been
through ``NoteFromRef`` and ``authorize_note``, which is what makes a second scoped-query surface
unnecessary here just as it is for ``note_link`` (``tests/unit/test_no_unscoped_note_query.py``'s
Rule 3 argues the general case in full: the only path from a row with no owner column to an owner
is the note id it carries, and a note id that already passed authorization inherits it).

**No index beyond the implicit one on the primary key.** Every read in this card is
``WHERE note_id = :note_id ORDER BY created_at DESC, id DESC`` for one note at a time — never a
cross-note query — so an index on ``note_id`` earns its keep the moment a corpus makes the
sequential scan show up in a measurement, and nothing has measured that yet. Adding one ahead of a
measurement would be paying a write-time cost (every save now maintains a second structure) for a
read-time saving nobody has shown is needed — the same trade ``app/models/note_link.py`` declines
for its own ``source_note_id`` in the opposite direction (there, the unique constraint already *is*
the index; a note_version has no equivalent constraint to reuse).
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class NoteVersion(Base):
    """One snapshot of a note's body, cut by ``app/note_versions.py``'s ``cut_version`` on every
    save that writes ``body`` — never edited afterward, only ever inserted or cascade-deleted."""

    __tablename__ = "note_version"

    id: Mapped[int] = mapped_column(primary_key=True)

    note_id: Mapped[int] = mapped_column(ForeignKey("note.id", ondelete="CASCADE"), nullable=False)
    """The note this is a version *of*. Never ``note.ref``, matching every other internal join in
    this schema (``app/models/note_link.py``'s module docstring makes the same call for the same
    reason: ``id`` is the column every other join already uses)."""

    body: Mapped[str] = mapped_column(Text, nullable=False)
    """The whole body, as it stood the moment this snapshot was cut. Not a diff: a diff would need
    a base to apply against, and the point of version history is that any one row stands alone as a
    complete, restorable body."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    """When this snapshot was cut, i.e. the committing save's transaction start time — the same
    ``now()`` semantics ``note.created_at``/``note.updated_at`` already carry, documented in full in
    ``app/models/note.py``."""

    # ---- actor (KAY-138, ADR 0015 precondition 1). Six nullable columns, all NULL on a row cut
    # before this card ("before tracking"). Written once by ``cut_version`` from the request's
    # ``Principal`` and never updated. Snapshots, not joins: a revoked token or a renamed one must
    # not rewrite who made an old edit, and a revoked token's row is gone.

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("kaya_account.id", ondelete="SET NULL"), nullable=True
    )
    """The account whose credential made the save. For a team note this is not the note's owner."""

    actor_channel: Mapped[str | None] = mapped_column(String(16), nullable=True)
    """``session`` (a browser cookie session) or ``token`` (a ``kaya_pat_`` bearer: the CLI, a
    script, or the hosted MCP endpoint, which are indistinguishable server-side because the MCP
    tools call the REST API with the caller's own bearer)."""

    actor_token_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    """``personal_access_token.id`` at save time. Deliberately **no foreign key**: revoking a token
    must not erase or null the record of what it did."""

    actor_token_prefix: Mapped[str | None] = mapped_column(String(32), nullable=True)
    """The same non-secret display hint Settings lists (``kaya_pat_ab12``), never more."""

    actor_token_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    """The token's caller-chosen name (device-flow and OAuth tokens are named by their origin)."""

    actor_token_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    """Reserved for token presets (pandan ADR 0027's kind; the sibling KAY-141). ``cut_version``
    copies it from ``Principal.token_kind`` when that exists; NULL until then."""
