"""The ``/api/v1`` surface (KAN-536).

Five modules, and the split is the same one ``app/auth/`` makes: the decisions sit in functions
over ordinary objects, and only the two route modules know FastAPI's routing machinery exists.

- ``errors.py`` — the wire shape of an error, for *every* failure the app can produce.
- ``refs.py`` — **the** central ref resolver. ``NOTE-12``, ``note-12`` and ``12`` all arrive here
  and leave as one ``Note``, or as one identical `404`. Every ref-taking route depends on it,
  including the ones V5 adds (`/links`, `/backlinks`) that do not exist yet.
- ``schemas.py`` — what a note looks like on the wire.
- ``notes.py`` — the five routes.
- ``meta.py`` — KAN-555's one **unauthenticated** route, carrying ``KAYA_PANDAN_URL`` to a visitor
  who has no credential yet and therefore cannot be asked for one. One key, on purpose.
"""

from app.api.errors import install_error_handlers
from app.api.meta import router as meta_router
from app.api.notes import router
from app.api.refs import NoteRef, invalid_note_ref, parse_note_ref, resolve_note

__all__ = [
    "NoteRef",
    "install_error_handlers",
    "invalid_note_ref",
    "meta_router",
    "parse_note_ref",
    "resolve_note",
    "router",
]
