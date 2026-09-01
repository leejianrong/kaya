"""``GET /api/v1/embeds/board`` end to end against a bare app — KAN-1049.

No database and no real pandan: `app.integrations.dependencies.get_board_embed_resolver` is
overridden with an in-memory fake, the same technique `test_meta.py` uses for `app.main.app`
directly. This route needs no `DATABASE_URL` and no Postgres fixture at all (see
`app/api/embeds.py`'s module docstring for why), so it lives in the fast, no-infrastructure layer
rather than beside `test_note_links_api.py` in `tests/integration/`.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from fakes import TOKEN
from fastapi.testclient import TestClient

from app.integrations.board_embed import BoardEmbedCard, BoardEmbedResult
from app.integrations.dependencies import get_board_embed_resolver
from app.main import app

BOARD_EMBED = "/api/v1/embeds/board"


class FakeBoardEmbedResolver:
    """A `BoardEmbedResolver`, answering a canned result and recording every call it saw."""

    def __init__(self) -> None:
        self.result = BoardEmbedResult(unavailable=False, cards=())
        self.calls: list[tuple[str, int, int | None, str | None]] = []

    def resolve(
        self, bearer: str, board_id: int, *, view_id: int | None = None, column: str | None = None
    ) -> BoardEmbedResult:
        self.calls.append((bearer, board_id, view_id, column))
        return self.result


@pytest.fixture
def resolver() -> FakeBoardEmbedResolver:
    return FakeBoardEmbedResolver()


@pytest.fixture
def client(resolver: FakeBoardEmbedResolver) -> Iterator[TestClient]:
    app.dependency_overrides[get_board_embed_resolver] = lambda: resolver
    try:
        yield TestClient(app)
    finally:
        del app.dependency_overrides[get_board_embed_resolver]


def error(response: Any) -> dict[str, Any]:
    return response.json()["error"]


def bearer(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- the happy paths --------------------------------------------------------------------------


def test_a_column_query_returns_the_resolved_cards(
    client: TestClient, resolver: FakeBoardEmbedResolver
) -> None:
    resolver.result = BoardEmbedResult(
        unavailable=False,
        cards=(BoardEmbedCard(ref="KAN-1", title="First", column="todo"),),
    )

    response = client.get(f"{BOARD_EMBED}?board=18&column=todo", headers=bearer())

    assert response.status_code == 200
    assert response.json() == {
        "unavailable": False,
        "cards": [{"ref": "KAN-1", "title": "First", "column": "todo"}],
    }
    assert resolver.calls == [(TOKEN, 18, None, "todo")]


def test_a_view_query_forwards_the_view_id_not_a_column(
    client: TestClient, resolver: FakeBoardEmbedResolver
) -> None:
    response = client.get(f"{BOARD_EMBED}?board=18&view=3", headers=bearer())

    assert response.status_code == 200
    assert resolver.calls == [(TOKEN, 18, 3, None)]


def test_an_unavailable_result_is_still_a_200(
    client: TestClient, resolver: FakeBoardEmbedResolver
) -> None:
    """Q26/ADR 0003's rendering-not-an-error contract, one route over from `/links`: pandan being
    down, or the caller lacking access to this board, is a decoration going missing, not a
    refusal."""
    resolver.result = BoardEmbedResult(unavailable=True, cards=())

    response = client.get(f"{BOARD_EMBED}?board=18&column=todo", headers=bearer())

    assert response.status_code == 200
    assert response.json() == {"unavailable": True, "cards": []}


def test_the_caller_own_bearer_is_forwarded_verbatim(
    client: TestClient, resolver: FakeBoardEmbedResolver
) -> None:
    """ADR 0002: never a kaya-owned credential."""
    client.get(f"{BOARD_EMBED}?board=18&column=todo", headers=bearer("a-different-caller-token"))

    assert resolver.calls[0][0] == "a-different-caller-token"


# --- validation --------------------------------------------------------------------------------


def test_missing_board_is_a_422(client: TestClient) -> None:
    response = client.get(f"{BOARD_EMBED}?column=todo", headers=bearer())

    assert response.status_code == 422
    assert error(response)["code"] == "invalid_request"


def test_a_non_numeric_board_is_a_422(client: TestClient) -> None:
    response = client.get(f"{BOARD_EMBED}?board=not-a-number&column=todo", headers=bearer())

    assert response.status_code == 422


def test_neither_view_nor_column_is_a_422(client: TestClient) -> None:
    response = client.get(f"{BOARD_EMBED}?board=18", headers=bearer())

    assert response.status_code == 422
    assert error(response)["code"] == "invalid_request"
    assert "view" in error(response)["message"]
    assert "column" in error(response)["message"]


def test_both_view_and_column_is_a_422(client: TestClient) -> None:
    response = client.get(f"{BOARD_EMBED}?board=18&view=3&column=todo", headers=bearer())

    assert response.status_code == 422
    assert error(response)["code"] == "invalid_request"


def test_a_malformed_query_makes_no_upstream_call(
    client: TestClient, resolver: FakeBoardEmbedResolver
) -> None:
    client.get(f"{BOARD_EMBED}?board=18", headers=bearer())

    assert resolver.calls == []


# --- authentication ---------------------------------------------------------------------------


def test_no_bearer_is_a_401(client: TestClient, resolver: FakeBoardEmbedResolver) -> None:
    response = client.get(f"{BOARD_EMBED}?board=18&column=todo")

    assert response.status_code == 401
    assert error(response)["code"] == "authentication_required"
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert resolver.calls == []


def test_a_bearer_pandan_would_reject_is_not_kayas_401(
    client: TestClient, resolver: FakeBoardEmbedResolver
) -> None:
    """Kaya does not introspect the token itself here (see `app/api/embeds.py`'s module docstring):
    a bearer of any shape reaches the resolver, which is the one that would find out from pandan
    whether it is any good — and if it is not, that surfaces as `unavailable`, not a kaya `401`."""
    resolver.result = BoardEmbedResult(unavailable=True, cards=())

    response = client.get(
        f"{BOARD_EMBED}?board=18&column=todo",
        headers=bearer("garbage-pandan-has-never-seen"),
    )

    assert response.status_code == 200
    assert response.json()["unavailable"] is True
    assert resolver.calls == [("garbage-pandan-has-never-seen", 18, None, "todo")]


def test_documented_in_the_openapi_schema(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    assert "/api/v1/embeds/board" in schema["paths"]
