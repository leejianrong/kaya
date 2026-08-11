"""``?q=`` — what a search *term* is, and what it is not (KAN-558, SLICES §V4).

One decision lives here, and it is the one the card said to make rather than let happen: ``?q=``
absent, ``?q=`` present-but-empty and ``?q=%20%20`` are three different requests, and they need a
rule instead of whatever ``strip()`` and truthiness happen to produce.

**The rule.** An absent ``q`` is not a search — the route lists everything, exactly as it did before
this card. A ``q`` that is *present* is a search, and a search with no non-whitespace character in
it is refused: `400` ``empty_search_query``. So "did the caller ask to search?" is answered by the
parameter's presence, and "is this a usable search?" by its content, and neither question is
answered by guessing at the other.

**Why a refusal rather than pandan's no-op.** Pandan treats an empty or whitespace-only ``q`` as
absent, which is the right call *there* because ``q`` arrived on a shipped, filter-laden list
endpoint and had to stay backwards compatible with clients that always send the parameter. Kaya has
no such client — ``--q`` (KAN-559) and the SPA's search box do not exist yet — so this is the one
moment the choice is free, and the two candidates are not equally good:

- ``kaya note list --q "$TERM"`` with ``TERM`` unset. Under the no-op rule that returns the whole
  corpus and looks exactly like a search that matched everything. Under this rule it is exit `2`
  (ADR 0005's table maps `400` → `2`, and ``invalid_note_ref`` is deliberately not keyed on its code
  string, so this refusal inherits that number without anything in ``kaya-cli`` changing).
- A search box that has been cleared. It must send no ``q`` at all rather than ``q=``, which is one
  branch in the SPA and makes it state which of the two requests it means.

The direction is ADR 0008's, one layer over: leniency in a parser buys a future ambiguity for no
measured need, and ``#NOTE-12`` is a `400` for the same reason.

**The refusal is on the input, not on the parse.** ``websearch_to_tsquery('english', 'the')`` and
``websearch_to_tsquery('english', '&|!()')`` both return the *empty* tsquery, and ``anything @@
''::tsquery`` is false, so both searches come back as zero notes with a `200`. That is deliberate
and it is not the same case as an empty ``q``: the caller typed something, so they made a search,
and zero results is the honest answer to it. Refusing an empty tsquery instead would make the status
code a function of the dictionary — ``the`` would be a `400` under ``english`` and a hit under a
configuration with no stopword list — so the HTTP contract would depend on ``app/models/note.py``'s
choice of text-search configuration. It does not.

**One term, one value.** ``search_term`` returns the *stripped* string, and that same string is what
reaches ``notes_matching``. The alternative — check ``q.strip()`` and query with ``q`` — is how the
two code paths the card warned about come into being, because the thing that was validated is then
not the thing that ran.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Query, status

from app.auth import error_body


def empty_search_query() -> HTTPException:
    """``?q=`` with nothing in it, as a value so tests can name it.

    No extra attached, unlike ``invalid_note_ref``'s ``ref``: the only thing the caller sent is
    whitespace or nothing at all, so echoing it back tells them nothing the message does not — and
    ``tests/unit/test_error_extras_stay_addressable.py`` is a reminder that an extra is a decision
    rather than decoration.
    """
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=error_body(
            "empty_search_query",
            "q was empty: pass a term to search for, or omit q entirely to list every note",
        ),
    )


def search_term(
    q: Annotated[
        str | None,
        Query(
            description=(
                "Full-text search over title and body. Bare words are AND-ed, "
                '"a phrase" is a phrase and -word excludes. Omit to list every note; '
                "present-but-empty is a 400."
            )
        ),
    ] = None,
) -> str | None:
    """``None`` for "no search", or the term to search for. Never an empty string.

    A dependency rather than a helper the route remembers to call, so ``list_notes`` is handed a
    value that has already been decided about and has no raw ``q`` in scope to use by mistake — the
    same shape, and the same reason, as ``NoteFromRef`` in ``app/api/refs.py``.
    """
    if q is None:
        return None

    term = q.strip()
    if not term:
        raise empty_search_query()

    return term


SearchTerm = Annotated[str | None, Depends(search_term)]
