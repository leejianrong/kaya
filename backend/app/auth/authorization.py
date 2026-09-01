"""Step 5 of ADR 0002's resolver: which note a principal may touch, which ones it may see, and —
since KAN-536 — the two statements that fetch a single note by either of its names.

Three kinds of function, and the difference between them is the whole design.

``authorize_note`` decides about **one** note that has already been fetched, and it deliberately
cannot scope the fetch. The `403` requires knowing the note exists, so a query filtered on the
owner is exactly the wrong shape here: it would come back empty for somebody else's note and the
caller would be told `404`, which is a different promise from the one ADR 0002 §"The resolver",
PLAN §Authorization and SLICES §V1 all make.

``notes_owned_by`` decides about **many**, and does the opposite. The scoping is a ``WHERE`` on the
statement, so another user's note is never loaded in the first place. SLICES §V1 is specific that
`GET /api/v1/notes` must *omit* another user's note "rather than returning an empty list for a
scoped query", and a post-filter over rows Postgres already returned reaches the same JSON by
accident rather than by construction — it would still page wrongly (ten rows fetched, three of them
someone else's, seven returned for a page of ten) and it would still have pulled the prose across
the wire. ``notes_matching`` (KAN-558) is the first thing to take that composition up — a search is
where an unscoped list query looks most convincing, and it is in this module rather than in
``app/api/`` so that "another user's matching note never appears" is that same ``WHERE``.
``notes_linking_to`` (KAN-566) is the second, and it is the case
``tests/unit/test_no_unscoped_note_query.py``'s docstring named in advance: a backlinks query is a
list endpoint that reads most naturally *from the other table*, and started that way it has no
owner column to filter on at all.

``note_addressed_as_ref`` / ``note_addressed_as_id`` decide about **neither**. They are the two
unscoped single-row fetches ADR 0008 needs, one per spelling of a note's name, and they are as
deliberately unscoped as ``session.get(Note, …)`` is: same reason, same `403`. They live in *this*
module rather than beside the ref resolver in ``app/api/`` because
``tests/unit/test_no_unscoped_note_query.py`` requires ``Note`` to reach a query builder here and
nowhere else under ``app/``, and that rule is worth more than the tidiness of moving two lines.
Fetching by a non-primary-key unique column is the one legitimate read `session.get` cannot express,
so the choice was between this and evading the guard. See the note above each one.

``authorize_note`` knows *nothing* about how the note was addressed. It takes a ``Note`` or
``None``, never an identifier, so a missing note gets the same `404` whether it was asked for as
``NOTE-9999`` or ``9999`` — ADR 0008's requirement, met structurally, because there is nothing here
that could differ between the two forms. The central ref resolver that turns either spelling into
that ``Note | None`` is ``app.api.refs`` (KAN-536), and this is the seam it hands its result to.

Nothing here touches FastAPI's dependency machinery, for the same reason ``resolver.py`` doesn't:
the whole HTTP contract below is then assertable by the no-infrastructure test layer.
"""

import uuid
from collections.abc import Iterable

from fastapi import HTTPException, status
from sqlalchemy import Select, func, select

from app.auth.principal import Principal
from app.auth.resolver import error_body
from app.models import Note
from app.models.note_link import TARGET_KIND_NOTE, NoteLink


def note_addressed_as_ref(ref: str) -> Select[tuple[Note]]:
    """One note by its ``NOTE-n`` ref. **Unscoped, on purpose** — the result goes to
    ``authorize_note``, which cannot answer `403` for somebody else's note if the fetch never found
    it (see the module docstring, and ``test_no_unscoped_note_query``'s carve-out for
    ``session.get``).

    ``ref`` is unique, so this returns at most one row. It is *not* an entry point for a list:
    adding an ``.order_by()`` and dropping the ``where`` turns it into the exact leak
    ``notes_owned_by`` exists to prevent. If you want many notes, start from ``notes_owned_by``.
    """
    return select(Note).where(Note.ref == ref)


