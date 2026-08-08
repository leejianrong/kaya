"""What a note looks like on the wire.

Three models and one envelope, and the constraints on them come from migration ``0001`` rather than
from taste: ``title`` is ``String(255)`` and ``path`` is ``String(1024)``, so a longer value is a
`422` here instead of a psycopg ``DataError`` and a `500` two layers down. ``body`` is ``TEXT`` and
carries no limit, because ADR 0008's model comment is right that a length cap on prose is a cap on
the product.

**Shaping does not live here** (ADR 0004). No projection, no truncation, no aggregates: those go
through ``kaya-client``'s ``render()`` seam in V2a/V2b, and a `--fields`-shaped parameter appearing
on one of these routes would be the bug ADR 0004 exists to prevent. What lives here is the full
object; deciding how much of it a caller sees is somebody else's job, deliberately.
"""

from datetime import datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.models import Note

TITLE_MAX = 255
PATH_MAX = 1024

CONTENT_FIELDS = ("title", "body", "path")
"""The three columns a `PATCH` writes, named once because three things below have to agree on the
list: what counts as a change, what a literal ``null`` is refused for, and — since KAN-537 — what is
*not* the precondition. A ``PATCH`` field that leaked into ``changes()`` would be ``setattr``'d onto
the ORM object, so this is a list worth keeping explicit rather than deriving from "every field"."""


class NoteRead(BaseModel):
    """One note, as every route returns it.

    Both of ADR 0008's names are present, and that is a contract rather than convenience:
    "anything the tool prints must be accepted back", so every identifier in this payload is one the
    ref resolver accepts verbatim. ``owner_id`` is deliberately absent — it is always the caller, so
    it carries no information, and leaving it out means no route can ever be asked to return a note
    whose owner is somebody else.

    ``updated_at`` is ADR 0009's optimistic-concurrency token. It is on every read because the `409`
    needs the client to have read one, and a token that only some reads return is a token clients
    forget to send.

    **The token survives the round trip to the microsecond.** ``updated_at`` is ``timestamptz`` and
    Postgres stores microseconds; this model carries a ``datetime``, pydantic serializes it as ISO
    8601 with its offset, and ``NoteUpdate.if_updated_at`` parses that string back to the same
    instant. Nothing in the loop truncates, and nothing may start to — a comparison that lost one
    microsecond would reject *every* correct write with a `409` while still passing any test written
    against a round-numbered timestamp (``tests/unit/test_note_concurrency.py`` pins it with
    ``.123456``).
    """

    model_config = ConfigDict(from_attributes=True)

    ref: str
    id: int
    title: str
    body: str
    path: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, note: Note) -> "NoteRead":
        return cls.model_validate(note)


class NoteList(BaseModel):
    """The list envelope, named rather than bare.

    PLAN §Implementation decisions fixes this shape up front — "a list verb returns
    ``{"notes": [...]}`` … a single read returns a bare object" — because pandan's envelope grew
    per-verb and its skill needed a table to document which verb returned what.

    What is deliberately *not* here: ``summary``, which ADR 0004 §Decision attaches inside
    ``render()`` after truncation and is therefore V2a/V2b's; and ``next_cursor``, which needs a
    paging parameter no card has asked for yet. Both are additive to this object when they arrive,
    which is the reason for wrapping the array in the first place.
    """

    notes: list[NoteRead]


