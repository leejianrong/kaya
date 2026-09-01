"""Live pandan board/view queries embedded in a note's preview — KAN-1049.

A note's body can carry a fenced ```pandan-board`` block naming a board plus either a saved view or
a column, and the SPA's preview hydrates it into a read-only list of cards
(``frontend/src/lib/embeds.ts``, ``frontend/src/components/PreviewPane.svelte``). This module is the
backend half: it turns ``(board, view)`` or ``(board, column)`` into pandan's own real cards, with
the caller's own bearer, and it never raises for a network reason — the same contract
``app/integrations/card_resolution.py`` (KAN-564) already keeps, and for the same ADR 0003 reason:
an embed rendering "unavailable" is a decoration going missing, and a note must render whether
pandan is up or not.

Deliberately **not** a copy-paste of ``card_resolution.py`` beyond that shared shape, because the
call pattern is genuinely different:

- Card resolution answers *many distinct refs* per render, chunked against a combined-selector cap,
  with a resolver that de-duplicates and bounds itself across a whole `resolve()` call.
- A board embed is **one or two whole-response fetches** per render: `column` is one
  `GET /api/v1/cards?board_id=…&column=…`; `view` is one
  `GET /api/v1/boards/{board_id}/views/{view_id}` to read the saved query, then one more
  `GET /api/v1/cards?board_id=…&<that query>` to replay it. There is nothing here to chunk, no
  request-count cap to enforce beyond "at most two", and no need for `CardEpicResolver`'s
  deadline/dedup machinery.

**Deliberately no cache**, unlike `CardEpicCache`. A card's *title* barely changes between two
renders of the same note a few minutes apart, which is what makes card resolution's 5-minute TTL a
good trade. A saved view or column query is closer to "what's on my board right now" — that is the
whole reason somebody embeds a live query instead of typing a static list — so a stale answer is a
worse failure mode here than an extra pandan round trip on every render. If this ever needs a cache
(e.g. a note viewed by many readers at once hammering one view), it wants its own short TTL and its
own key (`sha256(bearer)`, board, view-or-column) — not a knob bolted onto `CardEpicCache`, whose
key shape and TTL were sized for a different fact.
"""

from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.auth.upstream import split_timeout
from app.config import Settings

CARDS_PATH = "/api/v1/cards"


def views_path(board_id: int, view_id: int) -> str:
    return f"/api/v1/boards/{board_id}/views/{view_id}"


# --- What gets resolved -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BoardEmbedCard:
    """One card, as much as a `pandan-board` embed's read-only row needs."""

    ref: str
    """Pandan's own `ticket_number` (e.g. `"KAN-12"`) — a different ref system from kaya's
    `NOTE-n` (ADR 0008). Never confused with one: this module never touches a kaya note id."""

    title: str
    column: str


@dataclass(frozen=True, slots=True)
class BoardEmbedResult:
    """What `BoardEmbedResolver.resolve` always returns — never an exception, per the module
    docstring. `unavailable=True` covers every reason pandan could not answer (down, the caller
    cannot see this board/view, the board or view does not exist, an unreadable body) — the API
    route (`app/api/embeds.py`) does not distinguish them either, for the same over-disclosure
    reason `card_resolution.py` gives: a 403-shaped "you can't see this" and a 404-shaped "this
    doesn't exist" must not be told apart by a caller probing board ids they don't own."""

    unavailable: bool
    cards: tuple[BoardEmbedCard, ...]


# --- The upstream seam ---------------------------------------------------------------------------


class BoardEmbedUnavailable(Exception):
    """pandan could not be asked, or answered with something this module can't use. Mirrors
    `CardEpicUnavailable` — caught inside `BoardEmbedResolver.resolve`, never re-raised past it."""


class BoardEmbedUpstream(Protocol):
    """The two calls this card needs, behind a seam fakeable at the HTTP boundary — same reasoning
    as `CardEpicUpstream`."""

    def fetch_view_query(self, bearer: str, board_id: int, view_id: int) -> dict[str, Any]:
        """The saved view's stored `CardQuery`, as a `dict` with `None` values dropped (pandan's
        `CardQuery` fields all default to `null`; a `null` sent back as a query param would ask for
        `column=None` literally, which pandan would reject rather than treat as "unset")."""
        ...

    def fetch_cards(
        self, bearer: str, board_id: int, params: dict[str, Any]
    ) -> tuple[BoardEmbedCard, ...]:
        """One `GET /api/v1/cards?board_id=…` request, ``params`` merged in verbatim on top of
        ``board_id`` (a saved view's replayed query, or a bare ``{"column": …}``)."""
        ...


