"""`TeamMembershipCache` — the same lock discipline as `PrincipalCache`
(`tests/unit/test_principal_cache.py`), so the tests that matter are the same shape: TTL split,
hit/miss/unknown distinguishability, and the entry-point lock guard that caught a real race once
already (`app/auth/cache.py`'s docstring). Not a full duplicate of every case there — the digest
function itself is imported, not reimplemented, so it is already covered by that suite.
"""

import threading

import pytest
from fakes import OTHER_TOKEN, TOKEN, FakeClock

from app.auth.team_cache import TeamMembershipCache

TEAM_A = frozenset({1})
TEAM_AB = frozenset({1, 2})


def make_cache(clock: FakeClock, **kwargs: float) -> TeamMembershipCache:
    return TeamMembershipCache(
        positive_ttl=kwargs.pop("positive_ttl", 60.0),
        negative_ttl=kwargs.pop("negative_ttl", 10.0),
        clock=clock,
        **kwargs,  # type: ignore[arg-type]
    )


def test_a_positive_entry_is_returned_until_its_ttl_elapses() -> None:
    clock = FakeClock()
    cache = make_cache(clock, positive_ttl=60.0)
    cache.remember(TOKEN, TEAM_A)

    clock.advance(59.9)
    assert cache.lookup(TOKEN) == (True, TEAM_A)

    clock.advance(0.1)
    assert cache.lookup(TOKEN) == (False, None)


def test_an_unknown_answer_expires_on_the_shorter_negative_ttl() -> None:
    """The "pandan could not be asked" case — this is load-shedding, not a remembered rejection."""
    clock = FakeClock()
    cache = make_cache(clock, positive_ttl=60.0, negative_ttl=10.0)
    cache.remember(TOKEN, None)

    clock.advance(9.9)
    assert cache.lookup(TOKEN) == (True, None)

    clock.advance(0.1)
    assert cache.lookup(TOKEN) == (False, None)


def test_a_cached_unknown_is_distinguishable_from_a_miss() -> None:
    """The whole reason ``lookup`` returns a pair, same argument as `PrincipalCache`'s: collapsing
    these two would make every "pandan could not be asked" cache hit look like a fresh miss and
    call pandan again — defeating the one thing the negative half exists to prevent."""
    cache = make_cache(FakeClock())
    cache.remember(TOKEN, None)

    assert cache.lookup(TOKEN) == (True, None)
    assert cache.lookup(OTHER_TOKEN) == (False, None)


@pytest.mark.parametrize("teams", [TEAM_A, TEAM_AB, frozenset(), None])
def test_remember_then_lookup_round_trips(teams: frozenset[int] | None) -> None:
    cache = make_cache(FakeClock())
    cache.remember(TOKEN, teams)
    assert cache.lookup(TOKEN) == (True, teams)


def test_an_expired_entry_is_dropped_rather_than_left_to_accumulate() -> None:
    clock = FakeClock()
    cache = make_cache(clock, positive_ttl=60.0)
    cache.remember(TOKEN, TEAM_A)

    clock.advance(61)
    cache.lookup(TOKEN)

    assert len(cache) == 0


def test_the_cache_is_bounded() -> None:
    clock = FakeClock()
    cache = make_cache(clock, negative_ttl=10.0, max_entries=8)

    for i in range(50):
        cache.remember(f"bearer-{i}", None)

    assert len(cache) <= 8


@pytest.mark.parametrize("operation", ["lookup", "remember", "clear", "len"])
def test_every_entry_point_waits_for_the_lock(operation: str) -> None:
    """Same guard as `PrincipalCache`'s, against the same class of bug — see that test's docstring
    for the full history. Reaching for the private `_lock` is the point, not a shortcut."""
    cache = make_cache(FakeClock())
    cache.remember(TOKEN, TEAM_A)

    operations = {
        "lookup": lambda: cache.lookup(TOKEN),
        "remember": lambda: cache.remember(OTHER_TOKEN, TEAM_AB),
        "clear": cache.clear,
        "len": lambda: len(cache),
    }

    entered = threading.Event()
    returned = threading.Event()

    def call_it() -> None:
        entered.set()
        operations[operation]()
        returned.set()

    caller = threading.Thread(target=call_it)
    with cache._lock:
        caller.start()
        assert entered.wait(timeout=5), "the caller thread never started"
        assert not returned.wait(timeout=0.25), (
            f"`{operation}` returned while another thread held the lock, so it touched _entries "
            "unguarded"
        )

    caller.join(timeout=5)
    assert returned.is_set(), "the operation never completed once the lock was released"
