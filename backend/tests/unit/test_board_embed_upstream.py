"""``PandanBoardEmbedUpstream``, faked at the HTTP boundary — the same technique
``test_card_resolution_upstream.py`` uses, for the same reason: ``httpx.MockTransport`` means the
request under assertion is the real one httpx would put on the wire.

Response shapes mirror pandan's real ``CardRead``/``SavedViewRead`` (verified live against
``https://simple-kanban-jian.fly.dev/openapi.json`` on 2026-09-01, at the time this card was built):
``GET /api/v1/cards`` returns a bare ``CardRead[]`` with ``ticket_number``/``title``/``column``
among its fields, and ``GET /api/v1/boards/{board_id}/views/{view_id}`` returns a ``SavedViewRead``
whose ``query`` is the structured filter/sort grammar (``CardQuery``) that replays verbatim as
``GET /cards`` query params.

No real PAT appears here or anywhere else in the suite.
"""

import httpx
import pytest
from fakes import TOKEN

from app.integrations.board_embed import (
    CARDS_PATH,
    BoardEmbedUnavailable,
    PandanBoardEmbedUpstream,
    views_path,
)

BASE_URL = "https://pandan.invalid"


def upstream_returning(handler: object) -> PandanBoardEmbedUpstream:
    client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    return PandanBoardEmbedUpstream(BASE_URL, timeout=1.0, client=client)


def json_response(status: int, payload: object, headers: dict[str, str] | None = None) -> object:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload, headers=headers or {})

    return handler


# --- fetch_view_query -----------------------------------------------------------------------------


def test_fetch_view_query_hits_the_view_path_with_the_bearer() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": 3, "board_id": 18, "name": "Todo", "query": {}})

    upstream_returning(handler).fetch_view_query(TOKEN, 18, 3)

    request = seen[0]
    assert request.url.path == views_path(18, 3)
    assert request.headers["authorization"] == f"Bearer {TOKEN}"


def test_fetch_view_query_returns_the_query_object_with_nulls_dropped() -> None:
    body = {
        "id": 3,
        "board_id": 18,
        "name": "In progress, high priority",
        "query": {"column": "in_progress", "priority": "high", "assignee": None, "sort": None},
    }
    query = upstream_returning(json_response(200, body)).fetch_view_query(TOKEN, 18, 3)

    assert query == {"column": "in_progress", "priority": "high"}


def test_fetch_view_query_with_an_empty_query_is_an_empty_dict() -> None:
    body = {"id": 3, "board_id": 18, "name": "Everything", "query": {}}
    query = upstream_returning(json_response(200, body)).fetch_view_query(TOKEN, 18, 3)

    assert query == {}


@pytest.mark.parametrize("status", [403, 404, 422, 500, 503])
def test_a_non_200_from_the_view_is_an_outage(status: int) -> None:
    """A 403 (not this caller's board) and a 404 (no such view) both count — see
    `board_embed.py`'s `BoardEmbedResult` docstring on why they are not distinguished."""
    upstream = upstream_returning(json_response(status, {"detail": "nope"}))
    with pytest.raises(BoardEmbedUnavailable):
        upstream.fetch_view_query(TOKEN, 18, 3)


def test_a_transport_failure_on_the_view_is_an_outage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(BoardEmbedUnavailable):
        upstream_returning(handler).fetch_view_query(TOKEN, 18, 3)


@pytest.mark.parametrize(
    "payload",
    [
        {"id": 3, "board_id": 18, "name": "no query key"},
        {"id": 3, "board_id": 18, "name": "query is not an object", "query": "nope"},
        [1, 2, 3],
        "a login page interstitial served with a 200",
    ],
)
def test_a_200_kaya_cannot_read_is_an_outage_for_the_view(payload: object) -> None:
    with pytest.raises(BoardEmbedUnavailable):
        upstream_returning(json_response(200, payload)).fetch_view_query(TOKEN, 18, 3)


# --- fetch_cards ------------------------------------------------------------------------------


def test_fetch_cards_hits_cards_with_board_id_and_the_given_params() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[])

    upstream_returning(handler).fetch_cards(TOKEN, 18, {"column": "todo"})

    request = seen[0]
    assert request.url.path == CARDS_PATH
    assert dict(request.url.params) == {"board_id": "18", "column": "todo"}
    assert request.headers["authorization"] == f"Bearer {TOKEN}"


def test_fetch_cards_forwards_every_replayed_view_param() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[])

    upstream_returning(handler).fetch_cards(TOKEN, 18, {"column": "done", "priority": "high"})

    assert dict(seen[0].url.params) == {"board_id": "18", "column": "done", "priority": "high"}


def test_fetch_cards_parses_ref_title_and_column() -> None:
    body = [
        {"id": 1, "ticket_number": "KAN-1", "title": "First", "column": "todo"},
        {"id": 2, "ticket_number": "KAN-2", "title": "Second", "column": "done"},
    ]
    cards = upstream_returning(json_response(200, body)).fetch_cards(TOKEN, 18, {"column": "todo"})

    assert [c.ref for c in cards] == ["KAN-1", "KAN-2"]
    assert cards[0].title == "First"
    assert cards[0].column == "todo"


def test_fetch_cards_with_an_empty_result_is_an_empty_tuple() -> None:
    cards = upstream_returning(json_response(200, [])).fetch_cards(TOKEN, 18, {"column": "todo"})
    assert cards == ()


@pytest.mark.parametrize("status", [403, 404, 422, 500, 503])
def test_a_non_200_from_cards_is_an_outage(status: int) -> None:
    upstream = upstream_returning(json_response(status, {"detail": "nope"}))
    with pytest.raises(BoardEmbedUnavailable):
        upstream.fetch_cards(TOKEN, 18, {"column": "todo"})


def test_a_transport_failure_on_cards_is_an_outage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(BoardEmbedUnavailable):
        upstream_returning(handler).fetch_cards(TOKEN, 18, {"column": "todo"})


@pytest.mark.parametrize(
    "payload",
    [
        [{"id": 1, "title": "no ticket_number", "column": "todo"}],
        [{"id": 1, "ticket_number": "KAN-1", "column": "todo"}],  # no title
        {"not": "a list"},
        "a login page interstitial served with a 200",
    ],
)
def test_a_200_kaya_cannot_read_is_an_outage_for_cards(payload: object) -> None:
    with pytest.raises(BoardEmbedUnavailable):
        upstream_returning(json_response(200, payload)).fetch_cards(TOKEN, 18, {"column": "todo"})
