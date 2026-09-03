"""ADR 0011's soft-fail decision, end to end, with pandan faked at its seam.

The load-bearing property of this whole file is the one `test_principal_resolver.py` never has to
prove: **an outage never reaches the caller as an exception.** Where identity's resolver turns
`UpstreamUnavailable` into a `503`, `TeamAccessResolver.member_of` always returns — an empty
`frozenset` on failure, exactly as ADR 0011, Fork 3 decided.
"""

import threading
from collections.abc import Callable

import pytest
from fakes import OTHER_TOKEN, TOKEN, FakeClock, FakeTeamUpstream

from app.auth.principal import UpstreamUnavailable
from app.auth.single_flight import SingleFlight
from app.auth.team_cache import TeamMembershipCache, digest
from app.auth.team_resolver import TeamAccessResolver

TEAM_A = frozenset({1})
TEAM_AB = frozenset({1, 2})


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def upstream() -> FakeTeamUpstream:
    return FakeTeamUpstream({TOKEN: TEAM_A})


@pytest.fixture
def resolver(clock: FakeClock, upstream: FakeTeamUpstream) -> TeamAccessResolver:
    return TeamAccessResolver(
        upstream=upstream,
        cache=TeamMembershipCache(positive_ttl=60.0, negative_ttl=10.0, clock=clock),
        single_flight=SingleFlight(),
    )


# --- The happy path -------------------------------------------------------------------------


def test_a_cache_miss_asks_pandan(resolver: TeamAccessResolver, upstream: FakeTeamUpstream) -> None:
    assert resolver.member_of(TOKEN) == TEAM_A
    assert upstream.calls == [TOKEN]


def test_a_second_request_costs_no_round_trip(
    resolver: TeamAccessResolver, upstream: FakeTeamUpstream
) -> None:
    resolver.member_of(TOKEN)
    resolver.member_of(TOKEN)
    resolver.member_of(TOKEN)

    assert upstream.call_count == 1


def test_zero_teams_is_a_legitimate_cached_answer(
    resolver: TeamAccessResolver, upstream: FakeTeamUpstream
) -> None:
    assert resolver.member_of(OTHER_TOKEN) == frozenset()
    assert resolver.member_of(OTHER_TOKEN) == frozenset()
    assert upstream.call_count == 1, "an empty set is not a miss and must not re-ask pandan"


def test_the_cached_answer_lapses_after_the_positive_ttl(
    resolver: TeamAccessResolver, clock: FakeClock, upstream: FakeTeamUpstream
) -> None:
    resolver.member_of(TOKEN)
    clock.advance(59)
    resolver.member_of(TOKEN)
    assert upstream.call_count == 1

    clock.advance(2)
    resolver.member_of(TOKEN)
    assert upstream.call_count == 2


def test_membership_changes_are_picked_up_once_the_ttl_lapses(
    resolver: TeamAccessResolver, clock: FakeClock, upstream: FakeTeamUpstream
) -> None:
    assert resolver.member_of(TOKEN) == TEAM_A

    upstream.known[TOKEN] = TEAM_AB
    clock.advance(61)

    assert resolver.member_of(TOKEN) == TEAM_AB


# --- Pandan down: the soft-fail decision itself ---------------------------------------------


def test_an_unreachable_pandan_on_a_miss_is_an_empty_set_not_an_exception(
    resolver: TeamAccessResolver, upstream: FakeTeamUpstream
) -> None:
    upstream.available = False

    assert resolver.member_of(TOKEN) == frozenset()


def test_an_outage_is_cached_briefly_so_it_does_not_retry_every_call(
    resolver: TeamAccessResolver, clock: FakeClock, upstream: FakeTeamUpstream
) -> None:
    upstream.available = False
    resolver.member_of(TOKEN)
    resolver.member_of(TOKEN)
    assert upstream.call_count == 1, "load-shedding: a blip must not become a call per request"

    clock.advance(11)
    upstream.available = True
    assert resolver.member_of(TOKEN) == TEAM_A, "the outage entry lapses on the negative TTL"


def test_an_already_cached_answer_keeps_working_while_pandan_is_down(
    resolver: TeamAccessResolver, upstream: FakeTeamUpstream, clock: FakeClock
) -> None:
    assert resolver.member_of(TOKEN) == TEAM_A

    upstream.available = False
    clock.advance(30)

    assert resolver.member_of(TOKEN) == TEAM_A, "a live positive entry is not gated on pandan"
    assert upstream.call_count == 1


def test_no_upstream_unavailable_ever_escapes_member_of(
    resolver: TeamAccessResolver, upstream: FakeTeamUpstream
) -> None:
    """The property the whole file exists to check, stated directly."""
    upstream.available = False
    try:
        resolver.member_of(TOKEN)
    except UpstreamUnavailable:
        pytest.fail("ADR 0011's soft-fail decision was bypassed: UpstreamUnavailable escaped")


