"""``PUT /api/v1/notes/{ref}`` — create a note at a specific, currently-free ref.

R12/KAN-1061's import path is the one reason this exists: re-importing a note whose exported front
matter names a ``kaya_ref`` nobody currently holds should get that ref back, not a fresh one — ADR
0008 §Decision says so explicitly ("an import re-uses it when free"), and a plain
``POST /api/v1/notes`` cannot honour it: ``NoteCreate`` is ``extra="forbid"`` with no ``ref`` field
at all, and ``note.ref``'s ``server_default`` is Postgres's own ``nextval('note_ref_seq')`` — there
is no request the existing route accepts that would hand a *caller-chosen* ref back to the caller.
Skipping this was this feature's first cut (KAN-1060..1063's original PR), on the theory that it
needed a new backend route this round's scope had ruled out. It doesn't need a new *table*, and the
route it needs is four lines longer than ``create_note`` — see below.

**Every existing wire contract stays exactly as it was.** ``NoteCreate`` is unchanged, still refuses
an explicit ``ref``, still the body every *other* caller of ``POST /api/v1/notes`` sees. This route
is reached by ``ref`` living in the **URL**, not the body — the same shape ``PATCH``/``DELETE``
already use — so it is additive: a second door onto note creation, for the one caller (kaya-client's
import path) that has a specific number in mind, rather than a widening of the door every other
caller already walks through.

### Why this is safe under a concurrent ordinary `create_note`

Two writers can genuinely collide: an import claiming a free ``NOTE-42`` at the same moment an
unrelated ``POST /api/v1/notes`` calls ``nextval('note_ref_seq')`` and also gets ``42`` (this
happens only when ``42`` is *ahead* of the sequence's current position — the common "reclaim a
ref whose note was deleted" case can never collide this way, because a ref that once existed can
only be **behind** the sequence, never ahead of it; nothing here reasons about which case it is in,
because it does not need to).

``note.ref`` already carries ``unique=True`` (migration ``0001``), so Postgres itself is the
referee: **exactly one** of two INSERTs naming the same ``ref`` can ever land, whichever the
database's own lock ordering decides, and the loser fails cleanly rather than either winning
silently or corrupting a row. This route reaches that guarantee the same way
``app/auth/mirror.py``'s ``SqlAlchemyPrincipalMirror.ensure`` does for the exact same reason (two
first-ever requests racing to mirror one user) — ``INSERT … ON CONFLICT DO NOTHING``, translated
here to a `409` rather than mirror.py's silent no-op, because "somebody already has this ref" is
this route's whole subject rather than an uninteresting race to shrug off. **What this route does
not do** is catch ``IntegrityError`` from the *ordinary* ``create_note`` route — the sequence-only
path was never touching a caller-supplied value before this card and does not need to start
defending against one now. If an ordinary create's ``nextval()`` ever does land on a number an
import claimed moments earlier, that write raises a plain, uncaught `500` — correct rather than
comfortable: no duplicate ref is possible (the unique index forbids it structurally), the loser
just has to retry, and `backend/tests/integration/test_note_claim_api.py` proves the race produces
exactly that outcome rather than two notes sharing one ref.

### The sequence bump, and why it is best-effort rather than load-bearing

After a successful claim, the sequence is nudged forward past the claimed number — see
``_advance_sequence_past`` — so a *future* ordinary create is less likely to reach for a number this
route just gave out. It is explicitly **not** the thing that keeps two writers from duplicating a
ref; the unique index above is that thing, unconditionally, whether or not the bump below ever runs
or races against a concurrent bump from a second claim. Skipping it, or losing a race inside it,
costs at most a wasted gap in the sequence (already a designed-for outcome — see
`app/models/note.py`'s ``NOTE_REF_SEQUENCE`` comment and
``test_a_rolled_back_insert_never_lends_its_ref_to_the_next_writer``) or a rarer future collision
that the unique index still turns into a clean `500` rather than corruption. That asymmetry — an
approximate optimisation sitting on top of an exact guarantee — is what makes the bump safe to keep
simple.

The bump only ever moves the sequence **forward**: ``GREATEST(claimed_number, current_last_value)``,
never backward, because moving it backward would let a later ``nextval()`` reissue a number some
other note already holds — the one true corruption risk in this whole feature, and the reason the
comparison exists at all rather than an unconditional ``setval``.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.api.refs import invalid_note_ref, parse_note_ref
from app.api.schemas import NoteCreate, NoteRead
from app.auth import Principal, error_body, get_principal
from app.db import get_session
from app.models import NOTE_REF_SEQUENCE_NAME, Note
from app.note_links import reconcile_note_links, resolve_pending_note_links
from app.note_versions import cut_version

router = APIRouter(prefix="/api/v1", tags=["notes"])

CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
DbSession = Annotated[Session, Depends(get_session)]


def ref_taken(ref: str) -> HTTPException:
    """The `409` this route raises, as a value so tests can name it — the same shape as
    ``refs.invalid_note_ref`` and ``concurrency.note_conflict``.

    A distinct code from ``note_conflict``'s ``note_conflict`` (ADR 0009's optimistic-concurrency
    `409`): that one means "this note changed since you read it"; this one means "no note changed —
    somebody already has the ref you asked to claim", which is a different fact a caller might want
    to branch on differently (ADR 0009's `409` is worth retrying with a fresh read; this one never
    is, for the same ``ref`` — the caller's fallback is to stop asking for that ref, not to retry).
    """
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=error_body(
            "ref_taken",
            f"{ref} already names a note. Claiming a specific ref only succeeds when it is free.",
            ref=ref,
        ),
    )


def _advance_sequence_past(session: Session, number: int) -> None:
    """Nudge ``note_ref_seq`` forward so it never hands out ``number`` again. See the module
    docstring for why this is best-effort rather than the thing that prevents a duplicate ref.

    One statement, so the read of ``last_value`` and the ``setval`` sit as close together as SQL
    allows — not a hard atomicity guarantee (see the module docstring), but the narrowest window
    achievable without inventing a lock this module has no other reason to take.
    """
    session.execute(
        text(
            f"SELECT setval('{NOTE_REF_SEQUENCE_NAME}', "
            f"GREATEST(:number, (SELECT last_value FROM {NOTE_REF_SEQUENCE_NAME})), true)"
        ),
        {"number": number},
    )


@router.put(
    "/notes/{ref}",
    status_code=status.HTTP_201_CREATED,
    summary="Create a note at a specific, currently-free ref",
)
def claim_note(
    ref: str,
    payload: NoteCreate,
    principal: CurrentPrincipal,
    session: DbSession,
    response: Response,
) -> NoteRead:
    """Create a note whose ref is exactly ``ref``, or refuse if anyone already holds it.

    ``ref`` must be the canonical ``NOTE-n`` spelling — a bare integer is refused with the same
    `400` an unparsable ref gets, deliberately narrower than every *other* ref-taking route. Those
    routes accept a bare integer as an alternate spelling of a ref that already exists (ADR 0008);
    here there is no existing row for a bare integer to be a second spelling *of*, and letting one
    through would raise the question of whether it means "claim ``NOTE-n``" or something about the
    ``id`` column, which this route has no reason to answer either way. kaya-client's caller — an
    import reading a ``kaya_ref: NOTE-…`` line back out of a file — never has any other spelling to
    offer, so this restriction costs the real caller nothing.

    ``payload`` is a plain ``NoteCreate`` — the same schema, the same validation, the same absence
    of a ``ref`` field, as the ordinary ``POST /api/v1/notes``. Title, body and path arrive exactly
    as they do there; only the ref's *origin* differs, and it differs by living in the URL.
    """
    parsed = parse_note_ref(ref)
    if not parsed.prefixed:
        raise invalid_note_ref(ref)
    canonical = parsed.canonical

    claim = (
        insert(Note)
        .values(
            owner_id=principal.id,
            ref=canonical,
            title=payload.title,
            body=payload.body,
            path=payload.path,
        )
        .on_conflict_do_nothing(index_elements=[Note.ref])
        .returning(Note.id)
    )
    claimed_id = session.execute(claim).scalar_one_or_none()
    if claimed_id is None:
        raise ref_taken(canonical)

    _advance_sequence_past(session, parsed.number)

    # From here on this is `create_note`'s own tail, unchanged: the same reconciliation, the same
    # version cut, in the same transaction, for the same reasons — see `app/api/notes.py`.
    note = session.get(Note, claimed_id)
    assert note is not None  # the INSERT above just returned this id in this same transaction
    reconcile_note_links(session, note)
    resolve_pending_note_links(session, note)
    cut_version(session, note)
    session.commit()
    session.refresh(note)

    response.headers["Location"] = f"{router.prefix}/notes/{note.ref}"
    return NoteRead.of(note)
