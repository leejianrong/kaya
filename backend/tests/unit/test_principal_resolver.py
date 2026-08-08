"""ADR 0002's resolver, end to end, with pandan and Postgres both faked at their seams.

The assertions that carry the weight are the **call counts**, not the returned principals. A
resolver with a broken cache still returns the right answer every time; a resolver that re-mirrors
on every request still returns the right answer every time. Only "how many times did you ask
pandan" and "how many times did you touch the mirror" can tell those apart, which is the same
lesson KAN-560 wrote into V5's guard.
"""

import threading
from collections.abc import Callable

import pytest
from fakes import ALICE, BOB, OTHER_TOKEN, TOKEN, FakeClock, FakeMirror, FakeUpstream
from fastapi import HTTPException

from app.auth.cache import PrincipalCache, digest
from app.auth.principal import Principal, TokenRejected, UpstreamUnavailable
from app.auth.resolver import PrincipalResolver, principal_from_bearer
from app.auth.single_flight import SingleFlight


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def upstream() -> FakeUpstream:
    return FakeUpstream({TOKEN: ALICE})


@pytest.fixture
def mirror() -> FakeMirror:
    return FakeMirror()


@pytest.fixture
def resolver(clock: FakeClock, upstream: FakeUpstream, mirror: FakeMirror) -> PrincipalResolver:
    return PrincipalResolver(
        upstream=upstream,
        mirror=mirror,
        cache=PrincipalCache(positive_ttl=60.0, negative_ttl=10.0, clock=clock),
        single_flight=SingleFlight(),
    )


# --- The happy path, step by step ---------------------------------------------------------------


def test_a_cache_miss_asks_pandan_and_mirrors_the_answer(
    resolver: PrincipalResolver, upstream: FakeUpstream, mirror: FakeMirror
) -> None:
    assert resolver.resolve(TOKEN) == ALICE
    assert upstream.calls == [TOKEN], "the bearer is forwarded verbatim, not normalised"
    assert mirror.ensured == [ALICE]


def test_a_second_request_costs_neither_a_round_trip_nor_a_mirror_call(
    resolver: PrincipalResolver, upstream: FakeUpstream, mirror: FakeMirror
) -> None:
    resolver.resolve(TOKEN)
    resolver.resolve(TOKEN)
    resolver.resolve(TOKEN)

    assert upstream.call_count == 1
    assert len(mirror.ensured) == 1, "steady state is a dict lookup; it must not reach the database"


def test_the_cached_answer_lapses_after_the_positive_ttl(
    resolver: PrincipalResolver, clock: FakeClock, upstream: FakeUpstream
) -> None:
    """Q6's revocation lag, stated as a test so the number is not folklore."""
    resolver.resolve(TOKEN)
    clock.advance(59)
    resolver.resolve(TOKEN)
    assert upstream.call_count == 1

    clock.advance(2)
    resolver.resolve(TOKEN)
    assert upstream.call_count == 2


def test_a_revoked_token_stops_working_once_the_entry_expires(
    resolver: PrincipalResolver, clock: FakeClock, upstream: FakeUpstream
) -> None:
    assert resolver.resolve(TOKEN) == ALICE

    upstream.known.clear()  # the PAT is revoked in pandan mid-session

    clock.advance(59)
    assert resolver.resolve(TOKEN) == ALICE, "still cached — this lag is the accepted cost of Q6"

    clock.advance(2)
    with pytest.raises(TokenRejected):
        resolver.resolve(TOKEN)


# --- Rejection, and the negative cache ----------------------------------------------------------


def test_an_unknown_token_is_rejected_and_the_rejection_is_remembered(
    resolver: PrincipalResolver, upstream: FakeUpstream, mirror: FakeMirror
) -> None:
    """A stray ``Authorization`` header costs one round trip, then none for 10s."""
    for _ in range(5):
        with pytest.raises(TokenRejected):
            resolver.resolve(OTHER_TOKEN)

    assert upstream.call_count == 1, "the negative cache is the load-shedding, not a prefix check"
    assert mirror.ensured == [], "nothing pandan rejected may reach the user table"


def test_the_negative_cache_lapses_on_the_shorter_ttl(
    resolver: PrincipalResolver, clock: FakeClock, upstream: FakeUpstream
) -> None:
    """A token minted a second ago must not stay rejected for a full minute."""
    with pytest.raises(TokenRejected):
        resolver.resolve(OTHER_TOKEN)

    upstream.known[OTHER_TOKEN] = ALICE

    clock.advance(9)
    with pytest.raises(TokenRejected):
        resolver.resolve(OTHER_TOKEN)

    clock.advance(2)
    assert resolver.resolve(OTHER_TOKEN) == ALICE