def note_addressed_as_id(note_id: int) -> Select[tuple[Note]]:
    """The same fetch, by the other name (ADR 0008: every id-taking verb accepts either form).

    ``session.get(Note, note_id)`` would do this in one call and is explicitly sanctioned. It is
    deliberately *not* used, because then the two spellings would run down two different code paths
    — one through the ORM identity map, one through a statement — and "identical results including
    identical error codes" would rest on two implementations agreeing rather than on there being
    one. Returning a ``Select`` here means ``app.api.refs`` picks a statement and everything after
    that point is literally the same line of code for both forms.
    """
    return select(Note).where(Note.id == note_id)


def authorize_note(principal: Principal, note: Note | None) -> Note:
    """The whole authorization contract for a single note, with none of FastAPI's plumbing.

    Sibling of ``principal_from_bearer``: an ordinary function over ordinary objects. It **returns
    the note it was given**, so a call site reads ``note = authorize_note(principal, found)`` and
    comes away with a ``Note`` rather than a ``Note | None``. That is the point of the return value
    — the check sits on the path to the value instead of beside it, and a route that forgot to call
    it is left holding an optional it has to explain.
    """
    if note is None:
        # No identifier in the message, and none available to put there. That is what keeps
        # `NOTE-9999` and `9999` byte-identical rather than merely same-coded (ADR 0008).
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_body("note_not_found", "no such note"),
        )

    if note.owner_id != principal.id:
        # `403` rather than `404`, which tells the caller the note exists. That is a decision, not
        # an oversight: the card, ADR 0002 §"The resolver", PLAN §Authorization and SLICES §V1's
        # end-to-end list all name `403` explicitly. The existence bit is cheap to give up here —
        # refs come from one global sequence and already leak a rough note count across all users
        # (ADR 0008 §Consequences) — and in exchange someone who mistyped a ref learns what actually
        # happened instead of hunting a note that is sitting right there. Per-note sharing (Q8) is
        # the change that would make this line worth revisiting; hardening it to a blanket `404`
        # unilaterally is not.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error_body("note_forbidden", "this note belongs to another user"),
        )

    return note


def notes_owned_by(principal: Principal) -> Select[tuple[Note]]:
    """Every list of notes starts here: ``WHERE owner_id = :caller``, before anything else.

    Handed back as a ``Select`` rather than as rows so a route composes onto it — ``.where()`` for a
    search term, ``.order_by()``, ``.limit()`` for a page — and cannot lose the scoping while doing
    so, because there is no clause you can add to a statement that removes one already on it. The
    tempting alternative, a helper that runs the query and returns a list, forces every future
    filter either into this signature or into a Python loop over rows that were fetched anyway.

    ``tests/unit/test_no_unscoped_note_query.py`` holds the other half of the guarantee: ``Note``
    reaches a ``select()`` in this module and nowhere else under ``app/``, so an unscoped list query
    fails the suite rather than depending on a reviewer noticing.
    """
    return select(Note).where(Note.owner_id == principal.id)


SEARCH_CONFIG = "english"
"""The text-search configuration the *query* is parsed with, and it has to be the one the **stored**
vector was built with (``app/models/note.py``'s ``SEARCH_VECTOR_EXPRESSION``, migration ``0002``).

A mismatch is the quietest failure in this whole card: parse the query as ``simple`` against an
``english`` vector and every exact word still matches, so a search box looks like it works, while
stemming is silently gone — ``runbooks`` stops finding ``runbook`` and nothing raises. So the two
literals are held together by ``tests/unit/test_note_search_query.py``, which asserts this string
appears in the model's expression rather than trusting two files to be edited together.

Left as a **bound parameter** rather than an inlined ``'english'`` literal, which was measured
rather than assumed: ``regconfig`` has no implicit cast from ``text``, so the obvious worry is that
the driver sends a typed string and Postgres cannot resolve the overload. Against Postgres 17 with
psycopg 3, both spellings return ``'foo' & 'bar'`` for ``foo bar`` (KAN-558's experiment). It is a
constant in this file either way, so nothing user-supplied is ever near the position."""


