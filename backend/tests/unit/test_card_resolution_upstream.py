"""``PandanCardEpicUpstream``, faked at the HTTP boundary — the same technique
``test_pandan_upstream.py`` uses for identity, for the same reason: ``httpx.MockTransport`` means
the request under assertion is the real one httpx would put on the wire.

The response shapes mirror what pandan actually returns, verified live against
``https://simple-kanban-jian.fly.dev`` on 2026-08-18 (see ``app/integrations/card_resolution.py``'s
module docstring for the full transcript):

    GET /api/v1/cards?refs=KAN-560,KAN-561,EPIC-3,KAN-999999
    -> 200, two cards in the body, X-Unresolved-Selectors: EPIC-3,KAN-999999
    GET /api/v1/epics
    -> 200, every epic across every board the caller can see, no pagination

No real PAT appears here or anywhere else in the suite.
"""

import httpx
import pytest
from fakes import TOKEN

from app.integrations.card_resolution import (
    CARDS_PATH,
    EPICS_PATH,
    CardEpicUnavailable,
    PandanCardEpicUpstream,
)

BASE_URL = "https://pandan.invalid"


def upstream_returning(handler: object) -> PandanCardEpicUpstream:
    client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    return PandanCardEpicUpstream(BASE_URL, timeout=1.0, client=client)


def json_response(status: int, payload: object, headers: dict[str, str] | None = None) -> object:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload, headers=headers or {})

    return handler


# --- fetch_cards ----------------------------------------------------------------------------------


def test_fetch_cards_hits_cards_with_the_bearer_and_a_comma_joined_refs_param() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[])

    upstream_returning(handler).fetch_cards(TOKEN, ["KAN-1", "KAN-2"])

    request = seen[0]
    assert request.url.path == CARDS_PATH
    assert request.url.params["refs"] == "KAN-1,KAN-2"
    assert request.headers["authorization"] == f"Bearer {TOKEN}"


def test_fetch_cards_parses_the_body_and_the_unresolved_header() -> None:
    body = [
        {"id": 1, "ticket_number": "KAN-1", "title": "First", "column": "todo"},
        {"id": 2, "ticket_number": "KAN-2", "title": "Second", "column": "done"},
    ]
    upstream = upstream_returning(
        json_response(200, body, {"X-Unresolved-Selectors": "KAN-3,KAN-4"})
    )

    batch = upstream.fetch_cards(TOKEN, ["KAN-1", "KAN-2", "KAN-3", "KAN-4"])

    assert [c.ticket_number for c in batch.cards] == ["KAN-1", "KAN-2"]
    assert batch.cards[0].kind == "card"
    assert batch.cards[0].title == "First"
    assert batch.cards[0].column == "todo"
    assert batch.unresolved_refs == ("KAN-3", "KAN-4")


def test_fetch_cards_with_no_unresolved_header_is_an_empty_tuple_not_a_missing_key() -> None:
    batch = upstream_returning(json_response(200, [])).fetch_cards(TOKEN, ["KAN-1"])
    assert batch.unresolved_refs == ()


@pytest.mark.parametrize("status", [422, 500, 502, 503])
def test_a_non_200_from_cards_is_an_outage(status: int) -> None:
    upstream = upstream_returning(json_response(status, {"detail": "nope"}))
    with pytest.raises(CardEpicUnavailable):
        upstream.fetch_cards(TOKEN, ["KAN-1"])


def test_a_transport_failure_on_cards_is_an_outage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(CardEpicUnavailable):
        upstream_returning(handler).fetch_cards(TOKEN, ["KAN-1"])


def test_a_timeout_on_cards_is_an_outage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(CardEpicUnavailable):
        upstream_returning(handler).fetch_cards(TOKEN, ["KAN-1"])


@pytest.mark.parametrize(
    "payload",
    [
        [{"id": 1, "title": "no ticket_number", "column": "todo"}],
        [{"id": "not-an-int", "ticket_number": "KAN-1", "title": "x", "column": "todo"}],
        {"not": "a list"},
        "a login page interstitial served with a 200",
    ],
)
def test_a_200_kaya_cannot_read_is_an_outage_for_cards(payload: object) -> None:
    with pytest.raises(CardEpicUnavailable):
        upstream_returning(json_response(200, payload)).fetch_cards(TOKEN, ["KAN-1"])


# --- fetch_epics ----------------------------------------------------------------------------------


def test_fetch_epics_hits_epics_with_no_query_params() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[])

    upstream_returning(handler).fetch_epics(TOKEN)

    request = seen[0]
    assert request.url.path == EPICS_PATH
    assert dict(request.url.params) == {}
    assert request.headers["authorization"] == f"Bearer {TOKEN}"


def test_fetch_epics_parses_the_body() -> None:
    body = [{"id": 3, "ticket_number": "EPIC-3", "name": "M4: Board Collaboration"}]
    epics = upstream_returning(json_response(200, body)).fetch_epics(TOKEN)

    assert len(epics) == 1
    assert epics[0].kind == "epic"
    assert epics[0].ticket_number == "EPIC-3"
    assert epics[0].title == "M4: Board Collaboration"
    assert epics[0].column is None


@pytest.mark.parametrize("status", [500, 502, 503])
def test_a_non_200_from_epics_is_an_outage(status: int) -> None:
    with pytest.raises(CardEpicUnavailable):
        upstream_returning(json_response(status, {"detail": "nope"})).fetch_epics(TOKEN)


def test_a_transport_failure_on_epics_is_an_outage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(CardEpicUnavailable):
        upstream_returning(handler).fetch_epics(TOKEN)


# --- No token leak ------------------------------------------------------------------------------


def test_no_failure_message_carries_the_bearer() -> None:
    """These strings can reach an outer 503 body and the application log (same guard as
    ``test_pandan_upstream.py``'s twin)."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    cases = [
        (upstream_returning(refuse), "fetch_cards", (TOKEN, ["KAN-1"])),
        (upstream_returning(json_response(500, {"detail": "boom"})), "fetch_epics", (TOKEN,)),
        (
            upstream_returning(json_response(200, {"bad": "shape"})),
            "fetch_cards",
            (TOKEN, ["KAN-1"]),
        ),
    ]

    for upstream, method_name, args in cases:
        method = getattr(upstream, method_name)
        with pytest.raises(CardEpicUnavailable) as raised:
            method(*args)
        chained = repr(raised.value) + repr(raised.value.__cause__)
        assert TOKEN not in chained


def test_gzip_is_requested_by_default_with_no_extra_header() -> None:
    """Spike 0001 asked for gzip explicitly; httpx's ``Client`` already sends
    ``Accept-Encoding: gzip, deflate`` by default, so this asserts the free behaviour rather than
    a header this module has to add."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[])

    upstream_returning(handler).fetch_cards(TOKEN, ["KAN-1"])

    assert "gzip" in seen[0].headers.get("accept-encoding", "")
