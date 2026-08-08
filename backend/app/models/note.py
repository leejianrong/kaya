"""The note table, and the sequence that names notes.

ADR 0008 gives a note three names and makes exactly one of them its identity:

===============  ========  =======================================================
name             mutable?  purpose
===============  ========  =======================================================
``id``           no        internal joins, and the ``note_link`` edges in V4
``ref``          **no**    the identifier users, agents and wikilinks actually use
``path``         yes       organisation and display, nothing else
``title``        yes       display, and the wikilink resolution key
===============  ========  =======================================================

``path`` being *just metadata* is the whole point of the decision: moving a note is a ``PATCH`` to
one column, with no link rewriting and nothing to break. That is the Obsidian wart this schema is
shaped to avoid, so nothing may grow a dependency on ``path`` being stable or unique.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Sequence,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# ---------------------------------------------------------------------------------------------
#  THE `NOTE-` PREFIX AND THIS SEQUENCE ARE PERMANENT. DO NOT RENAME EITHER.
#
#  Refs are handed out at INSERT, are immutable, and are never reused. That is what makes them
#  safe to embed in wikilinks, `note_link` edges, exports and anything a user has written down —
#  and it is exactly what makes them impossible to renumber afterwards. There is no correct
#  migration from `NOTE-` to some other prefix: every historical ref in every note body would
#  become a lie, and the ones outside the database (bookmarks, agent transcripts, someone's own
#  notes) cannot be rewritten at all.
#
#  Pandan learned this during a full rebrand. Its ADR 0018 §"What is deliberately NOT renamed"
#  records that `KAN-` survived the rename of everything around it, for these reasons. If a future
#  rebrand reaches this file looking for the last un-renamed thing: this is not an oversight, and
#  "finishing the job" here destroys data. Leave it.
#
#  ADR 0008 §Decision requires this comment to exist. Deleting it is a documented mistake.
# ---------------------------------------------------------------------------------------------
NOTE_REF_PREFIX = "NOTE-"
NOTE_REF_SEQUENCE_NAME = "note_ref_seq"

# On `Base.metadata` so `create_all` emits it; migration `0001` creates it explicitly, because
# Alembic autogenerate does not detect sequences and never will do this for you.
NOTE_REF_SEQUENCE = Sequence(NOTE_REF_SEQUENCE_NAME, start=1, metadata=Base.metadata)

# A `server_default`, not a Python default: the value is allocated by Postgres inside the INSERT,
# so two concurrent writers cannot be handed the same ref and a rolled-back INSERT burns its value
# rather than leaking it to the next writer. Assembling the string in the application would give
# up both properties for nothing.
NOTE_REF_SERVER_DEFAULT = text(f"'{NOTE_REF_PREFIX}' || nextval('{NOTE_REF_SEQUENCE_NAME}')")


class Note(Base):
    """One markdown note, owned by exactly one user."""

    __tablename__ = "note"

    id: Mapped[int] = mapped_column(primary_key=True)
    """Internal surrogate key. Accepted on the wire as an alternative spelling of the ref (ADR
    0008 requires both forms to behave identically), but it is not the identity."""

    ref: Mapped[str] = mapped_column(
        String(32),
        server_default=NOTE_REF_SERVER_DEFAULT,
        nullable=False,
        unique=True,
    )
    """``NOTE-n``. Allocated by Postgres, never assigned by application code, never updated.

    32 characters leaves room for `NOTE-` plus a 27-digit number, which outlives the product.
    """

    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        # RESTRICT, not CASCADE. The `user` row is a *mirror* of pandan's identity, so it is the
        # kind of row someone eventually writes a cleanup job against ("prune mirrors we haven't
        # seen in a year"). Under CASCADE that job silently deletes prose. Under RESTRICT it fails
        # loudly, which is the correct outcome — a mirror row is not the authority on whether a
        # person's notes should exist.
        ForeignKey("user.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    """Owner. Every read is scoped by this (`authorize_note`, KAN-535); Postgres does not index
    the referencing side of a foreign key on its own, hence `index=True`."""

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    """Display, and the key wikilinks resolve against (ADR 0008 / Q19). Not unique — two notes in
    different folders may genuinely share a title, and the recorded edge stores the resolved id
    anyway, so a later rename cannot break it."""

    body: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    """The markdown. `TEXT`, unbounded: a length cap on prose is a cap on the product."""

    path: Mapped[str] = mapped_column(String(1024), nullable=False, server_default=text("''"))
    """Folder + filename, mutable, and carrying **no** uniqueness constraint on purpose — a unique
    path would quietly reintroduce path-as-identity through the back door. The API decides the
    convention (KAN-536); the column just stores what it is told."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    """Doubles as the optimistic-concurrency token (ADR 0009): a `PATCH` carrying a stale value is
    rejected with `409`.

    `now()` is transaction start time, so two writes *inside one transaction* stamp the same value.
    That is fine for the contract as specified — each request is its own transaction — but a future
    batch endpoint that writes one note twice in a single transaction would defeat the precondition
    silently. `clock_timestamp()` is the escape hatch if that day comes.
    """
