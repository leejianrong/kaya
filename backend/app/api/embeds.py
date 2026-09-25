"""``GET /api/v1/embeds/board`` — a live pandan board/view query for a note's `pandan-board`
fenced-code embed (KAN-1049, amended by ADR 0012's KAN-1741).

A note's preview (``frontend/src/lib/markdown.ts``, ``PreviewPane.svelte``) renders a placeholder
for a ```pandan-board`` block and then asks this route for the live cards. This module is a thin
passthrough onto ``app.integrations.board_embed``: resolve the caller's kaya identity, look up
their linked pandan PAT, parse the two query params into exactly one request shape, and return
whatever ``BoardEmbedResolver.resolve()`` decided — which, per that module's contract, is never an
exception.

**Now depends on ``get_principal``, where it deliberately did not before ``KAN-1740``.** The
original design here forwarded the caller's own bearer straight to pandan and skipped
``get_principal`` on purpose, because before that cutover ``get_principal`` meant a second, blocking
pandan round trip (ADR 0002's identity introspection) on every cold cache — a cost this route's own
upstream call already had to pay once, and paying it twice for a route whose real authorization
check *is* pandan's own board/view ownership check would have bought nothing. ``KAN-1740`` removed
that cost entirely: ``get_principal`` is now a local, indexed database lookup with no pandan call in
it at all (`app/auth/kaya_principal.py`). What used to be a real trade-off is now free, and it is
also the only way this route can know *which* linked pandan PAT to forward — the caller's own
kaya-side bearer stopped being a pandan credential the same cutover made, so there is no longer a
bearer to skip resolving in the first place. See `app/integrations/board_embed.py`'s module
docstring for the rest of that story.

**Still no session-owning row of its own** — a lookup, not a write, and the one place this route
touches the database is a single indexed `SELECT` on `pandan_link.user_id`
(`app/identity/pandan_link.py`), not a session `get_principal` didn't already need to open.

Query validation is a `422` in the usual shape, built by hand rather than left to FastAPI's
default: "exactly one of ``view``/``column``" is a cross-field rule Pydantic's per-field validation
does not express on its own, and a bare ``board: int`` query parameter already gets FastAPI's
normal `422` for missing/non-numeric for free.
"""

from dataclasses import dataclass
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import BoardEmbedResponse, EmbedCard
from app.auth import Principal, error_body, get_principal
from app.config import get_settings
from app.db import get_session
from app.identity.pandan_link import PandanLink, decrypt_token
from app.integrations.dependencies import BoardResolver

router = APIRouter(prefix="/api/v1", tags=["embeds"])


@dataclass(frozen=True, slots=True)
class BoardEmbedQuery:
    """The one validated request shape: a board, and exactly one of a view or a column."""

    board: int
    view: int | None
    column: str | None


def board_embed_query(
    board: Annotated[int, Query(description="Pandan board id")],
    view: Annotated[int | None, Query(description="Saved view id")] = None,
    column: Annotated[str | None, Query(description="Column name")] = None,
) -> BoardEmbedQuery:
    """``board`` is required and must parse as an integer — FastAPI's own `422` covers "missing" and
    "not a number" without anything written here. What is written here is the one rule FastAPI
    cannot express on a single field: ``view`` xor ``column``.
    """
    if (view is None) == (column is None):
        raise HTTPException(
            # `HTTPStatus.UNPROCESSABLE_ENTITY` rather than `status.HTTP_422_UNPROCESSABLE_ENTITY`,
            # matching `app/api/errors.py`'s `handle_validation_error` — the latter is a deprecated
            # alias in this Starlette version (`HTTP_422_UNPROCESSABLE_CONTENT` replaced it).
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail=error_body(
                "invalid_request",
                "exactly one of `view` or `column` is required",
                field="view" if view is None else "column",
            ),
        )
    return BoardEmbedQuery(board=board, view=view, column=column)


def linked_pandan_bearer(db: Session, principal: Principal) -> str | None:
    """The caller's own linked pandan PAT, decrypted, or `None` if they have never connected one
    (`app/api/pandan_link.py`) or the stored ciphertext can no longer be read back (a
    `KAYA_AUTH_SECRET` rotation since — `decrypt_token`'s own docstring). Both collapse to the
    same `None`, on purpose: `BoardEmbedResolver.resolve` cannot and should not act differently on
    either, the same "a caller cannot act differently" argument `BoardEmbedResult` already makes
    for `unavailable`."""
    link = db.scalar(select(PandanLink).where(PandanLink.user_id == principal.id))
    if link is None:
        return None
    return decrypt_token(link.encrypted_token, get_settings().kaya_auth_secret)


EmbedQuery = Annotated[BoardEmbedQuery, Depends(board_embed_query)]
CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
DbSession = Annotated[Session, Depends(get_session)]


@router.get(
    "/embeds/board",
    summary="A live pandan board/view query, for a note's `pandan-board` embed",
)
def get_board_embed(
    query: EmbedQuery,
    db: DbSession,
    principal: CurrentPrincipal,
    resolver: BoardResolver,
) -> BoardEmbedResponse:
    """Always `200`. `not_connected: true` means this caller has no linked pandan PAT to forward
    at all; otherwise `unavailable: true` covers every reason pandan itself could not answer —
    down, the board/view does not exist, or the caller cannot see it — and `cards` is `[]` in
    every one of those cases, or for a legitimately empty result (`BoardEmbedResponse`'s
    docstring, ADR 0003)."""
    bearer = linked_pandan_bearer(db, principal)
    result = resolver.resolve(bearer, query.board, view_id=query.view, column=query.column)
    return BoardEmbedResponse(
        unavailable=result.unavailable,
        not_connected=result.not_connected,
        cards=[
            EmbedCard(ref=card.ref, title=card.title, column=card.column) for card in result.cards
        ],
    )
