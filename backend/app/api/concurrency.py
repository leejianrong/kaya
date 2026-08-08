"""ADR 0009's precondition: one comparison, and the `409` that carries both versions.

This is the deliberate deviation from pandan ADR 0007, and the reason for it is the payload rather
than the philosophy. Last-write-wins is a sound trade for a card, where the loser can see at a
glance what changed and redo it. A note body is long-form prose: under pure LWW two writers on a
3,000-word runbook means one of them loses an arbitrary amount of work **silently** — no error, no
notification, no copy of what was overwritten — and typically finds out days later, if at all.

So the rule is small and the payload is not:

- The write carries the ``updated_at`` it read. If the stored value differs, nothing is written and
  the caller gets a `409`.
- The `409` body carries **both** versions in full, because "your write was refused" is not actually
  actionable. What the caller needs is what it tried to write and what is there now, side by side.
- A write that omits the precondition is a plain overwrite. That is specified, not a gap.

It lives in its own module for the same reason identity lives in ``refs.py``: ``notes.py`` is
wiring, and a rule that has to hold for every writer should not be four lines inside one route
where the next writer copies three of them.
"""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.api.schemas import NoteRead, NoteUpdate
from app.auth import error_body
from app.models import Note


def attempted_version(note: Note, payload: NoteUpdate) -> NoteRead:
    """The note as the caller meant it to end up: what is stored, with the caller's changes on top.

    A full note rather than the changed fields alone, because the consumer is a diff. KAN-556
    renders "keep mine / keep theirs / side-by-side" straight out of this payload, and a
    side-by-side of two prose bodies needs both bodies whole — a client cannot reconstruct one from
    a patch it no longer has.

    Two details that look like bugs and are not:

    - The fields the caller *didn't* send are the **stored** ones, not the ones the caller read.
      Kaya never saw the caller's base version, only the token naming it. That reads correctly
      anyway: those are the fields this write was not changing, so showing them identical on both
      sides is exactly right, and the diff highlights only what the caller actually touched.
    - ``updated_at`` is the precondition, i.e. the version the caller was editing from. It is the
      one field where "what I attempted" and "what is stored" *must* differ, and printing a
      would-be-new stamp there would be inventing a version that never existed.
    """
    return NoteRead.of(note).model_copy(
        update={**payload.changes(), "updated_at": payload.if_updated_at}
    )


def note_conflict(note: Note, payload: NoteUpdate) -> HTTPException:
    """The `409`, as a value so tests can name it — the same shape as ``refs.invalid_note_ref``.

    ``error_body`` stays the single builder (KAN-536) and the two versions ride along as
    ``**extra``, so this is the one error shape on the wire rather than a second one for conflicts.
    A client that only knows ``error.code`` still reads it; a client that wants to resolve the
    conflict reads two more keys.

    ``attempted`` and ``stored``, not "mine" and "theirs": those words are the *SPA's*, and they are
    only true from the rejected caller's seat. The same body goes to the CLI (KAN-542) and to an MCP
    tool (V6), where "mine" names nobody. The mapping for KAN-556's banner is
    ``attempted`` → "keep mine", ``stored`` → "keep theirs" — and "keep mine" is then this same
    `PATCH` again with ``body`` from ``attempted`` and ``if_updated_at`` from ``stored``, which is
    the whole reason both objects carry their own ``updated_at``.

    The message names both timestamps because ADR 0005 wants a refusal renderable as one line, and
    "the note changed" without saying *when* leaves a scripted caller nothing to log.
    """
    stored = NoteRead.of(note)

    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=error_body(
            "note_conflict",
            f"{note.ref} has changed since you read it: stored {stored.updated_at.isoformat()}, "
            f"precondition {payload.if_updated_at.isoformat() if payload.if_updated_at else None}. "
            "Nothing was written.",
            attempted=attempted_version(note, payload),
            stored=stored,
        ),
    )


def enforce_precondition(session: Session, note: Note, payload: NoteUpdate) -> None:
    """Raise the `409` if this write is guarded and its precondition no longer holds.

    **The re-read with a row lock is load-bearing, not caution.** ``note`` was SELECTed earlier in
    this same transaction by the ref resolver, and under READ COMMITTED a writer that committed
    since then is invisible to it. Without the refresh, two writers that both read before either
    committed would both pass the check and the second would overwrite the first — the exact silent
    loss this module exists to prevent, surviving inside the guard against it. ``with_for_update``
    then holds the row until this request's transaction ends, so a writer arriving mid-check waits
    and re-reads rather than racing between the comparison and the UPDATE.

    It is taken **only on the guarded path**. An unguarded write is specified to be a plain
    overwrite, so locking for it would buy nothing and serialise the callers who opted out.

    The comparison is ``!=`` on two aware datetimes, which compares instants: a client that echoes
    the token back in a different offset still matches, and one that is a microsecond out does not.
    Microseconds are the whole precision budget here — see ``NoteRead.updated_at``.
    """
    if not payload.guards_the_body():
        return

    session.refresh(note, with_for_update=True)

    if note.updated_at != payload.if_updated_at:
        raise note_conflict(note, payload)
