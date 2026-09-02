"""The ``/api/v1`` surface (KAN-536).

Nine modules, and the split is the same one ``app/auth/`` makes: the decisions sit in functions
over ordinary objects, and only the route modules know FastAPI's routing machinery exists.

- ``errors.py`` — the wire shape of an error, for *every* failure the app can produce.
- ``refs.py`` — **the** central ref resolver. ``NOTE-12``, ``note-12`` and ``12`` all arrive here
  and leave as one ``Note``, or as one identical `404`. Every ref-taking route depends on it,
  V5's `/links` and `/backlinks` included.
- ``schemas.py`` — what a note, and since KAN-566 a link, since KAN-1049 a board embed, and since
  KAN-1067 an attachment, looks like on the wire.
- ``notes.py`` — the five routes.
- ``links.py`` — KAN-566's two: ``/notes/{ref}/links`` and ``/notes/{ref}/backlinks``. A second
  route module rather than two more functions in ``notes.py``, because these are the only routes in
  the package that take a bearer and an upstream client as well as a session — see its docstring,
  which argues the split and the three-phase body that follows from it.
- ``embeds.py`` — KAN-1049's one: ``/embeds/board``, a note's live `pandan-board` embed. A bearer
  and an upstream client but, unlike ``links.py``, deliberately **no** session — see its docstring.
- ``graph.py`` — KAN-1050's ``/graph``: every note the caller owns and every resolved note-to-note
  wikilink among them, node-and-edge shaped for the SPA's graph view.
- ``attachments.py`` — R14's two (KAN-1067/1068): ``POST``/``GET /notes/{ref}/attachments``,
  reached through ``NoteFromRef`` exactly like every other ref-taking route, over a table with no
  owner column of its own — see its module docstring.
- ``note_claim.py`` — R12/KAN-1061's ``PUT /notes/{ref}``: create a note at a caller-chosen, still-
  free ref, for the one caller (kaya-client's import path) that has a specific number to reclaim —
  see its module docstring for why this needed a new route rather than a field on ``NoteCreate``.
- ``meta.py`` — KAN-555's one **unauthenticated** route, carrying ``KAYA_PANDAN_URL`` to a visitor
  who has no credential yet and therefore cannot be asked for one. One key, on purpose.
"""

from app.api.attachments import router as attachments_router
from app.api.embeds import router as embeds_router
from app.api.errors import install_error_handlers
from app.api.graph import router as graph_router
from app.api.links import router as links_router
from app.api.meta import router as meta_router
from app.api.note_claim import router as note_claim_router
from app.api.notes import router
from app.api.refs import NoteRef, invalid_note_ref, parse_note_ref, resolve_note

__all__ = [
    "NoteRef",
    "attachments_router",
    "embeds_router",
    "graph_router",
    "install_error_handlers",
    "invalid_note_ref",
    "links_router",
    "meta_router",
    "note_claim_router",
    "parse_note_ref",
    "resolve_note",
    "router",
]
