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
the wire.

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

from fastapi import HTTPException, status
from sqlalchemy import Select, select

from app.auth.principal import Principal
from app.auth.resolver import error_body
from app.models import Note


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
