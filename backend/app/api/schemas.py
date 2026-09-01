"""What a note, and since KAN-566 a link, and since KAN-1049 a board embed, looks like on the wire.

Three note models and one envelope, plus KAN-566's ``LinkRead``/``LinkList`` and KAN-1049's
``EmbedCard``/``BoardEmbedResponse``. The note constraints
come from migration ``0001`` rather than from taste: ``title`` is ``String(255)`` and ``path`` is
``String(1024)``, so a longer value is a `422` here instead of a psycopg ``DataError`` and a `500`
two layers down. ``body`` is ``TEXT`` and carries no limit, because ADR 0008's model comment is
right that a length cap on prose is a cap on the product.

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
    the API usable from `curl` without a read-first dance and is what `kaya note edit` does when the
    caller omits `--if-updated-at` (KAN-551: the CLI spells the unguarded write by *not* passing a
    flag, so there is no `--force`).
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


class LinkRead(BaseModel):
    """One outbound wikilink of a note, resolved as far as it can be — KAN-566's `/links`.

    Five keys, and the shape's whole job is to let a renderer draw a pill (KAN-567) or a panel
    (KAN-568) **without branching on whether resolution succeeded**. Q26 settled that an unresolved
    link renders as an unresolved link rather than as an error, so every resolved-side field is
    nullable and ``null`` is the honest value rather than a missing key.

    **No internal id anywhere, and that is the reason this class exists rather than the table being
    serialized.** ``note_link`` carries ``id``, ``source_note_id`` and ``resolved_id``; all three
    are internal surrogates, and ADR 0008 makes a note's identity its ``ref``. ``resolved_id`` is
    the one it would be most tempting to publish — it is already the thing the edge points at — and
    publishing it would hand a caller a number that no route accepts and that ``kaya_client``'s
    ``field_names()`` would then offer as ``--fields resolved_id``. ``source_note_id`` is absent for
    a second reason on top: it is the note in the URL, so it carries no information (the same
    argument ``NoteRead`` makes about ``owner_id``). ``tests/unit/test_link_payload_keys.py`` pins
    this list in order for the reason ``tests/unit/test_note_payload_keys.py`` pins the other one.

    **There is deliberately no ``resolved`` boolean.** It would be a second spelling of
    ``resolved_ref is null``, and two spellings of one state is how a client ends up branching on
    the one that happens to be wrong — the same argument ADR 0005 makes for ``--full`` being
    ``text_limit=0`` and not also a ``full=True``. ``resolved_ref`` is the flag *and* the value.
    """

    model_config = ConfigDict(from_attributes=True)

    target_kind: str
    """``"KAN"``, ``"EPIC"`` or ``"NOTE"`` (``app/models/note_link.py``). A plain string here for
    the same reason it is a plain string in the column: the vocabulary is a value, not a schema,
    and an enum on the wire would make adding a kind a breaking change for every generated
    client."""

    target_ref: str
    """What the body actually said, between the brackets: ``"KAN-501"`` for a pandan reference
    (``WikilinkRef.canonical`` — case-normalised, brackets and padding gone) or the note title
    exactly as typed for a ``NOTE`` edge, never case-folded.

    This is the *written* half of the link and it is never rewritten. ADR 0008 forbids link
    rewriting on a move, and the same reasoning covers a rename: the body says what the author
    typed, and a payload that silently reported the new title here would be claiming the note's text
    changed when it did not."""

    resolved_ref: str | None
    """The canonical identifier of the thing this link points at, or ``null`` for an unresolved one.

    ``NOTE-7`` for a resolved note-to-note edge, ``KAN-501``/``EPIC-3`` for a card or epic pandan
    answered for. For a pandan target that is the same string as ``target_ref``, which is redundant
    and is kept anyway: uniform means a renderer reads one field to get "what do I link to", and the
    NOTE case — where the two genuinely differ, because a title was typed and a ref came back — is
    the one that would otherwise need a branch.

    ``null`` covers four situations a caller cannot and should not tell apart (Q26, ADR 0003):
    pandan does not have that ticket; pandan has it but this caller cannot see it; pandan could not
    be reached at all; and a ``[[Title]]`` naming no note the caller owns. The first two are
    pandan's own answer and are indistinguishable *there* by design (see
    ``app/integrations/card_resolution.py``); collapsing the other two into the same value is what
    keeps an outage from looking like a broken link."""

    title: str | None
    """The resolved thing's **current** title — the card's, the epic's, or the target note's — or
    ``null`` when unresolved.

    Current, not stored, and for a ``NOTE`` edge that is the visible half of SLICES §V5's rename
    criterion: after the target is renamed, ``target_ref`` still shows what was typed and this shows
    what the note is called now. Nothing here is cached in kaya's database, so the two can never
    drift apart into a stale pair."""

    column: str | None
    """Pandan's column name for a resolved **card** (e.g. ``"in_progress"``), and ``null`` for
    everything else: an epic has no column (``ResolvedTicket.column``), a note has no column, and an
    unresolved anything has nothing to report. Present because KAN-567's pill renders
    ``KAN-501 · in_progress · "…"`` and the alternative is a second request per link."""


class EmbedCard(BaseModel):
    """One card in a `pandan-board` embed (KAN-1049) — enough for a read-only row, nothing more.

    Deliberately three fields, the same three `LinkRead`'s pill needs for a resolved card: `ref`,
    `title`, `column`. No `id`, no `board_id`, no `priority` or `assignee` — pandan's `CardRead`
    carries all of those, but an embed is a live *preview* of a board query inside a note, not a
    board client, and every field added here is a field `PreviewPane.svelte` has to render.

    `ref` is pandan's own `ticket_number` (`"KAN-12"`), never a kaya `NOTE-n` — a different ref
    system entirely (ADR 0008), which is why this class does not sit anywhere near `NoteRead`."""

    model_config = ConfigDict(from_attributes=True)

    ref: str
    title: str
    column: str


class BoardEmbedResponse(BaseModel):
    """`GET /api/v1/embeds/board`'s body. Always a `200`, even when pandan could not be asked —
    the same "degrade, never fail the render" contract Q26 already set for `LinkRead`
    (`resolved_ref`/`title`/`column` all going `null`), spelled here as one boolean instead of three
    nullable fields because there is no partial answer to preserve: either pandan answered with a
    card list, or it did not, and a caller cannot act differently on "pandan is down" versus "the
    caller cannot see this board" (ADR 0003, `app/integrations/board_embed.py`'s
    `BoardEmbedResult` docstring).

    `cards` is `[]` for both `unavailable=True` and a legitimately empty result — a saved view with
    no matching cards renders identically to a decoration nobody could reach on the wire, and that
    is deliberate: a caller cannot and should not act differently on either."""

    unavailable: bool
    cards: list[EmbedCard]


class LinkList(BaseModel):
    """`GET /api/v1/notes/{ref}/links`'s envelope — named, like ``NoteList``, and for PLAN
    §Implementation decisions' reason rather than a fresh one.

    ``summary`` and ``next_cursor`` are absent here exactly as they are there: the aggregate is
    attached inside ``kaya-client``'s ``render()`` (ADR 0004) and paging is nobody's card yet. The
    array is wrapped so both stay additive.
    """

    links: list[LinkRead]


class GraphNode(BaseModel):
    """One note, as a graph node — KAN-1050's `/graph`.

    Three fields, no more: what a diagram needs to draw a node and let a click navigate to it.
    ``ref`` rather than ``id`` (ADR 0008 — a note's identity is its ref, never its numeric id, and
    the frontend's ``navigate()``/``routeHref()`` already take refs, not ids). ``title`` for the
    label. ``path`` is included because a future grouping-by-folder view is the obvious next cut of
    this same graph, and it costs nothing to carry now — dropping an unused field later is free,
    inventing a second graph read to add one field is not.
    """

    model_config = ConfigDict(from_attributes=True)

    ref: str
    title: str
    path: str


class GraphEdge(BaseModel):
    """One resolved note-to-note wikilink, as the two refs it connects — KAN-1050's `/graph`.

    Both ``NOTE-n``, never ``note_link.source_note_id``/``resolved_id``'s raw integers, for the same
    reason ``LinkRead`` withholds them: those ids are internal surrogates and a graph is exactly the
    payload most tempted to publish them, since it already has one id per endpoint in hand.

    No ``target_kind``: this graph is note-to-note edges only (a `[[KAN-501]]` reference is a
    cross-repo pandan link, not an edge between two of the caller's own notes, and rendering one
    would need a call this route does not make). Every edge here is a ``NOTE`` edge by construction
    — see ``app.auth.notes_graph_edges`` — so a field that could only ever hold one value is not a
    field.
    """

    source: str
    target: str


class GraphRead(BaseModel):
    """`GET /api/v1/graph`'s envelope — every note the caller owns, and every resolved link between
    two of them.

    Bare (not a list envelope like ``NoteList``/``LinkList``) because it already carries two arrays
    and a caller renders it as one diagram, not as a page of rows — the "wrap the array" argument
    those two envelopes make does not apply when there is no bare array to distinguish it from.

    A note with no links still appears in ``nodes`` with nothing in ``edges`` pointing at it: the
    two arrays are built independently (nodes from the caller's notes, edges from the caller's
    resolved ``note_link`` rows), so an isolated note is not a special case, it is simply a node no
    edge happens to name.
    """

    nodes: list[GraphNode]
    edges: list[GraphEdge]