def notes_matching(principal: Principal, term: str) -> Select[tuple[Note]]:
    """The caller's notes matching ``term``, best match first, in a **deterministic** order.

    KAN-558, SLICES §V4. Composed onto ``notes_owned_by``, so "another user's matching note must
    never appear" is the ``WHERE owner_id = :caller`` that is already on the statement — a clause
    cannot be composed away, and there is no point at which a row of somebody else's prose is
    fetched and then dropped.

    **``websearch_to_tsquery`` rather than the other two, because the input is a human's.** Measured
    against Postgres 17 on this card: ``to_tsquery('english', '&|!()')`` and ``to_tsquery('english',
    'foo &')`` both **raise** ``SyntaxError``, which reaches a caller as a `500` — a search box
    cannot use a parser that fails on the characters people type. ``plainto_tsquery`` never raises
    but AND-s bare words and nothing else, so ``"reading list"`` as a phrase and ``reading -list``
    as an exclusion are both unsayable. ``websearch_to_tsquery`` raised on none of the eleven
    hostile inputs tried (empty, whitespace, a stopword, ``&|!()``, ``foo &``, an unbalanced quote,
    5,000 characters, ``%``/``_``, a quoted phrase, a negation) and supports the two grammars a
    person expects. Where it has nothing to work with it returns the empty tsquery, and ``anything
    @@ ''::tsquery`` is false — so a stopword-only or punctuation-only search is *zero notes* rather
    than an error or, worse, the whole corpus.

    **The term is a bound parameter, never rendered into SQL.** That is what makes ``&|!()``, ``%``,
    ``_`` and a quote character inert: they reach Postgres as data, and the only thing that assigns
    them meaning is the tsquery grammar. ``%`` and ``_`` in particular matter because a ``LIKE``
    implementation of this feature would have made them wildcards, so a test pins that they are not
    (``tests/unit/test_note_search_query.py``).

    **``.bool_op("@@")`` rather than ``.match()``**, which the postgresql dialect renders as
    ``plainto_tsquery`` with no way to reach the tsquery it built. This needs the *same* tsquery in
    two places — the predicate and the rank — and building it once here is what keeps them from
    drifting into a query that ranks by something other than what it filtered on.

    **The tie-break is ``note.id``, and it is inside this expression on purpose.** ``ts_rank`` reads
    the A/B weights out of the stored vector (KAN-557), so a title hit outranks a body hit for free
    — but equal ranks are *common* rather than exotic: on kaya's own ten-note corpus,
    ``plainto_tsquery('english','reading list')`` scores "A reading list" and "Reading list" at
    0.9910 each. Without a second key Postgres may return those two in either order on identical
    queries, which is exactly what SLICES §V4's "deterministic order" forbids. ``updated_at`` cannot
    serve: ``now()`` is transaction start time (``app/models/note.py``), so two notes written in one
    transaction share a stamp and the tie merely moves. ``id`` is unique, immutable and never reused
    (ADR 0008), so it is the only column that can promise it. It sits in the same ``order_by`` as
    the rank so nobody can add relevance ranking without the tie-break travelling with it.

    ``DESC`` on the tie-break, where pandan's equivalent uses ascending ``id``: kaya's unfiltered
    list is ``updated_at DESC, id DESC`` and pandan's is ``updated_at, id`` ascending, so copying
    its *direction* rather than its *consistency* would leave this repository with two houses.
    Newest first, at every level, in both orders.
    """
    tsquery = func.websearch_to_tsquery(SEARCH_CONFIG, term)
    return (
        notes_owned_by(principal)
        .where(Note.search_vector.bool_op("@@")(tsquery))
        .order_by(func.ts_rank(Note.search_vector, tsquery).desc(), Note.id.desc())
    )


def notes_titled(owner_id: uuid.UUID, titles: Iterable[str]) -> Select[tuple[str, int]]:
    """``owner_id``'s own notes, projected to ``(title, id)`` and filtered to `titles` — KAN-563's
    forward-resolution lookup. ``app/note_links.py``'s ``_notes_by_title`` calls this to find out
    which of a save's brand-new ``[[Some Title]]`` links already name a note that exists, so that
    module never has to build its own ``select(Note, ...)`` and trip this file's own guard.

    Keyed on a raw ``owner_id`` rather than on a ``Principal`` like ``notes_owned_by`` is: the
    caller here is reconciling *some* note's links, and by the time that runs the note has already
    passed `authorize_note` (or was just created for the current principal), so its `owner_id` is
    always the request's own principal — but the value in hand is the column, not the object, and
    manufacturing a `Principal` just to satisfy a different function's signature would be the
    tail wagging the dog. The scoping is the same clause either way, and it stays in this module
    either way.
    """
    return select(Note.title, Note.id).where(Note.owner_id == owner_id, Note.title.in_(titles))


