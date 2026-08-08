"""The introspection cache. Digests go in; raw tokens never do.

Two properties matter more than the caching, and both are ADR 0002's:

**Keys are `sha256(raw_token)`.** A heap dump, a `repr()` in a traceback, or a debugger session
must not yield a live credential. The digest is computed at the boundary of every public method
here, so no caller ever holds a key it could accidentally build from the raw value and store.

**A rejection is cached too, briefly.** Pandan gives kaya no way to tell a malformed token from a
revoked one, so kaya cannot cheaply reject a stray `Authorization` header the way a prefix check
would. The negative cache is what pandan's `startswith` guard was actually reaching for: it sheds
the load without needing to know a single thing about the token's shape.

The clock is injected. A TTL test that `sleep`s past a real 60 seconds is a slow test that will
eventually be a flaky one (dev-playbook §3).
"""

import hashlib
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from app.auth.principal import Principal

DEFAULT_MAX_ENTRIES = 4096
"""Bound on the cache, because the negative half is filled by *strangers*.

Anyone can make kaya cache an entry by sending an `Authorization` header. Unbounded, the
load-shedding mechanism becomes a memory leak driven by whoever is scanning the internet today.
"""


def digest(token: str) -> str:
    """The cache key for a token, and the only place a raw token is read in this module."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class _Entry:
    principal: Principal | None
    """``None`` is the negative cache: pandan was asked and said no."""

    expires_at: float


class PrincipalCache:
    """TTL cache of introspection answers, keyed on a digest. **Safe under concurrent use.**

    That last part is not decoration, and the earlier version of this docstring got it wrong in a
    way worth recording, because the reasoning was persuasive and still incorrect.

    It argued that the cache did not need a lock: every operation is a handful of dict mutations
    under the GIL, so the worst a race can do is two threads paying for the same upstream call —
    a wasted round trip, not a wrong answer. **That reasons about wrong answers and says nothing
    about raised exceptions.** `lookup` used to check `expires_at` and then `del` the key as two
    separate steps. Two threads could both pass the check and the second `del` would raise
    `KeyError`. `_evict` had the same shape twice over, plus a comprehension over `_entries` that
    another thread could resize underneath it.

    None of that is hypothetical here. `get_principal` is a sync `def` FastAPI dependency, so
    Starlette runs it in a threadpool, and this object is a process-wide singleton. The blast
    radius was a **500 from the auth dependency on a perfectly valid credential**, and it was
    reachable at every TTL boundary — which, for one agent holding one PAT and making many
    parallel calls, comes round every sixty seconds.

    So: one lock, held across every read and write of `_entries`. Two rules keep it honest.

    1. **Nothing injected is called while the lock is held.** The clock is read before the lock is
       taken, never inside it. A caller's clock is arbitrary code; blocking every other thread on
       it would trade a `KeyError` for a stall. The cost is that `now` can be a few microseconds
       stale by the time it is compared, so an entry may live a fraction past its expiry. Against
       a 60s TTL that is not a number anyone can observe.
    2. **`_evict` runs with the lock already held and never takes it.** ``threading.Lock`` is not
       reentrant, so a second acquire from inside `remember` would deadlock rather than fail
       loudly.

    Contention is not a concern: the critical section is a few dict operations with no I/O in it,
    and an uncontended acquire costs tens of nanoseconds against an upstream round trip measured
    in hundreds of milliseconds.
    """

    def __init__(
        self,
        *,
        positive_ttl: float,
        negative_ttl: float,
        clock: Callable[[], float] = time.monotonic,
        max_entries: int = DEFAULT_MAX_ENTRIES,
    ) -> None:
        self._positive_ttl = positive_ttl
        self._negative_ttl = negative_ttl
        # monotonic, not `time.time`: an NTP step backwards must not extend a revocation window.
        self._clock = clock
        self._max_entries = max_entries
        self._entries: dict[str, _Entry] = {}
        self._lock = threading.Lock()

    def lookup(self, token: str) -> tuple[bool, Principal | None]:
        """``(hit, principal)``.

        Three outcomes in two values, and the awkwardness is deliberate: ``(True, None)`` is a
        cached *rejection* and ``(False, None)`` is a miss. Collapsing them into a bare
        ``Principal | None`` would silently turn every negative-cache hit into an upstream call,
        which is the one thing the negative cache exists to prevent — and the test for it would
        still pass, because the answer would still be "rejected".
        """
        key = digest(token)
        now = self._clock()  # read before the lock — see rule 1 in the class docstring

        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return (False, None)
            if now >= entry.expires_at:
                # A plain `del` rather than a tolerant `pop(key, None)`, deliberately: the lock is
                # what makes this safe, and a defensive pop here would imply the lock is optional.
                del self._entries[key]
                return (False, None)
            return (True, entry.principal)

    def remember(self, token: str, principal: Principal | None) -> None:
        """Cache an answer. ``None`` records a rejection under the shorter negative TTL."""
        ttl = self._positive_ttl if principal is not None else self._negative_ttl
        key = digest(token)
        now = self._clock()

        with self._lock:
            # Re-insert rather than overwrite, so dict insertion order stays recency order.
            self._entries.pop(key, None)
            self._entries[key] = _Entry(principal=principal, expires_at=now + ttl)
            self._evict(now)

    def _evict(self, now: float) -> None:
        """Bring the cache back under its bound. **The caller holds ``_lock``.**

        ``now`` is passed in rather than read here, for both reasons in the class docstring: the
        lock is held, so no injected code may run; and re-reading would be a second clock call
        inside one logical operation.
        """
        if len(self._entries) <= self._max_entries:
            return
        # Safe to build a list from `_entries` and to iterate it only because the lock is held.
        # Unlocked, a concurrent insert here raises "dictionary changed size during iteration".
        for key in [k for k, entry in self._entries.items() if now >= entry.expires_at]:
            del self._entries[key]
        while len(self._entries) > self._max_entries:
            del self._entries[next(iter(self._entries))]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        """Live *and* expired entries — the storage size, not the logical size."""
        with self._lock:
            return len(self._entries)
