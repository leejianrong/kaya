"""``attachment``: one row per uploaded file, reached only by joining through its owning note.

R14 (``docs/roadmap/BREADBOARD.md``), KAN-1067/1068/1069. Shaped like ``note_link`` on purpose
rather than inventing a new pattern (see that module's docstring): **no ``owner_id`` column**,
because the only path from an attachment to an owner is ``note_id -> note.owner_id``, and that join
is already how every route on this table has to be authorized — ``app.api.refs.NoteFromRef`` (and
therefore ``authorize_note``) runs before either route in ``app/api/attachments.py`` ever reads this
table, exactly as CLAUDE.md's owner-scoping rule describes for ``note_link``.

Four columns that matter, plus the surrogate key and a timestamp:

- ``note_id`` — the owning note, ``note.id``, ``ON DELETE CASCADE``. An attachment has no meaning
  independent of the note it was uploaded to, matching ``note_link.source_note_id``'s reasoning
  exactly.
- ``r2_key`` — the object's key inside the bucket, ``{note_id}/{uuid4}{ext}``
  (``app/api/attachments.py``'s ``object_key``) — **never** the caller-supplied filename verbatim,
  which would be a path-traversal-shaped key (``../../secrets``, a name containing a stray ``/``)
  if trusted as-is.
- ``content_type`` — the browser-supplied MIME type at upload time, stored so a later fetch can
  answer with the right ``Content-Type`` without re-sniffing the bytes.
- ``size_bytes`` — recorded for a future listing/quota UI; nothing enforces a quota yet.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

R2_KEY_MAX = 512
"""Room for ``{note_id}/{uuid4.hex}{.ext}`` many times over — a `note.id` is at most ten digits, a
hex UUID4 is 32 characters, and an extension is capped much smaller than this in
``app/api/attachments.py``."""

CONTENT_TYPE_MAX = 255
"""A MIME type never approaches this; it is a bound so a caller-supplied `Content-Type` header
cannot grow the column past what an index over it (should one ever be added) would tolerate."""


class Attachment(Base):
    """One uploaded file, attached to exactly one note."""

    __tablename__ = "attachment"

    id: Mapped[int] = mapped_column(primary_key=True)

    note_id: Mapped[int] = mapped_column(
        ForeignKey("note.id", ondelete="CASCADE"), nullable=False, index=True
    )
    """The owning note. ``ON DELETE CASCADE``, the same reasoning as ``note_link.source_note_id`` —
    an attachment with no note left to belong to is not a state anything here represents.
    ``index=True`` because, unlike ``note_link``'s unique constraint, there is no other index on
    this table whose leading column already covers "every attachment for this note"."""

    r2_key: Mapped[str] = mapped_column(String(R2_KEY_MAX), nullable=False, unique=True)
    """The object's address inside the bucket. Unique because it *is* the object's address — two
    rows sharing a key would mean two attachments naming one blob, a state the upload path (which
    always mints a fresh UUID) cannot produce; the constraint says so structurally rather than by
    convention."""

    content_type: Mapped[str] = mapped_column(String(CONTENT_TYPE_MAX), nullable=False)
    """The MIME type recorded at upload time. Caller-supplied, never sniffed from the bytes — R14
    does not ask for content-sniffing, and trusting the browser's own `Content-Type` for a file it
    just read off disk is the same trust boundary every other multipart upload in the wild uses."""

    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    """``BigInteger`` rather than the plain ``Integer`` `note.id` uses: a note body is bounded by
    what a person types, an attachment is bounded by nothing this schema enforces yet, and a 2 GiB
    ceiling is cheap to avoid paying for later."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