# --- A stampede on one bearer (mirrors KAN-666's coalescing proof) ---------------------------


class BlockingTeamUpstream(FakeTeamUpstream):
    """A ``FakeTeamUpstream`` that parks inside ``member_teams`` until the test releases it."""

    def __init__(self, known: dict[str, frozenset[int]] | None = None) -> None:
        super().__init__(known)
        self.entered = threading.Event()
        self.release = threading.Event()

    def member_teams(self, bearer: str) -> frozenset[int]:
        self.calls.append(bearer)
        self.entered.set()
        assert self.release.wait(timeout=10), "the test never released the upstream"
        if not self.available:
            raise UpstreamUnavailable("https://pandan.invalid/api/v1/teams is unreachable")
        return self.known.get(bearer, frozenset())


def stampede(count: int, target: Callable[[], None]) -> list[threading.Thread]:
    barrier = threading.Barrier(count)
    at_the_gate = threading.Semaphore(0)

    def body() -> None:
        barrier.wait(timeout=10)
        at_the_gate.release()
        target()

    threads = [threading.Thread(target=body, daemon=True) for _ in range(count)]
    for thread in threads:
        thread.start()
    for _ in range(count):
        assert at_the_gate.acquire(timeout=10)
    return threads


def test_forty_concurrent_misses_on_one_bearer_cost_one_round_trip() -> None:
    upstream = BlockingTeamUpstream({TOKEN: TEAM_A})
    resolver = TeamAccessResolver(
        upstream=upstream,
        cache=TeamMembershipCache(positive_ttl=60.0, negative_ttl=10.0, clock=FakeClock()),
        single_flight=SingleFlight(),
    )
    results: list[frozenset[int]] = []
    results_lock = threading.Lock()

    def call() -> None:
        result = resolver.member_of(TOKEN)
        with results_lock:
            results.append(result)

    threads = stampede(40, call)
    assert upstream.entered.wait(timeout=10)
    assert upstream.call_count == 1

    upstream.release.set()
    for thread in threads:
        thread.join(timeout=10)

    assert upstream.call_count == 1, (
        f"forty concurrent misses on one bearer made {upstream.call_count} calls to pandan"
    )
    assert results == [TEAM_A] * 40


def test_a_stampede_into_an_outage_returns_an_empty_set_for_every_caller() -> None:
    """The team-check analogue of Q9 under concurrency: every waiter must see the leader's
    soft-fail answer, not an exception the leader never raised past `_introspect` in the first
    place."""
    upstream = BlockingTeamUpstream({TOKEN: TEAM_A})
    upstream.available = False
    resolver = TeamAccessResolver(
        upstream=upstream,
        cache=TeamMembershipCache(positive_ttl=60.0, negative_ttl=10.0, clock=FakeClock()),
        single_flight=SingleFlight(),
    )
    results: list[frozenset[int]] = []
    results_lock = threading.Lock()

    def call() -> None:
        result = resolver.member_of(TOKEN)
        with results_lock:
            results.append(result)

    threads = stampede(12, call)
    assert upstream.entered.wait(timeout=10)
    assert upstream.call_count == 1

    upstream.release.set()
    for thread in threads:
        thread.join(timeout=10)

    assert upstream.call_count == 1
    assert results == [frozenset()] * 12


def test_the_in_flight_registry_is_keyed_on_the_digest_and_not_the_bearer() -> None:
    upstream = BlockingTeamUpstream({TOKEN: TEAM_A})
    single_flight = SingleFlight()
    resolver = TeamAccessResolver(
        upstream=upstream,
        cache=TeamMembershipCache(positive_ttl=60.0, negative_ttl=10.0, clock=FakeClock()),
        single_flight=single_flight,
    )

    caller = threading.Thread(target=lambda: resolver.member_of(TOKEN), daemon=True)
    caller.start()
    assert upstream.entered.wait(timeout=10)

    keys = list(single_flight._in_flight)

    upstream.release.set()
    caller.join(timeout=10)

    assert keys == [digest(TOKEN)]
    assert sum(1 for key in keys if TOKEN in key) == 0


def test_a_leader_that_arrived_late_uses_the_answer_instead_of_asking_again() -> None:
    """The double-check in `_introspect` — same reasoning as `PrincipalResolver`'s own."""
    upstream = FakeTeamUpstream({TOKEN: TEAM_A})
    resolver = TeamAccessResolver(
        upstream=upstream,
        cache=TeamMembershipCache(positive_ttl=60.0, negative_ttl=10.0, clock=FakeClock()),
        single_flight=SingleFlight(),
    )

    assert resolver.member_of(TOKEN) == TEAM_A
    assert upstream.call_count == 1

    assert resolver._introspect(TOKEN) == TEAM_A
    assert upstream.call_count == 1
