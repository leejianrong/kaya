"""Concurrent misses for one token cost one upstream call, and share its outcome (KAN-666).

Every test here stages the interleaving with an `Event` or a `Barrier` and never with a `sleep`.
That is not stylistic. The property under test is "N threads made 1 call", and the *natural* way to
write it — start N threads, join, count — passes on a machine where the scheduler happened to
serialise them even with the coalescing removed entirely. A concurrency test that can pass for the
wrong reason is worse than no test, because it is also the thing people trust when reviewing a
change to the locking.

The one place a wall-clock number appears is a 250 ms *negative* window ("this has not returned
yet"), which is the same idiom `test_principal_cache.py` uses on the cache's lock. It cannot make a
broken implementation pass: a thread that failed to coalesce records its call *before* it parks, so
the assertion that follows the window sees it.
"""

import threading
from collections.abc import Callable

import pytest
from fakes import ALICE, BOB

from app.auth.principal import UpstreamUnavailable
from app.auth.single_flight import SingleFlight

KEY = "a-sha256-digest-shaped-string-standing-in-for-one"
OTHER_KEY = "a-sha256-digest-shaped-string-standing-in-for-two"


class StagedWork:
    """Work that parks inside itself until the test lets it out, and records every entry.

    `entered` fires on the *first* call; `calls` counts all of them. A second caller that failed to
    coalesce appends to `calls` before it blocks, so it is visible while the leader is still parked
    rather than only after the test tears down.
    """

    def __init__(self, result: object = ALICE, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[int] = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self._lock = threading.Lock()

    def __call__(self) -> object:
        with self._lock:
            self.calls.append(threading.get_ident())
        self.entered.set()
        assert self.release.wait(timeout=10), "the test never released the staged work"
        if self.error is not None:
            raise self.error
        return self.result

    @property
    def call_count(self) -> int:
        with self._lock:
            return len(self.calls)


def run_concurrently(
    count: int, target: Callable[[], None]
) -> tuple[list[threading.Thread], threading.Semaphore]:
    """`count` threads that rendezvous on a barrier, then all run `target` at once.

    Returns the threads and a semaphore released once per thread the instant it clears the barrier,
    so a test can wait for "everyone is about to call" rather than guessing at it with a sleep.
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


# --- The property the card asks for -------------------------------------------------------------


def test_n_concurrent_misses_for_one_key_make_exactly_one_call() -> None:
    """The acceptance criterion, and the reason the 30 s read budget is affordable at all.

    Without this, forty threadpool workers each hold a cold pandan's full read budget and note
    *saving* stalls behind an upstream that notes do not need — ADR 0003's rule, broken from inside
    kaya by resource exhaustion rather than by a timeout.
    """
    workers = 12
    flight = SingleFlight()
    work = StagedWork()
    results: list[object] = []
    results_lock = threading.Lock()
    anyone_finished = threading.Event()

    def call() -> None:
        answer = flight.do(KEY, work)
        with results_lock:
            results.append(answer)
        anyone_finished.set()

    threads, at_the_gate = run_concurrently(workers, call)

    assert work.entered.wait(timeout=10), "nobody ever entered the work"
    for _ in range(workers):
        assert at_the_gate.acquire(timeout=10), "a thread never reached the call"

    # The leader is parked inside the work and stays there until this test says otherwise, so there
    # is no deadline the others have to meet — they simply have to arrive, and the semaphore above
    # says they have. The window is a *negative* assertion and nothing hangs on its length.
    assert not anyone_finished.wait(timeout=0.25), (
        "a caller returned while the one in-flight call was still parked, so it did not wait for it"
    )
    assert work.call_count == 1, (
        f"{work.call_count} threads entered the upstream call for one key; the other "
        f"{workers - 1} were supposed to be parked on the first one's result"
    )

    work.release.set()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()

    assert work.call_count == 1, "a straggler started a second call for a key already in flight"
    assert results == [ALICE] * workers, "every caller gets the one answer, not just the leader"
    assert len(flight) == 0, "the registry kept an entry after the call finished"


def test_a_failing_call_fails_every_waiter() -> None:
    """Q9, at the point it is easiest to lose.

    A waiter handed `None` instead of the leader's exception would have its request answered `401
    invalid_token` — kaya telling thirty-nine callers their credential is bad because pandan was
    asleep. `SingleFlight` must propagate the failure, and it must propagate *this* failure, so the
    `503`'s message still names the upstream that could not be reached.
    """
    workers = 8
    flight = SingleFlight()
    boom = UpstreamUnavailable("https://pandan.invalid/api/v1/me is unreachable")
    work = StagedWork(error=boom)
    seen: list[BaseException] = []
    seen_lock = threading.Lock()
    anyone_finished = threading.Event()

    def call() -> None:
        try:
            flight.do(KEY, work)
        except BaseException as exc:  # noqa: BLE001 — the point is that *something* propagates
            with seen_lock:
                seen.append(exc)
        anyone_finished.set()

    threads, at_the_gate = run_concurrently(workers, call)

    assert work.entered.wait(timeout=10)
    for _ in range(workers):
        assert at_the_gate.acquire(timeout=10)
    assert not anyone_finished.wait(timeout=0.25)

    work.release.set()
    for thread in threads:
        thread.join(timeout=10)

    assert work.call_count == 1
    assert len(seen) == workers, (
        "a waiter returned instead of raising — an outage that reaches a caller as a rejection is "
        "the Q9 bug, and it is silent"
    )
    assert all(exc is boom for exc in seen), (
        "waiters must see the leader's own failure, so the 503 body still names the upstream"
    )
    assert len(flight) == 0, "a failed call left its entry behind and would wedge the next caller"


def test_a_result_of_none_travels_as_a_result_and_not_as_a_failure() -> None:
    """`None` is ADR 0002's *rejection*, which is an answer. Only an outage is an error.

    Written because the obvious `if self.result is None: still running` implementation of a
    single-flight registry collapses these two, and the failure is invisible: every caller would
    still be rejected, just after an upstream call each.
    """
    flight = SingleFlight()
    work = StagedWork(result=None)
    results: list[object] = []
    finished = threading.Event()

    def call() -> None:
        results.append(flight.do(KEY, work))
        finished.set()

    threads, at_the_gate = run_concurrently(4, call)
    assert work.entered.wait(timeout=10)
    for _ in range(4):
        assert at_the_gate.acquire(timeout=10)
    assert not finished.wait(timeout=0.25)
    work.release.set()
    for thread in threads:
        thread.join(timeout=10)

    assert work.call_count == 1
    assert results == [None] * 4


# --- What it must *not* do ----------------------------------------------------------------------


def test_a_different_key_is_not_held_up_behind_an_in_flight_one() -> None:
    """The lock covers a dict, never the work — otherwise this is a global chokepoint.

    Hold `_lock` across `work()` and every token's introspection queues behind whichever one is
    currently slowest, which on a cold pandan is a 30 s stall for callers whose principal is not
    even involved. The bug would look like a fix, and this is the test that tells them apart.
    """
    flight = SingleFlight()
    blocked = StagedWork()
    unrelated_done = threading.Event()
    unrelated: list[object] = []

    leader = threading.Thread(target=lambda: flight.do(KEY, blocked), daemon=True)
    leader.start()
    assert blocked.entered.wait(timeout=10), "the leader never reached the work"

    def other() -> None:
        unrelated.append(flight.do(OTHER_KEY, lambda: BOB))
        unrelated_done.set()

    passerby = threading.Thread(target=other, daemon=True)
    passerby.start()

    assert unrelated_done.wait(timeout=5), (
        "a call under a different key waited for an unrelated in-flight call, so the lock is being "
        "held across the work"
    )
    assert unrelated == [BOB]

    blocked.release.set()
    leader.join(timeout=10)


def test_a_caller_arriving_after_the_call_finished_starts_a_fresh_one() -> None:
    """Coalescing, not caching. The TTL is `PrincipalCache`'s job and stays there (Q6).

    Retire the entry *after* `done` is set and this fails: the second caller would join a completed
    call and be handed an answer from a round trip that finished before it ever asked.
    """
    flight = SingleFlight()
    calls: list[int] = []

    def work() -> object:
        calls.append(1)
        return ALICE

    assert flight.do(KEY, work) == ALICE
    assert flight.do(KEY, work) == ALICE

    assert len(calls) == 2
    assert len(flight) == 0


def test_the_registry_holds_nothing_between_calls() -> None:
    """It is keyed on a digest and it still must not accumulate.

    `PrincipalCache` is bounded because strangers fill its negative half; this needs no bound only
    because it is empty at rest. If an entry ever outlived its call, an `Authorization` header per
    request would be an unbounded dict — the same leak, in the module that thought it was exempt.
    """
    flight = SingleFlight()
    for i in range(200):
        flight.do(f"stray-header-{i}", lambda: None)
        with pytest.raises(UpstreamUnavailable):
            flight.do(f"stray-header-{i}", _raise)

    assert len(flight) == 0


def _raise() -> object:
    raise UpstreamUnavailable("https://pandan.invalid/api/v1/me is unreachable")


def test_the_lock_is_not_held_while_the_work_runs() -> None:
    """Asserted directly rather than inferred, so a refactor that widens the lock fails here.

    The mirror of `test_principal_cache.py`'s mutual-exclusion test, pointed the other way: there
    the property was "this method waits for the lock", here it is "this method releases it".
    """
    flight = SingleFlight()
    lock_was_free: list[bool] = []

    def work() -> object:
        lock_was_free.append(flight._lock.acquire(blocking=False))
        if lock_was_free[-1]:
            flight._lock.release()
        return ALICE

    flight.do(KEY, work)

    assert lock_was_free == [True], (
        "`_lock` was held while the upstream call ran; every other token's introspection would "
        "queue behind this one"
    )