class PandanBoardEmbedUpstream:
    """`BoardEmbedUpstream` over real HTTP. The bearer is forwarded byte for byte — kaya has no
    token format and mints none of its own (ADR 0002), same as every other upstream call here."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: httpx.Timeout | float,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        # `timeout` configures the client this builds; a `client` passed in (tests only) carries
        # its own — see `PandanCardEpicUpstream`'s constructor comment, the asymmetry is the same.
        self._client = client if client is not None else httpx.Client(timeout=timeout)

    def fetch_view_query(self, bearer: str, board_id: int, view_id: int) -> dict[str, Any]:
        url = self._base_url + views_path(board_id, view_id)
        try:
            response = self._client.get(url, headers={"Authorization": f"Bearer {bearer}"})
        except httpx.HTTPError as exc:
            raise BoardEmbedUnavailable(f"{url} is unreachable") from exc

        if response.status_code != 200:
            # A 403 (not this caller's board) and a 404 (no such view) both land here — see
            # `BoardEmbedResult`'s docstring on why this module does not distinguish them.
            raise BoardEmbedUnavailable(f"{url} answered {response.status_code}")

        try:
            payload = response.json()
            query = payload["query"]
            if not isinstance(query, dict):
                raise TypeError("`query` was not an object")
        except (ValueError, TypeError, KeyError) as exc:
            raise BoardEmbedUnavailable(f"{url} returned a body kaya could not read") from exc

        return {key: value for key, value in query.items() if value is not None}

    def fetch_cards(
        self, bearer: str, board_id: int, params: dict[str, Any]
    ) -> tuple[BoardEmbedCard, ...]:
        url = self._base_url + CARDS_PATH
        try:
            response = self._client.get(
                url,
                params={"board_id": board_id, **params},
                headers={"Authorization": f"Bearer {bearer}"},
            )
        except httpx.HTTPError as exc:
            raise BoardEmbedUnavailable(f"{url} is unreachable") from exc

        if response.status_code != 200:
            raise BoardEmbedUnavailable(f"{url} answered {response.status_code}")

        try:
            payload = response.json()
            return tuple(
                BoardEmbedCard(
                    ref=str(item["ticket_number"]),
                    title=str(item["title"]),
                    column=str(item["column"]),
                )
                for item in payload
            )
        except (ValueError, TypeError, KeyError) as exc:
            raise BoardEmbedUnavailable(f"{url} returned a body kaya could not read") from exc


# --- The resolver ---------------------------------------------------------------------------------


class BoardEmbedResolver:
    """`(board, view)` or `(board, column)` in, `BoardEmbedResult` out. Never raises.

    No cache, no dedup, no deadline clock: see the module docstring for why a board embed's call
    shape does not need `CardEpicResolver`'s machinery. Bounded structurally instead — exactly one
    upstream call for a `column` query, exactly two (view, then cards) for a `view` query, and any
    failure at either step collapses to `unavailable` rather than a partial answer, because a card
    list filtered by a query pandan never actually confirmed would be a wrong answer dressed up as
    a real one.
    """

    def __init__(self, upstream: BoardEmbedUpstream) -> None:
        self._upstream = upstream

    def resolve(
        self,
        bearer: str,
        board_id: int,
        *,
        view_id: int | None = None,
        column: str | None = None,
    ) -> BoardEmbedResult:
        """Exactly one of ``view_id``/``column`` is expected — `app/api/embeds.py` enforces that
        at the request boundary, so this method does not re-validate it; a call with both or
        neither is a caller bug, not a pandan-shaped outcome, and is not this method's contract."""
        try:
            params = (
                self._upstream.fetch_view_query(bearer, board_id, view_id)
                if view_id is not None
                else {"column": column}
            )
            cards = self._upstream.fetch_cards(bearer, board_id, params)
        except BoardEmbedUnavailable:
            return BoardEmbedResult(unavailable=True, cards=())

        return BoardEmbedResult(unavailable=False, cards=cards)


# --- Wiring helpers (`app/integrations/dependencies.py` owns the Depends() lifecycle) ------------


def default_upstream(settings: Settings) -> BoardEmbedUpstream:
    return PandanBoardEmbedUpstream(
        settings.pandan_url,
        timeout=split_timeout(
            connect=settings.board_embed_connect_timeout_seconds,
            read=settings.board_embed_read_timeout_seconds,
        ),
    )


def default_resolver(upstream: BoardEmbedUpstream) -> BoardEmbedResolver:
    return BoardEmbedResolver(upstream)
