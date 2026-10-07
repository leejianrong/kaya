"""Declarative models.

Every model is imported here so it reaches ``Base.metadata``. That is not tidiness:
``alembic/env.py`` imports this package to build ``target_metadata``, and an autogenerate run
against metadata that never imported a model emits a migration that *drops* the tables it cannot
see.

A new model goes in its own module and gets an import below. Both, always.

**``User`` (``app/models/user.py``, the ADR 0002 pandan-mirror table) is gone as of migration
``0009``, retired alongside ADR 0002 itself (KAN-1740).** ``note.owner_id`` now points at
``app.identity.models.KayaAccount`` instead — that table lives in ``app/identity/models.py``, not
here, and is imported into ``Base.metadata`` from ``alembic/env.py`` directly rather than through
this package, the same way ``app.identity.pat``'s ``PersonalAccessToken`` already was.
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
from app.models.team import Team

__all__ = [
    "NOTE_REF_PREFIX",
    "NOTE_REF_SEQUENCE",
    "NOTE_REF_SEQUENCE_NAME",
    "Attachment",
    "Base",
    "Note",
    "NoteLink",
    "NoteVersion",
    "Team",
]
