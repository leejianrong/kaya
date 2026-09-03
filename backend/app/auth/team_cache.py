"""TTL cache of team-membership answers, keyed on a digest — the same shape as
`app/auth/cache.py`'s `PrincipalCache`, deliberately **not** shared with it.

Two reasons for a second class rather than making `PrincipalCache` generic. First, the two caches
answer different questions and decay to different things on a miss: `PrincipalCache`'s `None` is a
cached *rejection* (ADR 0002) and surfaces as a `401`; this cache's `None` is "pandan could not be
asked" and surfaces as ADR 0011's soft-fail — an *empty* membership set, never an error. Collapsing
the two into one generic class would either lose that distinction at the type level or push it back
out into every caller, for less clarity than the duplication below costs. Second,
`PrincipalCache`'s own docstring narrates a real concurrency bug (a `lookup`/`del` race) this class
must not reintroduce by drifting from its fix — copying the whole locking discipline, rules
included, is safer than parameterizing a shared class and hoping a later edit to one preserves the
other's invariant.

`digest` is imported rather than reimplemented — it is a pure function with no state, so sharing it
carries none of the risk sharing the stateful cache class would.

The bound below is defense-in-depth rather than the load-shedding necessity it is for
`PrincipalCache`: a garbage `Authorization` header never reaches this cache at all, because ADR
0002's identity resolver already rejects it before `authorize_note`'s team-default rung ever runs.
Kept anyway, for the same reason a seatbelt is worn on a route with no history of crashes.
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from app.auth.cache import digest

DEFAULT_MAX_ENTRIES = 4096


@dataclass(frozen=True, slots=True)
class _Entry:
    teams: frozenset[int] | None
    """``None`` is "pandan could not be asked" (ADR 0011's soft-fail case) — never a rejection."""

    expires_at: float


class TeamMembershipCache:
    """TTL cache of team-membership answers, keyed on a digest. **Safe under concurrent use** —
    see the module docstring for why this duplicates `PrincipalCache`'s locking rather than
    sharing it. The two rules are identical and identically load-bearing:

    1. Nothing injected is called while `_lock` is held (the clock is read before it is taken).
    2. `_evict` runs with the lock already held and never takes it itself.
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
        self._clock = clock
        self._max_entries = max_entries
        self._entries: dict[str, _Entry] = {}
        self._lock = threading.Lock()

    def lookup(self, token: str) -> tuple[bool, frozenset[int] | None]:
        """``(hit, teams)``. ``(True, None)`` is a cached "unknown"; ``(False, None)`` is a miss —
        see `PrincipalCache.lookup` for why collapsing these two would be the bug."""
        key = digest(token)
        now = self._clock()

        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return (False, None)
            if now >= entry.expires_at:
                del self._entries[key]
                return (False, None)
            return (True, entry.teams)

    def remember(self, token: str, teams: frozenset[int] | None) -> None:
        """Cache an answer. ``None`` records "pandan could not be asked", under the shorter TTL."""
        ttl = self._positive_ttl if teams is not None else self._negative_ttl
        key = digest(token)
        now = self._clock()

        with self._lock:
            self._entries.pop(key, None)
            self._entries[key] = _Entry(teams=teams, expires_at=now + ttl)
            self._evict(now)

    def _evict(self, now: float) -> None:
        """Bring the cache back under its bound. **The caller holds `_lock`.**"""
        if len(self._entries) <= self._max_entries:
            return
        for key in [k for k, entry in self._entries.items() if now >= entry.expires_at]:
            del self._entries[key]
        while len(self._entries) > self._max_entries:
            del self._entries[next(iter(self._entries))]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