class NoteCreate(BaseModel):
    """``POST /api/v1/notes``. Title required, everything else optional.

    ``body`` and ``path`` default to the empty string rather than to ``None``, matching the columns'
    server defaults, so ``{"title": "…"}`` is a complete request — which is what
    ``test_migration_0001`` already assumes when it says the API can create a note from a title
    alone.

    ``ref``, ``id`` and the timestamps are absent because they are the database's to allocate. A
    caller-supplied ``ref`` would defeat the sequence's atomicity (ADR 0008); ``extra="forbid"``
    means an attempt to send one is a `422` naming the field rather than a silently ignored key.
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=TITLE_MAX)
    """Non-empty: it is the wikilink resolution key (Q19) and the only human-readable thing in a
    list row. An untitled note is addressable but unfindable."""

    body: str = ""
    path: str = Field(default="", max_length=PATH_MAX)


class NoteUpdate(BaseModel):
    """``PATCH /api/v1/notes/{ref}``. Every field optional; omitted means unchanged.

    A *partial* update, so "not sent" and "sent as null" have to be different things. Omitting
    ``body`` must leave 3,000 words alone; the alternative — a PUT-shaped route where a client that
    forgets a field silently blanks it — is the same class of silent prose loss ADR 0009 exists to
    close. ``model_fields_set`` is what tells them apart, and the validator below refuses a literal
    ``null`` rather than treating it as either one, because all three columns are ``NOT NULL`` and
    "clear this field" is spelled ``""``.

    ``path`` is in here because moving a note **is** a `PATCH` to one column, with no link rewriting
    — ADR 0008's whole point, and the reason there is no separate move endpoint.

    ``if_updated_at`` is ADR 0009's precondition, and it is **optional by specification** rather
    than by omission: a write without one is a plain last-write-wins overwrite, which is what keeps
    the API usable from `curl` without a read-first dance and keeps `kaya note edit --force`
    possible.
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=TITLE_MAX)
    body: str | None = None
    path: str | None = Field(default=None, max_length=PATH_MAX)

    if_updated_at: AwareDatetime | None = None
    """The ``updated_at`` this caller read, echoed back. ADR 0009's optimistic-concurrency token.

    **A body field rather than `If-Unmodified-Since`.** That header's format is an HTTP-date, which
    resolves to the second; ``updated_at`` is ``timestamptz`` to the microsecond. Truncating the
    token to a second would make a stale precondition *match* for anything written inside the same
    second — silently turning the guarantee off in exactly the racing-writers case it exists for.
    `If-Match` over an opaque ETag would work, but it would be a second identity for a note on top
    of ADR 0008's two, and nothing has asked for one.

    **Aware, not naive: a naive value is a `422` here, not a guess at UTC.** The comparison is
    exact, so a precondition silently shifted by an offset never matches again and the caller sees
    a permanent `409` it has no way to act on. A `422` naming the field is a bug fixable in one
    edit. Every timestamp kaya emits carries its offset, so a client echoing back what it read is
    never affected — only a hand-typed one is, and that is the caller who most needs telling.
    """

    @model_validator(mode="after")
    def _reject_explicit_nulls(self) -> "NoteUpdate":
        nulled = sorted(name for name in self.model_fields_set if getattr(self, name) is None)

        content_nulls = [name for name in nulled if name in CONTENT_FIELDS]
        if content_nulls:
            raise ValueError(
                f"{', '.join(content_nulls)}: null is not a value here — omit the field to leave "
                'it unchanged, or send "" to clear it'
            )

        if nulled:
            # `"if_updated_at": null` is refused rather than read as "no precondition", because the
            # way a client produces it is a bug — a template that always emits the key, with the
            # timestamp it meant to send missing. Reading it charitably would silently downgrade
            # that client to last-write-wins, which is precisely the prose loss ADR 0009 exists to
            # close, and it would do it to the client that asked for the guarantee.
            raise ValueError(
                f"{', '.join(nulled)}: null is not a value here — omit the field entirely to write "
                "without a precondition (ADR 0009)"
            )

        return self

    def changes(self) -> dict[str, str]:
        """Only the *content* fields the caller actually sent. An empty dict is a valid no-op.

        ``include`` rather than a bare ``exclude_unset``: every value in here is ``setattr``'d onto
        the ORM object, so the precondition — which names a column but is not a write to it — must
        not be able to arrive as one.
        """
        return self.model_dump(include=set(CONTENT_FIELDS), exclude_unset=True)

    def guards_the_body(self) -> bool:
        """Whether ADR 0009's precondition applies to *this* write. Two conditions, both from it.

        The caller sent a precondition — omitting one is a plain overwrite, deliberately.

        And the write touches ``body``. ADR 0009 §Decision: "Metadata-only writes (title, path) stay
        plain LWW, because they're card-shaped fields where the original reasoning holds." The
        reasoning it means is the payload one: the whole deviation from pandan ADR 0007 is that
        losing 3,000 words silently is a different kind of harm from losing a re-typed title. So a
        stale precondition on a rename is *not* a `409` — a rename conflicts with nothing this
        decision is about, and rejecting it would train the SPA's user (who "sends it always") to
        dismiss the banner that matters. A write touching ``title`` **and** ``body`` is guarded, and
        is rejected whole: applying the metadata half of a refused write would be a second silent
        edit, in the opposite direction.
        """
        return self.if_updated_at is not None and "body" in self.model_fields_set
