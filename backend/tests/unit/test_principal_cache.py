"""The cache stores digests and TTLs, and never a live credential.

The first test below is one of V1's two **[mutate]** guards. It is deliberately not written as
"the key equals the digest" — that phrasing passes just as happily when the raw token is *also*
stashed somewhere else on the object, which is the actual leak. It walks the cache's whole
reachable state instead and asserts the token is nowhere in it.
"""

import hashlib
import threading
from collections.abc import Mapping

import pytest
from fakes import ALICE, BOB, OTHER_TOKEN, TOKEN, FakeClock

from app.auth.cache import PrincipalCache, digest


def make_cache(clock: FakeClock, **kwargs: float) -> PrincipalCache:
    return PrincipalCache(
        positive_ttl=kwargs.pop("positive_ttl", 60.0),
        negative_ttl=kwargs.pop("negative_ttl", 10.0),
        clock=clock,
        **kwargs,  # type: ignore[arg-type]
    )


def reachable_strings(root: object, *, max_depth: int = 8) -> list[str]:
    """Every string reachable from ``root`` — dict keys, dict values, slots, attributes.

    Broader than "look at the keys" on purpose. The failure this guards against is a token stored
    somewhere nobody thought to check: an entry field kept "for debugging", a last-seen attribute,
    a key built from the raw value. If it is reachable from the cache object, a heap dump has it.
    """
    seen: set[int] = set()
    found: list[str] = []

    def walk(obj: object, depth: int) -> None:
        if depth > max_depth or id(obj) in seen:
            return
        seen.add(id(obj))

        if isinstance(obj, str):
            found.append(obj)
            return
        if isinstance(obj, bytes | bytearray):
            found.append(bytes(obj).decode("utf-8", "replace"))
            return
        if isinstance(obj, Mapping):
            for key, value in obj.items():
                walk(key, depth + 1)
                walk(value, depth + 1)
            return
        if isinstance(obj, list | tuple | set | frozenset):
            for item in obj:
                walk(item, depth + 1)
            return

        walk(getattr(obj, "__dict__", None) or {}, depth + 1)
        for klass in type(obj).__mro__:
            for slot in getattr(klass, "__slots__", ()) or ():
                if slot.startswith("__"):
                    continue
                walk(getattr(obj, slot, None), depth + 1)

    walk(root, 0)
    return found


# --- The [mutate] guard ------------------------------------------------------------------------


def test_the_raw_token_never_reaches_the_cache_state() -> None:
    """ADR 0002: "a heap dump or an errant log line must not yield a live credential"."""
    cache = make_cache(FakeClock())
    cache.remember(TOKEN, ALICE)
    cache.remember(OTHER_TOKEN, None)

    strings = reachable_strings(cache)

    # Counted, not listed. `assert leaked == []` would make pytest print the offending strings —
    # which in production is a live PAT in a CI log, i.e. the guard causing the leak it forbids.
    leaks = sum(1 for s in strings if TOKEN in s or OTHER_TOKEN in s)
    assert leaks == 0, (
        "a raw bearer token is reachable from the cache's state; ADR 0002 stores sha256(raw) and "
        "nothing else, so a heap dump cannot yield a live credential. Values withheld on purpose."
    )

    # …and the guard is not passing because the cache stored nothing at all.
    assert digest(TOKEN) in strings
    assert digest(OTHER_TOKEN) in strings


def test_the_guard_would_notice_a_leak() -> None:
    """The assertion above is an emptiness check, the shape that passes for the wrong reason.

    Point the same walker at an object that *does* hold the raw token and confirm it objects, so a
    refactor that neuters the walk fails here rather than going unnoticed for a slice.
    """

    class Leaky:
        def __init__(self) -> None:
            self.by_token = {TOKEN: ALICE}

    assert [s for s in reachable_strings(Leaky()) if TOKEN in s] != []


def test_the_key_is_a_sha256_hex_digest() -> None:
    assert digest(TOKEN) == hashlib.sha256(TOKEN.encode("utf-8")).hexdigest()
    assert len(digest(TOKEN)) == 64
    assert digest(TOKEN) != digest(OTHER_TOKEN)


# --- TTL behaviour, on an injected clock --------------------------------------------------------


def test_a_positive_entry_is_returned_until_its_ttl_elapses() -> None:
    clock = FakeClock()
    cache = make_cache(clock, positive_ttl=60.0)
    cache.remember(TOKEN, ALICE)

    clock.advance(59.9)
    assert cache.lookup(TOKEN) == (True, ALICE)

    clock.advance(0.1)
    assert cache.lookup(TOKEN) == (False, None), "60s means 60s — Q6's revocation lag, exactly"


def test_a_rejection_expires_on_the_shorter_negative_ttl() -> None:
    """Load-shedding, not a decision. It has to lapse quickly or a freshly minted PAT is stuck."""
    clock = FakeClock()
    cache = make_cache(clock, positive_ttl=60.0, negative_ttl=10.0)
    cache.remember(TOKEN, None)

    clock.advance(9.9)
    assert cache.lookup(TOKEN) == (True, None)

    clock.advance(0.1)
    assert cache.lookup(TOKEN) == (False, None)


def test_a_cached_rejection_is_distinguishable_from_a_miss() -> None:
    """The whole reason ``lookup`` returns a pair.

    Collapse these two into a bare ``Principal | None`` and every negative-cache hit silently
    becomes an upstream call — while every test asserting "the token is rejected" still passes.
    """
    cache = make_cache(FakeClock())
    cache.remember(TOKEN, None)

    assert cache.lookup(TOKEN) == (True, None)
    assert cache.lookup(OTHER_TOKEN) == (False, None)


