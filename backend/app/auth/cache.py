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
    """TTL cache of introspection answers, keyed on a digest.

    Not thread-safe by construction, and it does not need to be. Every operation is a handful of
    dict mutations under the GIL; the worst a race can do is two threads paying for the same
    upstream call, which is a wasted round trip and not a wrong answer.
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

    def lookup(self, token: str) -> tuple[bool, Principal | None]:
        """``(hit, principal)``.

        Three outcomes in two values, and the awkwardness is deliberate: ``(True, None)`` is a
        cached *rejection* and ``(False, None)`` is a miss. Collapsing them into a bare
        ``Principal | None`` would silently turn every negative-cache hit into an upstream call,
        which is the one thing the negative cache exists to prevent — and the test for it would
        still pass, because the answer would still be "rejected".
        """
        key = digest(token)
        entry = self._entries.get(key)
        if entry is None:
            return (False, None)
        if self._clock() >= entry.expires_at:
            del self._entries[key]
            return (False, None)
        return (True, entry.principal)

    def remember(self, token: str, principal: Principal | None) -> None:
        """Cache an answer. ``None`` records a rejection under the shorter negative TTL."""
        ttl = self._positive_ttl if principal is not None else self._negative_ttl
        key = digest(token)
        # Re-insert rather than overwrite, so dict insertion order stays recency order for _evict.
        self._entries.pop(key, None)
        self._entries[key] = _Entry(principal=principal, expires_at=self._clock() + ttl)
        self._evict()

    def _evict(self) -> None:
        if len(self._entries) <= self._max_entries:
            return
        now = self._clock()
        for key in [k for k, entry in self._entries.items() if now >= entry.expires_at]:
            del self._entries[key]
        while len(self._entries) > self._max_entries:
            del self._entries[next(iter(self._entries))]

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        """Live *and* expired entries — the storage size, not the logical size."""
        return len(self._entries)
