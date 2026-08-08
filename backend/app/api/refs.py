"""The central ref resolver. ADR 0008, in one place, for every verb that takes an identifier.

A note has two names — ``NOTE-12`` from ``note_ref_seq``, and the integer primary key — and ADR
0008 requires **every** id-taking verb to accept either, case-insensitively, and to produce
"identical results including identical error codes". The failure that decision exists to prevent is
concrete: pandan shipped a version where ``get 999999`` exited `1` and ``get KAN-999999`` exited
`5`, so the *error code depended on the identifier form* rather than on the failure. The fix
belonged in the resolver, because a resolver covers every ref-taking verb at once, while a helper
called per call site covers only the call sites somebody remembered.

So this module is deliberately the only thing in kaya that turns a caller's string into a note, and
it is shaped so the two spellings cannot drift:

1. ``parse_note_ref`` — string in, ``NoteRef`` out, or a `400`. Pure: no session, no principal, no
   framework, so the whole grammar is pinned by the no-infrastructure test layer.
2. ``resolve_note`` — ``NoteRef`` in, ``Note | None`` out. The **only** branch on the spelling is
   which ``Select`` gets built; the fetch, the miss and the hand-off to ``authorize_note`` are one
   shared line each.
3. ``note_from_ref`` — the FastAPI dependency, so a route reads
   ``note: Annotated[Note, Depends(note_from_ref)]`` and never handles an identifier at all.

The `404` itself is not written here. It comes from ``authorize_note``, which takes a ``Note |
None`` and has never seen an identifier — which is why the two spellings are byte-identical on a
miss rather than merely same-coded.
"""

import re
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import (
    Principal,
    authorize_note,
    error_body,
    get_principal,
    note_addressed_as_id,
    note_addressed_as_ref,
)
from app.db import get_session
from app.models import NOTE_REF_PREFIX, Note

# The whole accepted grammar: an optional case-insensitive `NOTE-`, then digits, then nothing.
#
# `fullmatch` rather than `match`, which is the difference between rejecting `NOTE-12-old` and
# silently resolving it. Nothing is stripped first: a leading `#`, a wrapping `[[…]]`, surrounding
# whitespace and a trailing comma are all usage errors, and ADR 0008 §Decision is explicit that this
# is a choice — "leniency in an identifier parser buys a future ambiguity for no measured need". The
# ambiguity is not hypothetical: the day `[[NOTE-12|alias]]` becomes wikilink syntax, a parser that
# already strips brackets has to guess.
#
# `re.ASCII` is not tidiness. Without it `\d` matches every Unicode decimal digit and `int()`
# converts them, so `٣` would parse to 3 and become a second spelling of `NOTE-3` that nothing else
# in the stack — not the sequence, not a wikilink, not a URL somebody pasted — agrees with. It also
# keeps `IGNORECASE` from folding non-ASCII letters onto the prefix.
NOTE_REF_PATTERN = re.compile(
    rf"(?P<prefix>{re.escape(NOTE_REF_PREFIX)})?(?P<number>\d+)",
    re.ASCII | re.IGNORECASE,
)

# `note.id` is an `INTEGER` column (migration `0001`). A number above this is well-formed and cannot
# possibly be a row, and asking Postgres about it raises rather than returning nothing — which would
# make `99999999999` a `500` while `NOTE-99999999999` stayed a `404`. That is precisely pandan's bug
# wearing different numbers, so it is answered here, once, for every verb.
POSTGRES_INTEGER_MAX = 2**31 - 1


@dataclass(frozen=True)
class NoteRef:
    """A parsed identifier: which number, and which of a note's two names it was written as."""

    number: int
    prefixed: bool
    """True for ``NOTE-12``, false for ``12``.

    It selects a **column**, not a code path. The ref number comes from ``note_ref_seq`` and the id
    from the table's own identity column; they are allocated by the same INSERT and so usually
    agree, but nothing guarantees it, and ADR 0008 lists them as two distinct names on purpose.
    Treating a bare integer as "the ref with the prefix left off" would quietly make a note's `id` —
    which this API returns in every payload — unusable as an identifier, breaking ADR 0008's
    "anything the tool prints must be accepted back".
    """

    @property
    def canonical(self) -> str:
        """The ``NOTE-n`` spelling, however the caller wrote it. Case is normalised here so
        ``note-12`` and ``NOTE-12`` hit the same row rather than relying on a case-insensitive
        comparison in SQL, which would not use the unique index."""
        return f"{NOTE_REF_PREFIX}{self.number}"


def invalid_note_ref(raw: str) -> HTTPException:
    """The one usage error this module raises, as a value so tests can name it.

    `400` and not `404`: `404` would answer "no such note" about a string that is not a note
    reference at all, and would make a typo indistinguishable from a genuine miss. The caller needs
    to learn it mistyped, which is the whole reason ADR 0008 pins `#NOTE-12` with a test rather than
    quietly accepting it.

    The offending string is echoed back — it is the caller's own path segment, not a credential, and
    an error that will not say *what* it rejected costs a round trip to find out.
    """
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=error_body(
            "invalid_note_ref",
            f"not a note reference: {raw!r}. Use NOTE-12, note-12 or 12.",
            ref=raw,
        ),
    )


def parse_note_ref(raw: str) -> NoteRef:
    """``NOTE-12`` / ``note-12`` / ``12`` → a ``NoteRef``. Anything else raises."""
    matched = NOTE_REF_PATTERN.fullmatch(raw)
    if matched is None:
        raise invalid_note_ref(raw)

    return NoteRef(
        number=int(matched.group("number")),
        prefixed=matched.group("prefix") is not None,
    )


def resolve_note(session: Session, principal: Principal, raw: str) -> Note:
    """A caller's string → the note it may see, or the same refusal for either spelling.

    Read the branch below carefully, because its narrowness is the point. It chooses a statement and
    stops. There is one ``scalars`` call, one ``authorize_note`` call and one ``return``, so a `404`
    is produced by code that cannot know which spelling it came from — the structural version of
    ADR 0008's "identical results including identical error codes", rather than two paths that a
    test has to keep in agreement.
    """
    ref = parse_note_ref(raw)

    if ref.prefixed:
        statement = note_addressed_as_ref(ref.canonical)
    elif ref.number > POSTGRES_INTEGER_MAX:
        # Not an error and not a special case of one: a number the id column cannot hold names no
        # row, exactly like `NOTE-99999999999` names no row. Answered without a query so the two
        # spellings agree, instead of one of them reaching psycopg and becoming a `500`.
        return authorize_note(principal, None)
    else:
        statement = note_addressed_as_id(ref.number)

    return authorize_note(principal, session.scalars(statement).one_or_none())


def note_from_ref(
    ref: str,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> Note:
    """The dependency every ref-taking route uses, and the reason none of them parse anything.

    V5's `/links` and `/backlinks` (KAN-566) get ADR 0008's guarantee by depending on this, without
    a line of ref handling of their own. That is what "resolve centrally" buys, and it is why this
    takes a bare ``ref: str`` path parameter rather than anything route-specific.
    """
    return resolve_note(session, principal, ref)


NoteFromRef = Annotated[Note, Depends(note_from_ref)]
