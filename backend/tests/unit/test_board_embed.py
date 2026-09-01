"""``BoardEmbedResolver``, against an in-memory fake upstream — KAN-1049.

Unlike ``test_card_resolution.py``, there is no cache and no call-count budget to prove; what
matters here is the two request shapes (``column`` is one call, ``view`` is two, in order) and that
every failure — at either step — collapses to ``unavailable`` rather than a partial or wrong
answer, per ``board_embed.py``'s module docstring.
"""

from typing import Any

import pytest
from fakes import TOKEN

from app.integrations.board_embed import (
    BoardEmbedCard,
    BoardEmbedResolver,
    BoardEmbedUnavailable,
)

KAN_1 = BoardEmbedCard(ref="KAN-1", title="First", column="todo")
KAN_2 = BoardEmbedCard(ref="KAN-2", title="Second", column="done")


class FakeBoardEmbedUpstream:
    """A ``BoardEmbedUpstream`` backed by canned answers, counting every call."""

    def __init__(self) -> None:
        self.view_queries: dict[tuple[int, int], dict[str, Any]] = {}
        self.cards_by_params: dict[tuple[int, tuple[tuple[str, Any], ...]], tuple[Any, ...]] = {}
        self.view_calls: list[tuple[str, int, int]] = []
        self.card_calls: list[tuple[str, int, dict[str, Any]]] = []
        self.view_available = True
        self.cards_available = True

    def fetch_view_query(self, bearer: str, board_id: int, view_id: int) -> dict[str, Any]:
        self.view_calls.append((bearer, board_id, view_id))
        if not self.view_available:
            raise BoardEmbedUnavailable("https://pandan.invalid/boards/1/views/1 answered 403")
        return self.view_queries.get((board_id, view_id), {})

    def fetch_cards(self, bearer: str, board_id: int, params: dict[str, Any]) -> tuple[Any, ...]:
        self.card_calls.append((bearer, board_id, params))
        if not self.cards_available:
            raise BoardEmbedUnavailable("https://pandan.invalid/api/v1/cards answered 500")
        key = (board_id, tuple(sorted(params.items())))
        return self.cards_by_params.get(key, ())


@pytest.fixture
def upstream() -> FakeBoardEmbedUpstream:
    return FakeBoardEmbedUpstream()


@pytest.fixture
def resolver(upstream: FakeBoardEmbedUpstream) -> BoardEmbedResolver:
    return BoardEmbedResolver(upstream)


# --- column queries ---------------------------------------------------------------------------


def test_a_column_query_is_one_call_straight_to_cards(
    resolver: BoardEmbedResolver, upstream: FakeBoardEmbedUpstream
) -> None:
    upstream.cards_by_params[(18, (("column", "todo"),))] = (KAN_1,)

    result = resolver.resolve(TOKEN, 18, column="todo")

    assert result.unavailable is False
    assert result.cards == (KAN_1,)
    assert upstream.view_calls == []
    assert upstream.card_calls == [(TOKEN, 18, {"column": "todo"})]


def test_a_column_query_degrades_to_unavailable_when_cards_fails(
    resolver: BoardEmbedResolver, upstream: FakeBoardEmbedUpstream
) -> None:
    upstream.cards_available = False

    result = resolver.resolve(TOKEN, 18, column="todo")

    assert result.unavailable is True
    assert result.cards == ()


# --- view queries -------------------------------------------------------------------------------


def test_a_view_query_reads_the_view_then_replays_it_against_cards(
    resolver: BoardEmbedResolver, upstream: FakeBoardEmbedUpstream
) -> None:
    upstream.view_queries[(18, 3)] = {"column": "done", "priority": "high"}
    upstream.cards_by_params[(18, (("column", "done"), ("priority", "high")))] = (KAN_1, KAN_2)

    result = resolver.resolve(TOKEN, 18, view_id=3)

    assert result.unavailable is False
    assert result.cards == (KAN_1, KAN_2)
    assert upstream.view_calls == [(TOKEN, 18, 3)]
    assert upstream.card_calls == [(TOKEN, 18, {"column": "done", "priority": "high"})]


def test_a_view_query_degrades_to_unavailable_when_the_view_fetch_fails(
    resolver: BoardEmbedResolver, upstream: FakeBoardEmbedUpstream
) -> None:
    """A 403/404 reading the view — the caller cannot see this board, or the view does not exist —
    never reaches the cards call at all."""
    upstream.view_available = False

    result = resolver.resolve(TOKEN, 18, view_id=3)

    assert result.unavailable is True
    assert result.cards == ()
    assert upstream.card_calls == []


def test_a_view_query_degrades_to_unavailable_when_the_cards_fetch_fails(
    resolver: BoardEmbedResolver, upstream: FakeBoardEmbedUpstream
) -> None:
    upstream.view_queries[(18, 3)] = {}
    upstream.cards_available = False

    result = resolver.resolve(TOKEN, 18, view_id=3)

    assert result.unavailable is True
    assert result.cards == ()


def test_an_empty_result_set_is_not_unavailable(
    resolver: BoardEmbedResolver, upstream: FakeBoardEmbedUpstream
) -> None:
    """A saved view or column with zero matching cards is a legitimate `200`, not a degradation —
    the wire response looks identical (`cards: []`) but this is the boundary that must not conflate
    the two internally, since a future caller of `BoardEmbedResolver` might care."""
    result = resolver.resolve(TOKEN, 18, column="backlog")

    assert result.unavailable is False
    assert result.cards == ()