def note_ids_owned_by(owner_id: uuid.UUID) -> Select[tuple[int]]:
    """``owner_id``'s own note ids, and nothing else about them — KAN-563's backward-resolution
    pass. ``app/note_links.py``'s ``resolve_pending_note_links`` uses this as a subquery, so that a
    title landing on one owner's note can only ever resolve a ``note_link`` row whose *source* note
    belongs to that same owner: a resolution crossing an owner boundary would let one person's save
    reveal, indirectly, that another person has a note by some particular title.
    """
    return select(Note.id).where(Note.owner_id == owner_id)


def notes_linking_to(principal: Principal, note_id: int) -> Select[tuple[Note]]:
    """The caller's own notes whose body links to note ``note_id`` — KAN-566's `/backlinks`.

    Composed onto ``notes_owned_by``, so "another user's note never appears in my backlinks" is the
    ``WHERE owner_id = :caller`` already on the statement. That clause is doing more work here than
    it does for a plain list: a `note_link` row carries no owner of its own (see
    ``app/models/note_link.py``), so the *only* thing scoping this query is the join to a table that
    does. A backlinks query written the obvious way — start from ``note_link``, collect
    ``source_note_id``, fetch those notes — reaches the same JSON for the only user on a developer's
    machine and tells everyone else who links to their notes.

    It lives in this module for the reason ``tests/unit/test_no_unscoped_note_query.py`` gives, and
    it is the case that file's own docstring predicted in as many words: "a second list endpoint
    (search, backlinks, a folder tree) that copies the first and skips the one clause that
    mattered".

    **The match key is ``resolved_id``, never ``target_ref``, and that is the whole of SLICES §V5's
    "renaming a note leaves existing backlinks to it intact".** ``target_ref`` holds the title *as
    it was typed* in the linking note's body (``app/wikilinks.py``'s ``NoteTitleLink.title``, "never
    case-folded"); ``resolved_id`` holds the id KAN-563 recorded when the edge first found its
    target, and an id survives a rename by construction (ADR 0008: identity is never the title).
    Keyed on the title string this query would return a note's backlinks right up until somebody
    renamed it and then return none — the exact failure Q19 recorded the id *for*, arriving at the
    one layer that reads it back.

    **An edge whose ``resolved_id`` is still ``NULL`` is deliberately not a backlink to anything.**
    It is a link to a *title*, and a title is not a note until something resolves it —
    ``app/note_links.py``'s ``resolve_pending_note_links`` is the thing that does, on create and on
    rename, so "a link written before its target existed" becomes a backlink the moment the target
    lands rather than by being guessed at here. Matching an unresolved edge against
    ``Note.title`` as a fallback would reintroduce the rename bug through the back door: the
    fallback would fire for exactly the rows the id was recorded to protect.

    **The ``target_kind`` filter is not redundant, even though it is unreachable today.**
    ``resolved_id`` is not a ``ForeignKey`` precisely because which table it references depends on
    ``target_kind`` (``app/models/note_link.py``), so an id is only meaningful *within* a kind.
    Nothing writes a KAN-kind ``resolved_id`` at the moment — KAN-564 resolves per caller, per TTL,
    and `app/api/links.py` says why that must not be persisted — but the day something does, a card
    whose pandan id collides with this note's id would otherwise arrive as a backlink from a note
    that never mentioned it. Two columns, one namespace each.

    ``updated_at DESC, id DESC``: the same order and the same tie-break as the unfiltered list in
    ``app/api/notes.py``, for the same reason (``now()`` is transaction start time, so two notes
    written in one transaction share a stamp). A relevance order would be meaningless here — nothing
    was searched for — so this is the list order, not ``notes_matching``'s.
    """
    return (
        notes_owned_by(principal)
        .join(NoteLink, NoteLink.source_note_id == Note.id)
        .where(NoteLink.target_kind == TARGET_KIND_NOTE, NoteLink.resolved_id == note_id)
        .order_by(Note.updated_at.desc(), Note.id.desc())
    )


