"""``GET /api/v1/embeds/board`` — a live pandan board/view query for a note's `pandan-board`
fenced-code embed (KAN-1049).

A note's preview (``frontend/src/lib/markdown.ts``, ``PreviewPane.svelte``) renders a placeholder
for a ```pandan-board`` block and then asks this route for the live cards. This module is a pure
passthrough onto ``app.integrations.board_embed``: parse the two query params into exactly one
request shape, forward the caller's own bearer, and return whatever
``BoardEmbedResolver.resolve()`` decided — which, per that module's contract, is never an
exception.

**Deliberately no ``session: DbSession`` parameter, and deliberately not ``get_principal``.** Every
other authenticated route in ``app/api/`` depends on ``get_principal``, which resolves a full
``Principal`` against pandan's ``GET /api/v1/me`` and mirrors it into kaya's own ``user`` table —
the right call when a request is about to *own* a row (a note, a link edge). This route touches no
kaya-owned row at all: it is a bearer going out and pandan's own answer coming back, unmodified.
Routing it through ``get_principal`` would buy nothing (this route's authorization *is* pandan's
own board/view ownership check, made when ``BoardEmbedResolver`` calls it) and would cost two
things this route does not need: a second blocking pandan round trip on every cold cache (identity
introspection, ADR 0002's one deliberate exception to "nothing blocks on pandan" —
``card_resolution.py``'s ``/links`` route pays this cost too, but for edges it is *about to
authorize against a local row*), and a ``Depends(get_session)`` this route has no other use for.

So authentication here is structural rather than full identity resolution: a request with no
``Authorization`` header at all gets kaya's own `401` (below), in the same error shape and with the
same ``WWW-Authenticate`` header ``principal_from_bearer`` would give it. A request carrying a
bearer pandan does not recognise is **not** a `401` from kaya — it reaches
``BoardEmbedResolver.resolve()``, which forwards it, gets pandan's own `401`/`403`, and renders
``unavailable: true`` exactly as it would for a board the caller cannot see. That is not a gap: a
kaya-side identity check would answer the same question (is this bearer any good?) that the
embed's own upstream call is about to answer anyway, so doing it twice would only add pandan
latency to every render for a distinction (invalid token vs. valid-token-wrong-board) this route's
response shape does not surface either way (see ``BoardEmbedResult``'s docstring for why not).

Query validation is a `422` in the usual shape, built by hand rather than left to FastAPI's
default: "exactly one of ``view``/``column``" is a cross-field rule Pydantic's per-field validation
does not express on its own, and a bare ``board: int`` query parameter already gets FastAPI's
normal `422` for missing/non-numeric for free.
"""

from dataclasses import dataclass
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.schemas import BoardEmbedResponse, EmbedCard
from app.auth import error_body
from app.integrations.dependencies import BoardResolver, CallerBearer

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


def require_bearer(bearer: CallerBearer) -> str:
    """The one authentication check this route makes — see the module docstring for why it is
    structural rather than ``get_principal``'s full introspection. Same code, message and header
    ``principal_from_bearer`` uses for the identical case, so a caller sees one `401` shape
    whichever authenticated route answered it.
    """
    if bearer is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_body("authentication_required", "a bearer token is required"),
            headers={"WWW-Authenticate": "Bearer"},
        )
    return bearer


EmbedQuery = Annotated[BoardEmbedQuery, Depends(board_embed_query)]
RequiredBearer = Annotated[str, Depends(require_bearer)]


@router.get(
    "/embeds/board",
    summary="A live pandan board/view query, for a note's `pandan-board` embed",
)
def get_board_embed(
    query: EmbedQuery,
    bearer: RequiredBearer,
    resolver: BoardResolver,
) -> BoardEmbedResponse:
    """Always `200`. `unavailable: true` covers every reason pandan could not answer — down, the
    board/view does not exist, or the caller cannot see it — and ``cards`` is `[]` either way or
    for a legitimately empty result (see ``BoardEmbedResponse``'s docstring, ADR 0003).
    """
    result = resolver.resolve(bearer, query.board, view_id=query.view, column=query.column)
    return BoardEmbedResponse(
        unavailable=result.unavailable,
        cards=[
            EmbedCard(ref=card.ref, title=card.title, column=card.column) for card in result.cards
        ],
    )
