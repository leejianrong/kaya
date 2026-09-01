"""Declarative models.

Every model is imported here so it reaches ``Base.metadata``. That is not tidiness:
``alembic/env.py`` imports this package to build ``target_metadata``, and an autogenerate run
against metadata that never imported a model emits a migration that *drops* the tables it cannot
see.

A new model goes in its own module and gets an import below. Both, always.
"""

from app.models.attachment import Attachment
from app.models.base import Base
from app.models.note import (
    NOTE_REF_PREFIX,
    NOTE_REF_SEQUENCE,
    NOTE_REF_SEQUENCE_NAME,
    Note,
)
from app.models.note_link import NoteLink
from app.models.note_version import NoteVersion
from app.models.user import User

__all__ = [
    "NOTE_REF_PREFIX",
    "NOTE_REF_SEQUENCE",
    "NOTE_REF_SEQUENCE_NAME",
    "Attachment",
    "Base",
    "Note",
    "NoteLink",
    "NoteVersion",
    "User",
]