# --- Pandan down ---------------------------------------------------------------------------------


def test_an_unreachable_pandan_on_a_miss_is_not_a_rejection(
    resolver: PrincipalResolver, upstream: FakeUpstream
) -> None:
    upstream.available = False

    with pytest.raises(UpstreamUnavailable):
        resolver.resolve(TOKEN)


def test_an_outage_is_never_cached(resolver: PrincipalResolver, upstream: FakeUpstream) -> None:
    """Caching an outage would turn a blip into a 10s denial for a perfectly good token."""
    upstream.available = False
    with pytest.raises(UpstreamUnavailable):
        resolver.resolve(TOKEN)

    upstream.available = True
    assert resolver.resolve(TOKEN) == ALICE


def test_an_already_cached_principal_keeps_working_while_pandan_is_down(
    resolver: PrincipalResolver, upstream: FakeUpstream, clock: FakeClock
) -> None:
    """ADR 0002 §Failure behaviour: an active session survives a pandan restart."""
    assert resolver.resolve(TOKEN) == ALICE

    upstream.available = False

    clock.advance(30)
    assert resolver.resolve(TOKEN) == ALICE
    assert upstream.call_count == 1


# --- The HTTP contract ---------------------------------------------------------------------------


def test_a_missing_bearer_is_a_401_naming_what_is_missing(resolver: PrincipalResolver) -> None:
    with pytest.raises(HTTPException) as raised:
        principal_from_bearer(None, resolver)

    assert raised.value.status_code == 401
    assert raised.value.detail["error"]["code"] == "authentication_required"
    assert (raised.value.headers or {})["WWW-Authenticate"] == "Bearer"


def test_a_rejected_token_is_a_401(resolver: PrincipalResolver) -> None:
    with pytest.raises(HTTPException) as raised:
        principal_from_bearer(OTHER_TOKEN, resolver)

    assert raised.value.status_code == 401
    assert raised.value.detail["error"]["code"] == "invalid_token"


def test_an_unreachable_pandan_is_a_503_that_names_the_upstream(
    resolver: PrincipalResolver, upstream: FakeUpstream
) -> None:
    """Q9, and the single most load-bearing status code in the slice.

    A `401` here would tell a client its credential is bad when the credential is fine, and send
    it into a token-rotation loop over an outage it cannot fix.
    """
    upstream.available = False

    with pytest.raises(HTTPException) as raised:
        principal_from_bearer(TOKEN, resolver)

    assert raised.value.status_code == 503
    assert raised.value.status_code != 401
    error = raised.value.detail["error"]
    assert error["code"] == "upstream_unavailable"
    assert error["upstream"] == "pandan"
    assert "pandan" in error["message"]


def test_no_error_body_or_header_ever_carries_the_token(
    resolver: PrincipalResolver, upstream: FakeUpstream
) -> None:
    """All three failure paths, one assertion: the credential does not come back out."""
    failures = []

    with pytest.raises(HTTPException) as missing:
        principal_from_bearer(None, resolver)
    failures.append(missing.value)

    with pytest.raises(HTTPException) as rejected:
        principal_from_bearer(OTHER_TOKEN, resolver)
    failures.append(rejected.value)

    upstream.available = False
    with pytest.raises(HTTPException) as unavailable:
        principal_from_bearer(TOKEN, resolver)
    failures.append(unavailable.value)

    assert [f.status_code for f in failures] == [401, 401, 503]

    for failure in failures:
        rendered = repr(failure.detail) + repr(failure.headers)
        assert TOKEN not in rendered
        assert OTHER_TOKEN not in rendered


def test_a_resolved_principal_is_returned_unwrapped(resolver: PrincipalResolver) -> None:
    assert principal_from_bearer(TOKEN, resolver) == ALICE


# --- A stampede on one token (KAN-666) ----------------------------------------------------------
#
# The tests above all run on one thread, and the resolver's most expensive path is the one that
# only happens on several. `test_single_flight.py` proves the registry coalesces; these prove the
# *resolver* is actually wired to it, which is a separate claim and the one that regresses when
# somebody inlines `_introspect` back into `resolve`.