def test_an_expired_entry_is_dropped_rather_than_left_to_accumulate() -> None:
    clock = FakeClock()
    cache = make_cache(clock, positive_ttl=60.0)
    cache.remember(TOKEN, ALICE)

    clock.advance(61)
    cache.lookup(TOKEN)

    assert len(cache) == 0


def test_the_clock_is_monotonic_by_default() -> None:
    """A wall clock stepped backwards by NTP would extend a revocation window."""
    import time

    from app.auth.cache import PrincipalCache as Cache

    assert Cache(positive_ttl=1, negative_ttl=1)._clock is time.monotonic


# --- The bound ----------------------------------------------------------------------------------


def test_the_cache_is_bounded_because_strangers_fill_the_negative_half() -> None:
    """Anyone can add an entry by sending an ``Authorization`` header. Unbounded, that is a leak."""
    clock = FakeClock()
    cache = make_cache(clock, negative_ttl=10.0, max_entries=8)

    for i in range(50):
        cache.remember(f"stray-header-{i}", None)

    assert len(cache) <= 8


def test_eviction_prefers_expired_entries_over_live_ones() -> None:
    clock = FakeClock()
    cache = make_cache(clock, positive_ttl=60.0, negative_ttl=10.0, max_entries=3)

    cache.remember("stale-a", None)
    cache.remember("stale-b", None)
    clock.advance(11)  # both rejections have lapsed; the live entry below has not

    cache.remember(TOKEN, ALICE)
    cache.remember(OTHER_TOKEN, BOB)
    cache.remember("one-too-many", None)

    assert cache.lookup(TOKEN) == (True, ALICE)
    assert cache.lookup(OTHER_TOKEN) == (True, BOB)


# --- Concurrency ---------------------------------------------------------------------------------
#
# `get_principal` is a sync `def` FastAPI dependency, so Starlette runs it in a threadpool and
# concurrent access to one process-wide cache is guaranteed rather than hypothetical. The window
# that matters is the TTL boundary, which for kaya's actual usage pattern — one agent, one PAT,
# many parallel calls, a 60s TTL — comes round every sixty seconds.


@pytest.mark.parametrize("operation", ["lookup", "remember", "clear", "len"])
def test_every_entry_point_waits_for_the_lock(operation: str) -> None:
    """No method reads or writes ``_entries`` without holding ``_lock``.

    This is a *replacement* for the test that found the bug, and the swap is worth explaining
    because it is not a retreat to something weaker.

    The bug was found with a barrier-parked clock: park both threads between `lookup`'s expiry
    check and its `del`, and the second `del` raises `KeyError`. That worked because the clock was
    read inside the window. The fix moves the clock read *out* of the critical section — deliberate
    (a caller's clock is arbitrary code and must not run while a lock is held), and it takes the
    hook with it. There is now no injected code inside the window, which is exactly what "the
    window is closed" means. A race test with nowhere to park is a race test that passes because
    the scheduler was kind, and that is the trap this suite already fell into once on the mirror.

    So the property that replaced the race is mutual exclusion, and this asserts it directly:
    hold the lock, call the method, and require that it does not come back. Remove the `with
    self._lock` from any entry point and the corresponding case fails immediately.

    Reaching for the private `_lock` is the point rather than a shortcut — the guard *is* the
    subject.
    """
    cache = make_cache(FakeClock())
    cache.remember(TOKEN, ALICE)

    operations = {
        "lookup": lambda: cache.lookup(TOKEN),
        "remember": lambda: cache.remember(OTHER_TOKEN, BOB),
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
            "unguarded — that is the check-then-delete race, back again, and it surfaces as a 500 "
            "from the auth dependency on a perfectly valid credential"
        )

    caller.join(timeout=5)
    assert returned.is_set(), "the operation never completed once the lock was released"


def test_the_cache_survives_a_stampede_across_the_ttl_boundary() -> None:
    """A supplement to the deterministic test above, not a replacement for it.

    Its job is the failure modes a staged two-thread test cannot pose: a dict resized underneath
    `_evict`'s comprehension, and the `next(iter(...))` on a dict another thread just emptied. It
    can only ever produce a *true* failure — if the scheduler never lands in the window, it passes
    for a weaker reason rather than flaking.
    """
    clock = FakeClock()
    cache = make_cache(clock, positive_ttl=60.0, negative_ttl=10.0, max_entries=16)
    failures: list[str] = []
    stop = threading.Event()

    def hammer(worker: int) -> None:
        try:
            for i in range(400):
                cache.remember(f"worker-{worker}-token-{i % 24}", ALICE if i % 2 else None)
                cache.lookup(f"worker-{worker}-token-{i % 24}")
                cache.lookup(TOKEN)
                if worker == 0 and i % 40 == 0:
                    clock.advance(11)  # drag the whole cache across an expiry boundary
        except Exception as exc:  # noqa: BLE001
            failures.append(type(exc).__name__)
        finally:
            stop.set()

    threads = [threading.Thread(target=hammer, args=(w,)) for w in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert failures == [], f"concurrent use of the cache raised: {sorted(set(failures))}"


@pytest.mark.parametrize("principal", [ALICE, None])
def test_remember_then_lookup_round_trips(principal: object) -> None:
    cache = make_cache(FakeClock())
    cache.remember(TOKEN, principal)  # type: ignore[arg-type]
    assert cache.lookup(TOKEN) == (True, principal)
