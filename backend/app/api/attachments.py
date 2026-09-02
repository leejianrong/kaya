"""``/api/v1/notes/{ref}/attachments`` — R14, KAN-1067 (upload) and KAN-1068 (authenticated render).

Two routes, and both are reached exactly like a note itself: through ``NoteFromRef``, so a caller
who cannot see the note cannot upload to it or read from it either. The `403`/`404` split is
inherited rather than reimplemented — the same shape ``app/api/links.py`` argues for `/links` and
`/backlinks`. ``attachment`` has **no owner column** (see ``app/models/attachment.py``): the only
thing that scopes either route to the right caller is the note that already went through
``authorize_note``, which is why KAN-1069's mutation test targets the ``WHERE`` clause in
``get_attachment`` directly rather than a query this module never writes.

**Upload never redirects to R2 and reads never hand back an R2 URL.**
``app/integrations/storage.py`` says why: every byte crosses through this process, so the same
authorization check that guards a note's own body guards every attachment on it too, and nothing
that identifies a private object ever sits in a URL a browser could cache, bookmark or leak through
a referrer header — the same argument CLAUDE.md makes for the bearer staying in `sessionStorage`.
"""

import io
from pathlib import PurePosixPath
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.refs import NoteFromRef
from app.api.schemas import AttachmentRead
from app.auth import error_body
from app.config import Settings, get_settings
from app.db import get_session
from app.integrations.dependencies import ObjectStorageDep
from app.integrations.storage import ObjectStorageUnavailable
from app.models.attachment import Attachment

router = APIRouter(prefix="/api/v1", tags=["attachments"])

DbSession = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

MAX_EXTENSION_LENGTH = 16
"""Room for anything a real filename carries (`.jpeg`, `.tar.gz` would only keep `.gz`) and no
more — an "extension" this long is not one, and the object key is not the place to find out."""

DEFAULT_CONTENT_TYPE = "application/octet-stream"


def _extension(filename: str | None) -> str:
    """The caller-supplied filename's suffix, cleaned to ASCII alphanumerics and capped — never the
    filename itself. ``PurePosixPath`` rather than a bare `rsplit('.')`: it is what already knows a
    name with no dot has no suffix, without this function re-deriving that rule.

    The result is cosmetic — it survives into the object key so a downloaded file keeps a plausible
    extension — and it is deliberately not trusted for anything a security decision could hang on;
    `content_type`, stored separately, is what a reader acts on.
    """
    if not filename:
        return ""
    suffix = PurePosixPath(filename).suffix
    cleaned = "".join(character for character in suffix if character.isalnum())
    cleaned = cleaned[:MAX_EXTENSION_LENGTH].lower()
    return f".{cleaned}" if cleaned else ""


def object_key(note_id: int, filename: str | None) -> str:
    """``{note_id}/{uuid4}{ext}`` — R14's namespacing, and the whole of why a filename can never
    collide with, overwrite or path-traverse out of another note's objects. The UUID is what makes
    the key unique regardless of what — if anything — the caller called the file; the note id
    prefix is what makes "every object for this note" a cheap bucket-side listing, though nothing
    here uses that yet.
    """
    return f"{note_id}/{uuid4().hex}{_extension(filename)}"


def _read_capped(upload: UploadFile, max_bytes: int) -> bytes:
    """Read ``upload`` in chunks, refusing anything past ``max_bytes`` before it is ever handed to
    storage. A `413` here costs nothing R2 would otherwise have to undo — refusing after the fact
    would mean deleting a partially- or fully-uploaded object on the way out.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = upload.file.read(65536)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=error_body(
                    "attachment_too_large",
                    f"attachments are capped at {max_bytes} bytes",
                ),
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.post(
    "/notes/{ref}/attachments",
    status_code=status.HTTP_201_CREATED,
    summary="Upload a file, attached to a note",
)
def create_attachment(
    note: NoteFromRef,
    session: DbSession,
    storage: ObjectStorageDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File()],
) -> AttachmentRead:
    """Stream ``file`` to R2 under a key namespaced by ``note.id`` (never the caller's filename
    verbatim — see ``object_key``), record the row, and return the markdown reference to insert
    into the note body. The note itself is never touched — inserting the returned `markdown` into
    `body` is a caller's own `PATCH`, exactly as a wikilink is typed rather than injected here.

    The size cap (`_read_capped`) runs **before** anything reaches storage, so a refused upload
    never becomes an object somebody has to clean up.
    """
    content_type = file.content_type or DEFAULT_CONTENT_TYPE
    body = _read_capped(file, settings.r2_upload_max_bytes)
    key = object_key(note.id, file.filename)

    try:
        storage.put(key, io.BytesIO(body), content_type=content_type)
    except ObjectStorageUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=error_body(
                "attachment_storage_unavailable", "could not reach object storage"
            ),
        ) from exc

    attachment = Attachment(
        note_id=note.id,
        r2_key=key,
        content_type=content_type,
        size_bytes=len(body),
    )
    session.add(attachment)
    session.commit()
    session.refresh(attachment)

    alt = file.filename or "attachment"
    return AttachmentRead.of(attachment, note_ref=note.ref, alt=alt)


def attachment_not_found() -> HTTPException:
    """The one refusal both branches of `get_attachment` raise, as a value — same shape as
    `refs.invalid_note_ref` — so a missing row and a wrong-note row answer with byte-identical
    bodies. That identity is deliberate: telling them apart would confirm to a caller that *some*
    attachment exists at an id it does not own, which is exactly the disclosure KAN-1069 exists to
    rule out.
    """
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=error_body("attachment_not_found", "no such attachment"),
    )


@router.get(
    "/notes/{ref}/attachments/{attachment_id}",
    summary="Fetch one attachment's bytes, authorized exactly like the note",
)
def get_attachment(
    note: NoteFromRef,
    attachment_id: int,
    session: DbSession,
    storage: ObjectStorageDep,
) -> Response:
    """The raw bytes, with the `Content-Type` recorded at upload. Never a redirect and never an R2
    URL — see the module docstring.

    **The `WHERE` below is the whole of this route's authorization**, and it is why KAN-1069's
    mutation targets it rather than `authorize_note` itself: `note` already passed through that
    check (a `404`/`403` for a note the caller cannot see never reaches this line), so the only
    thing left to get wrong is scoping *this* table to *that* note — `Attachment.note_id == note.id`
    is the one clause standing between "this caller's note" and "any attachment in the database",
    the identical shape `note_link`'s CLAUDE.md rule describes for a table with no owner column of
    its own.
    """
    attachment = session.execute(
        select(Attachment).where(
            Attachment.id == attachment_id, Attachment.note_id == note.id
        )
    ).scalar_one_or_none()
    if attachment is None:
        raise attachment_not_found()

    found = storage.get(attachment.r2_key)
    if found is None:
        # The row exists but the object does not — an upload that never finished, or an object
        # deleted bucket-side out from under kaya. Same `404` a caller gets for a row that never
        # existed: there is nothing more specific to say that is not also a disclosure.
        raise attachment_not_found()

    return Response(content=found.body, media_type=attachment.content_type)
