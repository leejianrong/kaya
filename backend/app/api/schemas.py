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

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import Note

TITLE_MAX = 255
PATH_MAX = 1024


class NoteRead(BaseModel):
    """One note, as every route returns it.

    Both of ADR 0008's names are present, and that is a contract rather than convenience:
    "anything the tool prints must be accepted back", so every identifier in this payload is one the
    ref resolver accepts verbatim. ``owner_id`` is deliberately absent — it is always the caller, so
    it carries no information, and leaving it out means no route can ever be asked to return a note
    whose owner is somebody else.

    ``updated_at`` is ADR 0009's optimistic-concurrency token. It is on every read because KAN-537's
    `409` needs the client to have read one, and a token that only some reads return is a token
    clients forget to send.
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

    No precondition field. ADR 0009 says a write that omits one is accepted as a plain overwrite,
    deliberately, so `curl` works without a read-first dance; the `409` branch that reads a supplied
    ``updated_at`` is KAN-537's and slots in beside this.
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=TITLE_MAX)
    body: str | None = None
    path: str | None = Field(default=None, max_length=PATH_MAX)

    @model_validator(mode="after")
    def _reject_explicit_nulls(self) -> "NoteUpdate":
        nulled = sorted(name for name in self.model_fields_set if getattr(self, name) is None)
        if nulled:
            raise ValueError(
                f"{', '.join(nulled)}: null is not a value here — omit the field to leave it "
                'unchanged, or send "" to clear it'
            )
        return self

    def changes(self) -> dict[str, str]:
        """Only the fields the caller actually sent. An empty dict is a valid no-op request."""
        return self.model_dump(exclude_unset=True)
