"""One upstream call per key, however many callers want the same answer.

This exists because of a number, not because duplicate work is untidy. `cache.py`'s docstring used
to shrug the race off — "the worst a race can do is two threads paying for the same upstream call"
— and at KAN-539's warm miss of 387 ms that was true and cheap. KAN-666 measured the cold miss at
tens of seconds, and at that scale the same sentence describes an outage.

The arithmetic that makes it one. `get_principal` is a sync `def` FastAPI dependency, so Starlette
runs it in a threadpool of 40. A cold pandan holds each thread for the whole read budget. Forty
concurrent requests carrying one uncached PAT — one agent starting work, which is kaya's *normal*
opening move — take all forty workers and hold them, and every unrelated request behind them,
including a note **save** that needs nothing from pandan at all, waits. That is the coupling ADR
0003 forbids, arriving as resource exhaustion rather than as a timeout, which is the shape ADR 0003
calls out specifically because it does not degrade gracefully. Coalescing turns forty held workers
into one held worker and thirty-nine parked on an `Event`, which is the difference between a slow
first request and a stalled service. It is what makes ADR 0002's long read budget affordable.

**The lock here is not the cache's lock, and neither is ever held across the upstream call.**
`cache.py` records the reasoning that made its own lock necessary and the two rules that keep it
honest; this module has one rule and it is the same idea:

    Nothing injected runs while `_lock` is held.

`_lock` covers a `dict.get`, a `dict` insert and a `dict` delete, and nothing else. `work` — a
network round trip that can take half a minute — runs with the lock released. Holding it across
that call would serialise *every* token's introspection behind whichever one is currently slowest,
turning a fix for a stampede into a global chokepoint, and it would do it while looking correct.

**Keys are digests.** Callers pass `sha256(raw_token)` for the same reason the cache stores it
(ADR 0002): nothing reachable from a long-lived object may be a live credential. The raw token
lives only inside the caller's closure, for the duration of one call, and never in this object.
"""

import threading
from collections.abc import Callable


class _Call:
    """One in-flight piece of work, and a place to put whatever came of it."""

    __slots__ = ("done", "error", "result")

    def __init__(self) -> None:
        self.done = threading.Event()
        self.result: object = None
        self.error: BaseException | None = None
        # `result` is not a sentinel for "no answer yet" and must not be read as one: `None` is a
        # *legitimate* result here — it is ADR 0002's cached rejection. `error` is the only
        # discriminator, and `done` is the only readiness signal.


class SingleFlight:
    """Deduplicates concurrent calls by key. **Safe under concurrent use.**"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._in_flight: dict[str, _Call] = {}

    def do[T](self, key: str, work: Callable[[], T]) -> T:
        """Run `work`, or wait for the `work` another thread is already running under this key.

        Every caller gets the same outcome — the same return value, or the same exception. That
        second half is load-bearing rather than symmetric-for-neatness: if the leader's
        introspection raises `UpstreamUnavailable` and the waiters were handed `None` instead, an
        outage would surface to thirty-nine callers as `401 invalid_token`, which is exactly the Q9
        bug ADR 0002 spends a whole section forbidding. Waiters must fail the way the leader failed.
        """
        with self._lock:
            existing = self._in_flight.get(key)
            if existing is not None:
                call, leading = existing, False
            else:
                call, leading = _Call(), True
                self._in_flight[key] = call

        if not leading:
            # No timeout, and it cannot hang: the leader's `finally` below sets `done` on *every*
            # exit including `BaseException`, so the only way to wait forever is a process that has
            # already stopped running the leader's frame at all.
            call.done.wait()
            if call.error is not None:
                # The leader's exception object, re-raised — the same thing
                # `concurrent.futures.Future.result()` does, for the same reason: a fresh exception
                # would lose the `__cause__` chain that says *why* pandan could not be reached.
                raise call.error
            return call.result  # type: ignore[return-value]

        try:
            call.result = work()
            return call.result  # type: ignore[return-value]
        except BaseException as exc:
            call.error = exc
            raise
        finally:
            with self._lock:
                # Retired *before* `done` is set, and only if it is still ours. A caller arriving
                # after this delete starts a fresh call rather than joining a finished one — which
                # is the whole difference between coalescing and caching, and getting the order
                # wrong the other way round would hand a later request an answer from a round trip
                # that had already completed.
                if self._in_flight.get(key) is call:
                    del self._in_flight[key]
            call.done.set()

    def __len__(self) -> int:
        """Calls currently in flight. Zero at rest — this holds nothing between calls."""
        with self._lock:
            return len(self._in_flight)