def notes_graph_edges(principal: Principal) -> Select[tuple[int, int]]:
    """Every resolved note-to-note wikilink among **all** of the caller's own notes, as
    ``(source_note_id, resolved_id)`` pairs — KAN-1050's `/graph`.

    ``notes_linking_to``'s sibling rather than a copy of it: same join, same two-column filter, but
    with the single-note ``resolved_id == note_id`` clause dropped, because a graph needs every edge
    at once rather than the edges pointing at one note. Composed onto ``notes_owned_by`` for the
    identical reason that function is: ``note_link`` has no owner column of its own, so the join to
    an owner-scoped ``note`` is the only thing that keeps one caller's edges out of another's graph.

    **``target_kind == TARGET_KIND_NOTE``, for the reason ``notes_linking_to`` gives.** This is the
    *note* graph (KAN-1050's scope, decided up front) — a `[[KAN-501]]` or `[[EPIC-3]]` edge is a
    cross-repo pandan reference, not an edge between two of the caller's own notes, and rendering
    one as a graph node would need a pandan call this route does not make (ADR 0003).

    **``resolved_id IS NOT NULL``, for the reason CLAUDE.md states in as many words: "a backlink is
    found by resolved_id, never by title. An edge with resolved_id IS NULL is a link to a title, not
    yet a note."** A `[[Some Future Note]]` edge that has not resolved has no target note to draw a
    line to, so it is excluded here rather than arriving at the route as a dangling id.

    ``with_only_columns`` narrows the projection to the two ids the route actually needs — the
    caller only ever has that one owner-scoped set of notes to translate an id against, so returning
    full ``Note`` rows here would be fetched and then thrown away. The ``WHERE``/``FROM`` this
    composes onto are unaffected by narrowing the columns clause, which is what keeps the owner
    scoping (and rule 3's ``source_note_id`` constraint) intact for the sweep in
    ``tests/unit/test_no_unscoped_note_query.py`` to find.

    No ``ORDER BY``: the route builds a node lookup keyed on id and reads it as a dict, so an edge's
    position in this result carries no meaning of its own. The **nodes** list — a plain
    ``notes_owned_by`` composed with an ``order_by`` at the route, the same shape ``list_notes``
    already uses — is what supplies a deterministic order to the response.
    """
    return (
        notes_owned_by(principal)
        .join(NoteLink, NoteLink.source_note_id == Note.id)
        .where(NoteLink.target_kind == TARGET_KIND_NOTE, NoteLink.resolved_id.is_not(None))
        .with_only_columns(NoteLink.source_note_id, NoteLink.resolved_id)
    )


def notes_named_by_id(owner_id: uuid.UUID, note_ids: Iterable[int]) -> Select[tuple[int, str, str]]:
    """``owner_id``'s own notes among ``note_ids``, projected to ``(id, ref, title)`` — KAN-566's
    `/links` reading the *other* end of a resolved NOTE-kind edge.

    ``note_link.resolved_id`` is an internal id and must not reach the wire (``app/api/links.py``
    pins the payload's keys), so `/links` has to turn it into the two things a caller can act on:
    ADR 0008's ``ref``, and the target's **current** title. Current rather than stored, which is the
    visible half of the rename criterion — a link typed as ``[[Old Name]]`` after the rename shows
    ``target_ref: "Old Name"`` beside ``title: "New Name"``, so the payload says what happened
    instead of quietly disagreeing with itself.

    Owner-scoped like everything else in this module, and here that is a real filter rather than a
    formality: ``resolved_id`` is not a ``ForeignKey`` and nothing in the schema stops a row from
    naming a note somebody else owns. ``app/note_links.py`` never writes one that does — both of its
    resolution passes are scoped — but a query that only *inherits* that property from another
    module's care is one edit away from leaking a stranger's title. A row this statement declines to
    answer for renders as an unresolved link, which is also the correct answer for the case that
    genuinely happens: ``resolved_id`` pointing at a note that has since been **deleted**. Nothing
    cleans those up, because ``ondelete="CASCADE"`` covers a deleted *source* and there is no
    constraint to cover a deleted target, so a dangling id has to degrade rather than raise.

    Keyed on a raw ``owner_id`` for the same reason ``notes_titled`` is: the caller already holds
    the column, and manufacturing a ``Principal`` to satisfy a signature would be the tail wagging
    the dog.
    """
    return select(Note.id, Note.ref, Note.title).where(
        Note.owner_id == owner_id, Note.id.in_(note_ids)
    )