class BlockingUpstream(FakeUpstream):
    """A ``FakeUpstream`` that parks inside ``introspect`` until the test lets it out.

    Staged rather than slow: a `sleep` long enough to win a race on a quiet laptop is a `sleep`
    short enough to lose one on a loaded CI box, and the test that results fails for reasons nobody
    can reproduce.
    """

    def __init__(self, known: dict[str, Principal] | None = None) -> None:
        super().__init__(known)
        self.entered = threading.Event()
        self.release = threading.Event()

    def introspect(self, bearer: str) -> Principal | None:
        # Recorded *before* parking, and that ordering is the whole point of overriding rather than
        # delegating to `super()`. `FakeUpstream` appends after it returns, which would leave
        # `call_count` at zero for as long as the leader is held — so a second thread that failed to
        # coalesce would be invisible during exactly the window the test exists to inspect.
        self.calls.append(bearer)
        self.entered.set()
        assert self.release.wait(timeout=10), "the test never released the upstream"

        if not self.available:
            raise UpstreamUnavailable("https://pandan.invalid/api/v1/me is unreachable")
        return self.known.get(bearer)


def stampede(
    count: int, target: Callable[[], None]
) -> tuple[list[threading.Thread], threading.Semaphore]:
    """`count` threads through a barrier, so they are all inside the resolver at once.

    Returns the threads and a semaphore released once per thread the moment it clears the barrier.
    Waiting on that semaphore `count` times before letting the blocked upstream go is the whole
    difference between a test and a coin flip: the leader retires its key the instant it returns, so
    a thread that has not yet reached the registry becomes a *new* leader and makes a second call.
    This test was written without the gate first, and failed roughly one run in five — recorded here
    because "it passed on my machine" is exactly how a concurrency test earns its place and then
    loses it.
    """
    barrier = threading.Barrier(count)
    at_the_gate = threading.Semaphore(0)

    def body() -> None:
        barrier.wait(timeout=10)
        at_the_gate.release()
        target()

    threads = [threading.Thread(target=body, daemon=True) for _ in range(count)]
    for thread in threads:
        thread.start()
    return threads, at_the_gate


def resolver_over(upstream: FakeUpstream, mirror: FakeMirror) -> PrincipalResolver:
    return PrincipalResolver(
        upstream=upstream,
        mirror=mirror,
        cache=PrincipalCache(positive_ttl=60.0, negative_ttl=10.0, clock=FakeClock()),
        single_flight=SingleFlight(),
    )


def test_forty_concurrent_misses_on_one_token_cost_one_round_trip_and_one_mirror_write() -> None:
    """The acceptance criterion of KAN-666, at the width Starlette's threadpool actually has.

    Forty is not a round number chosen for effect: it is `anyio`'s default threadpool size, so it is
    exactly how many sync `get_principal` dependencies can be in flight at once. Before coalescing,
    a cold pandan held every one of them for the full read budget and note *saving* queued behind an
    upstream that saving does not use — ADR 0003's rule, broken from inside kaya.
    """
    upstream = BlockingUpstream({TOKEN: ALICE})
    mirror = FakeMirror()
    resolver = resolver_over(upstream, mirror)
    results: list[Principal] = []
    results_lock = threading.Lock()
    anyone_finished = threading.Event()

    def call() -> None:
        principal = resolver.resolve(TOKEN)
        with results_lock:
            results.append(principal)
        anyone_finished.set()

    threads, at_the_gate = stampede(40, call)
    assert upstream.entered.wait(timeout=10), "nobody reached the upstream"
    for _ in range(40):
        assert at_the_gate.acquire(timeout=10), "a thread never reached `resolve`"
    # The leader is parked inside `introspect` and stays there until the line below, so the others
    # have no deadline to meet — only to arrive, which the semaphore above has just confirmed.
    assert not anyone_finished.wait(timeout=0.25), (
        "a caller returned while the one in-flight introspection was still parked"
    )
    assert upstream.call_count == 1, "a second thread started its own round trip"

    upstream.release.set()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()

    assert upstream.call_count == 1, (
        f"forty concurrent misses on one token made {upstream.call_count} calls to pandan; on a "
        "cold upstream that is forty threadpool workers held for the whole read budget"
    )
    assert mirror.ensured == [ALICE], "the waiters re-mirrored a row the leader had already written"
    assert results == [ALICE] * 40


