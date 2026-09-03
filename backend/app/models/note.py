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

There is a fifth column that is not a name and not user input: ``search_vector`` (KAN-557), a
``tsvector`` Postgres maintains itself. The DDL and the whole argument for its shape live in
``alembic/versions/0002_note_search_vector_and_its_gin_index.py``; what lives *here* is the
declaration that keeps the next ``alembic revision --autogenerate`` from proposing to drop it, and
that is the only reason the expression appears twice in the repository. See the column.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Sequence,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
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

# KAN-557. The generating expression for `search_vector`, byte for byte the string migration `0002`
# writes. Duplicated rather than shared, because a migration may not import the models: it describes
# the schema at one moment in history and has to keep working after this file has moved on.
#
# What holds the two copies together is `tests/unit/test_search_vector_declaration.py`, and it has
# to be a test of its own: `alembic revision --autogenerate` does **not** compare a generated
# column's expression, so a divergence here — or a `Computed(...)` deleted outright — produces an
# autogenerate diff of `pass` and a green integration suite, because the *database* is still right.
# That was measured on this card rather than assumed.
#
# Every decision inside the string — the explicit `'english'` regconfig (bare `to_tsvector` is not
# IMMUTABLE and Postgres refuses it in a stored generated column), the `coalesce` that is a no-op
# today, the A/B weights and the deliberate absence of `path` — is argued in `0002`'s docstring.
SEARCH_VECTOR_EXPRESSION = (
    "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('english', coalesce(body, '')), 'B')"
)


class Note(Base):
    """One markdown note, owned by exactly one user."""

    __tablename__ = "note"

    __table_args__ = (
        # The GIN index over `search_vector`. Declared with the name migration `0002` gives it,
        # because autogenerate compares indexes by name and an unnamed one here would read as a
        # missing index plus a stray one. `postgresql_using` has to match too, for the same reason.
        Index("ix_note_search_vector", "search_vector", postgresql_using="gin"),
    )

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

    team_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(),
        # RESTRICT, matching `owner_id`'s own reasoning exactly: a locally mirrored `team` row
        # (app/models/team.py) is not the authority on whether a note's team association should
        # end, so a future cleanup job that prunes stale team mirrors fails loudly instead of
        # silently turning a team-shared note into a personal one.
        ForeignKey("team.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    """Optional team-default access (ADR 0011, R16). `NULL` is every note's current, unchanged
    meaning — a personal note. `index=True` because Postgres does not index the referencing side of
    a foreign key on its own, and the team-default authorization rung (R16.3) scopes a note *list*
    by `owner_id = caller OR team_id IN (caller's teams)`, the same shape `owner_id`'s own index
    exists to serve.

    Deliberately absent from `NoteRead` for now (`tests/unit/test_note_payload_keys.py`'s
    `NOT_ON_THE_WIRE`) — this card is schema-only, and R16.5 (`KAN-1086`) is what puts it on the
    wire, once note creation can actually set it to something other than `NULL`."""

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
    rejected with `409` (`app/api/concurrency.py`).

    `now()` is transaction start time, so two writes *inside one transaction* stamp the same value.
    KAN-537 looked at this and **kept `now()`**, for two reasons rather than by deferral. Each
    request is its own transaction, so the token moves on every write the contract actually has; and
    `created_at` and `updated_at` are both `now()`, which is what makes them *equal* on a freshly
    created note — under `clock_timestamp()` they would differ by a few microseconds, so "this note
    has never been edited" would stop being expressible as `created_at == updated_at` and start
    being a tolerance.

    What KAN-537 would not leave is the assumption unpinned, because the failure mode is invisible:
    a batch endpoint writing one note twice in a single transaction would stamp the same value both
    times and silently defeat the precondition. `tests/integration/test_notes_api.py`
    ::`test_two_writes_in_one_transaction_share_one_stamp` asserts the behaviour *as it is*, so the
    day that endpoint is written the assumption is a failing test in front of its author rather
    than a comment they never read. `clock_timestamp()` is the escape hatch then — and it is a
    migration, since the default is `server_default`.
    """

    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(SEARCH_VECTOR_EXPRESSION, persisted=True),
        nullable=False,
        # `deferred`, and it is load-bearing rather than tidy. Every list read in the product is
        # `notes_owned_by(principal)`, i.e. `select(Note)`, so without this the tsvector for every
        # note on the page crosses the wire from Postgres on every read — roughly body-sized, for
        # a value no reader of a note has any use for. It also means the search path (KAN-558) can
        # name the column in a `WHERE`/`ts_rank` and still never load it into a row.
        deferred=True,
    )
    """Postgres' full-text index of `title` + `body`, maintained by Postgres (KAN-557).

    `Computed(..., persisted=True)` is `GENERATED ALWAYS AS (...) STORED`, which is what makes
    SLICES §V4's "no application-level reindex step" structural instead of a habit: the value is
    recomputed inside every INSERT and every UPDATE touching `title` or `body`, so
    `app/api/notes.py` cannot forget to maintain it, and Postgres **refuses** a direct write to
    it, so nothing can maintain it wrongly either. `Computed` is also what tells SQLAlchemy to
    leave the column out of INSERT and UPDATE entirely.

    **This column must never reach the wire.** It is absent from `NoteRead` (`app/api/schemas.py`)
    and has to stay absent: it is storage internals, it is the size of the note again, and —
    because `kaya_client`'s `field_names()` reads its vocabulary out of the records the API
    returns — `--fields search_vector` would become a thing a user could type and a column
    `--fields ref` was supposed to avoid paying for. `tests/unit/test_note_payload_keys.py` pins
    the payload's key list so adding it here can never quietly add it there.

    Do not derive anything else from it. It is not a summary, not a word count and not a diffable
    value; it is an index, and its text form (`'runbook':1A 'step':2B`) is Postgres' business.
    """