def test_a_stampede_into_an_outage_is_a_503_for_every_caller_and_a_401_for_none() -> None:
    """Q9 under concurrency, which is the only place the single-flight could quietly break it.

    The dangerous failure is silent and asymmetric: the leader gets its `503` and the thirty-nine
    waiters get `401 invalid_token`, so most of a fleet is told to rotate a credential that is
    perfectly good — over an outage none of them caused.
    """
    upstream = BlockingUpstream({TOKEN: ALICE})
    upstream.available = False
    resolver = resolver_over(upstream, FakeMirror())
    statuses: list[int] = []
    statuses_lock = threading.Lock()
    anyone_finished = threading.Event()

    def call() -> None:
        try:
            principal_from_bearer(TOKEN, resolver)
            status = 200
        except HTTPException as exc:
            status = exc.status_code
        with statuses_lock:
            statuses.append(status)
        anyone_finished.set()

    threads, at_the_gate = stampede(12, call)
    assert upstream.entered.wait(timeout=10)
    for _ in range(12):
        assert at_the_gate.acquire(timeout=10), "a thread never reached `principal_from_bearer`"
    assert not anyone_finished.wait(timeout=0.25)
    assert upstream.call_count == 1

    upstream.release.set()
    for thread in threads:
        thread.join(timeout=10)

    assert upstream.call_count == 1
    assert statuses == [503] * 12, (
        "an outage reached a caller as something other than a 503; a waiter handed the leader's "
        "`None` instead of the leader's exception is exactly how that happens"
    )


def test_the_in_flight_registry_is_keyed_on_the_digest_and_not_the_bearer() -> None:
    """ADR 0002 again: nothing reachable from a process-wide object may be a live credential.

    Checked *while a call is in flight*, because the registry is empty at rest — asserting on it
    afterwards would be a guard that passes without ever looking at anything.
    """
    upstream = BlockingUpstream({TOKEN: ALICE})
    single_flight = SingleFlight()
    resolver = PrincipalResolver(
        upstream=upstream,
        mirror=FakeMirror(),
        cache=PrincipalCache(positive_ttl=60.0, negative_ttl=10.0, clock=FakeClock()),
        single_flight=single_flight,
    )

    caller = threading.Thread(target=lambda: resolver.resolve(TOKEN), daemon=True)
    caller.start()
    assert upstream.entered.wait(timeout=10)

    keys = list(single_flight._in_flight)

    upstream.release.set()
    caller.join(timeout=10)

    assert keys == [digest(TOKEN)]
    # Counted rather than printed: in production the offending value would be a live PAT, and a
    # pytest assertion message goes straight into a CI log.
    assert sum(1 for key in keys if TOKEN in key) == 0


def test_a_miss_on_another_token_is_not_queued_behind_an_in_flight_one() -> None:
    """Coalescing is per token. If it were global, one sleeping principal would stall everyone."""
    upstream = BlockingUpstream({TOKEN: ALICE, OTHER_TOKEN: BOB})
    single_flight = SingleFlight()
    blocked = PrincipalResolver(
        upstream=upstream,
        mirror=FakeMirror(),
        cache=PrincipalCache(positive_ttl=60.0, negative_ttl=10.0, clock=FakeClock()),
        single_flight=single_flight,
    )
    free = PrincipalResolver(
        upstream=FakeUpstream({OTHER_TOKEN: BOB}),
        mirror=FakeMirror(),
        cache=PrincipalCache(positive_ttl=60.0, negative_ttl=10.0, clock=FakeClock()),
        single_flight=single_flight,
    )

    stuck = threading.Thread(target=lambda: blocked.resolve(TOKEN), daemon=True)
    stuck.start()
    assert upstream.entered.wait(timeout=10)

    assert free.resolve(OTHER_TOKEN) == BOB, "a different token waited on an unrelated round trip"

    upstream.release.set()
    stuck.join(timeout=10)


def test_a_leader_that_arrived_late_uses_the_answer_instead_of_asking_again() -> None:
    """The double-check in `_introspect`, which no black-box test can reach.

    The window is real but microseconds wide: miss the cache, lose the race, and arrive at the
    registry after the winner has already retired its key. There is nothing left to coalesce with
    at that point, so the only thing standing between that thread and a second cold round trip is
    the second cache read. Called directly, because staging a microsecond is not a test.
    """
    upstream = FakeUpstream({TOKEN: ALICE})
    resolver = resolver_over(upstream, FakeMirror())

    assert resolver.resolve(TOKEN) == ALICE
    assert upstream.call_count == 1

    assert resolver._introspect(TOKEN) == ALICE

    assert upstream.call_count == 1, (
        "a late leader asked pandan for something already cached; on a cold upstream that is a "
        "second twenty-second round trip nobody needed"
    )
