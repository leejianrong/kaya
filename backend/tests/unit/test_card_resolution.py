"""``CardEpicResolver`` and ``CardEpicCache``, against an in-memory fake upstream.

As with ``test_principal_resolver.py``, the assertions that carry the weight are the **call
counts**, not just the returned tickets: a resolver with no cache still returns the right answer
every time, and a resolver that leaks one caller's cache entry to another still returns *plausible*
answers for both. Only "how many upstream requests did this cost" and "did caller B's lookup ever
reach caller A's cache entry" can tell those apart.
"""

import threading
from collections.abc import Mapping, Sequence

import pytest

from app.integrations.card_resolution import (
    CardBatch,
    CardEpicCache,
    CardEpicResolver,
    CardEpicUnavailable,
    ResolvedTicket,
    classify_ref,
    digest,
)

TOKEN_A = "caller-a-supplied-string-kaya-does-not-parse"
TOKEN_B = "caller-b-supplied-a-different-string"

KAN_1 = ResolvedTicket(kind="card", id=1, ticket_number="KAN-1", title="First", column="todo")
KAN_2 = ResolvedTicket(kind="card", id=2, ticket_number="KAN-2", title="Second", column="done")
EPIC_1 = ResolvedTicket(kind="epic", id=1, ticket_number="EPIC-1", title="An epic", column=None)


class FakeClock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeCardEpicUpstream:
    """A ``CardEpicUpstream`` backed by per-bearer dicts, counting every call.

    Answering *per bearer* is what makes the cross-caller leak test possible: two different
    bearers can see two different sets of cards, exactly as pandan's own owner-scoping does.
    """

    def __init__(self) -> None:
        self.cards_by_bearer: dict[str, dict[str, ResolvedTicket]] = {}
        self.epics_by_bearer: dict[str, list[ResolvedTicket]] = {}
        self.card_calls: list[tuple[str, tuple[str, ...]]] = []
        self.epic_calls: list[str] = []
        self.available = True
        self.clock: FakeClock | None = None
        self.advance_per_call: float = 0.0

    def _tick(self) -> None:
        if self.clock is not None and self.advance_per_call:
            self.clock.advance(self.advance_per_call)

    def fetch_cards(self, bearer: str, refs: Sequence[str]) -> CardBatch:
        self.card_calls.append((bearer, tuple(refs)))
        if not self.available:
            raise CardEpicUnavailable("https://pandan.invalid/api/v1/cards is unreachable")
        self._tick()
        known = self.cards_by_bearer.get(bearer, {})
        cards = tuple(known[ref] for ref in refs if ref in known)
        unresolved = tuple(ref for ref in refs if ref not in known)
        return CardBatch(cards=cards, unresolved_refs=unresolved)

    def fetch_epics(self, bearer: str) -> Sequence[ResolvedTicket]:
        self.epic_calls.append(bearer)
        if not self.available:
            raise CardEpicUnavailable("https://pandan.invalid/api/v1/epics is unreachable")
        self._tick()
        return tuple(self.epics_by_bearer.get(bearer, []))

    @property
    def call_count(self) -> int:
        return len(self.card_calls) + len(self.epic_calls)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def upstream() -> FakeCardEpicUpstream:
    return FakeCardEpicUpstream()


@pytest.fixture
def cache(clock: FakeClock) -> CardEpicCache:
    return CardEpicCache(ttl=300.0, clock=clock)


def make_resolver(
    upstream: FakeCardEpicUpstream,
    cache: CardEpicCache,
    clock: FakeClock,
    *,
    max_selectors_per_request: int = 100,
    max_upstream_requests: int = 5,
    total_deadline_seconds: float = 8.0,
) -> CardEpicResolver:
    return CardEpicResolver(
        upstream,
        cache,
        max_selectors_per_request=max_selectors_per_request,
        max_upstream_requests=max_upstream_requests,
        total_deadline_seconds=total_deadline_seconds,
        clock=clock,
    )


# --- classify_ref -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ref", "kind"),
    [("KAN-1", "card"), ("EPIC-1", "epic"), ("PAN-1", None), ("NOTE-1", None), ("", None)],
)
def test_classify_ref(ref: str, kind: str | None) -> None:
    assert classify_ref(ref) == kind


# --- The happy path ----------------------------------------------------------------------------


def test_successful_resolution_of_a_card_and_an_epic(
    upstream: FakeCardEpicUpstream, cache: CardEpicCache, clock: FakeClock
) -> None:
    upstream.cards_by_bearer[TOKEN_A] = {"KAN-1": KAN_1}
    upstream.epics_by_bearer[TOKEN_A] = [EPIC_1]
    resolver = make_resolver(upstream, cache, clock)

    result = resolver.resolve(TOKEN_A, ["KAN-1", "EPIC-1"])

    assert result == {"KAN-1": KAN_1, "EPIC-1": EPIC_1}
    assert upstream.card_calls == [(TOKEN_A, ("KAN-1",))]
    assert upstream.epic_calls == [TOKEN_A]


def test_a_ref_not_found_renders_unresolved_with_no_exception(
    upstream: FakeCardEpicUpstream, cache: CardEpicCache, clock: FakeClock
) -> None:
    resolver = make_resolver(upstream, cache, clock)

    result = resolver.resolve(TOKEN_A, ["KAN-999"])

    assert result == {"KAN-999": None}


def test_a_ref_this_module_does_not_understand_never_reaches_upstream(
    upstream: FakeCardEpicUpstream, cache: CardEpicCache, clock: FakeClock
) -> None:
    resolver = make_resolver(upstream, cache, clock)

    result = resolver.resolve(TOKEN_A, ["PAN-1"])

    assert result == {"PAN-1": None}
    assert upstream.call_count == 0


def test_duplicate_refs_collapse_to_one_lookup(
    upstream: FakeCardEpicUpstream, cache: CardEpicCache, clock: FakeClock
) -> None:
    upstream.cards_by_bearer[TOKEN_A] = {"KAN-1": KAN_1}
    resolver = make_resolver(upstream, cache, clock)

    result = resolver.resolve(TOKEN_A, ["KAN-1", "KAN-1", "KAN-1"])

    assert result == {"KAN-1": KAN_1}
    assert upstream.card_calls == [(TOKEN_A, ("KAN-1",))]


def test_a_second_resolve_of_the_same_refs_costs_no_upstream_requests(
    upstream: FakeCardEpicUpstream, cache: CardEpicCache, clock: FakeClock
) -> None:
    upstream.cards_by_bearer[TOKEN_A] = {"KAN-1": KAN_1}
    upstream.epics_by_bearer[TOKEN_A] = [EPIC_1]
    resolver = make_resolver(upstream, cache, clock)

    resolver.resolve(TOKEN_A, ["KAN-1", "EPIC-1"])
    result = resolver.resolve(TOKEN_A, ["KAN-1", "EPIC-1"])

    assert result == {"KAN-1": KAN_1, "EPIC-1": EPIC_1}
    assert upstream.call_count == 2, "one card call + one epic call, from the first resolve only"


def test_a_not_found_ref_is_cached_too_so_a_repeat_costs_nothing(
    upstream: FakeCardEpicUpstream, cache: CardEpicCache, clock: FakeClock
) -> None:
    resolver = make_resolver(upstream, cache, clock)

    resolver.resolve(TOKEN_A, ["KAN-999"])
    resolver.resolve(TOKEN_A, ["KAN-999"])

    assert upstream.card_calls == [(TOKEN_A, ("KAN-999",))]


def test_the_epic_call_caches_every_epic_returned_not_only_the_referenced_one(
    upstream: FakeCardEpicUpstream, cache: CardEpicCache, clock: FakeClock
) -> None:
    other_epic = ResolvedTicket(kind="epic", id=2, ticket_number="EPIC-2", title="x", column=None)
    upstream.epics_by_bearer[TOKEN_A] = [EPIC_1, other_epic]
    resolver = make_resolver(upstream, cache, clock)

    resolver.resolve(TOKEN_A, ["EPIC-1"])
    result = resolver.resolve(TOKEN_A, ["EPIC-2"])

    assert result == {"EPIC-2": other_epic}
    assert len(upstream.epic_calls) == 1, "EPIC-2 was already cached from the first call's sweep"


# --- Pandan unavailable degrades cleanly --------------------------------------------------------


def test_pandan_unavailable_degrades_to_unresolved_with_no_exception(
    upstream: FakeCardEpicUpstream, cache: CardEpicCache, clock: FakeClock
) -> None:
    upstream.available = False
    resolver = make_resolver(upstream, cache, clock)

    result = resolver.resolve(TOKEN_A, ["KAN-1", "EPIC-1"])

    assert result == {"KAN-1": None, "EPIC-1": None}


def test_an_outage_is_not_cached_as_a_negative_result(
    upstream: FakeCardEpicUpstream, cache: CardEpicCache, clock: FakeClock
) -> None:
    """An outage is not evidence a ref doesn't exist. Caching it as absent would make a transient
    pandan failure durably wrong for the rest of the TTL."""
    upstream.available = False
    resolver = make_resolver(upstream, cache, clock)
    resolver.resolve(TOKEN_A, ["KAN-1"])
    assert len(cache) == 0

    upstream.available = True
    upstream.cards_by_bearer[TOKEN_A] = {"KAN-1": KAN_1}
    result = resolver.resolve(TOKEN_A, ["KAN-1"])

    assert result == {"KAN-1": KAN_1}


# --- TTL expiry --------------------------------------------------------------------------------


def test_ttl_expiry_causes_a_refetch(upstream: FakeCardEpicUpstream, clock: FakeClock) -> None:
    cache = CardEpicCache(ttl=60.0, clock=clock)
    upstream.cards_by_bearer[TOKEN_A] = {"KAN-1": KAN_1}
    resolver = make_resolver(upstream, cache, clock)

    resolver.resolve(TOKEN_A, ["KAN-1"])
    clock.advance(59.0)
    resolver.resolve(TOKEN_A, ["KAN-1"])
    assert len(upstream.card_calls) == 1, "still within the 60s TTL"

    clock.advance(2.0)  # now 61s since the cache write
    resolver.resolve(TOKEN_A, ["KAN-1"])
    assert len(upstream.card_calls) == 2, "the TTL has elapsed, so this is a fresh ask"


def test_settings_give_the_resolution_cache_its_own_env_var_and_default() -> None:
    """The other half of the independence claim: two distinct environment variables, two distinct
    defaults, and setting one through the environment must not move the other."""
    from app.config import Settings

    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.card_resolution_cache_ttl_seconds == 300.0
    assert settings.principal_cache_ttl_seconds == 60.0
    assert settings.card_resolution_cache_ttl_seconds != settings.principal_cache_ttl_seconds

    changed = Settings(  # type: ignore[call-arg]
        _env_file=None,
        KAYA_CARD_RESOLUTION_CACHE_TTL_SECONDS="900",
    )
    assert changed.card_resolution_cache_ttl_seconds == 900.0
    assert changed.principal_cache_ttl_seconds == 60.0, "the auth TTL must not have moved"


def test_the_resolution_cache_has_its_own_ttl_independent_of_the_auth_cache() -> None:
    """SLICES.md V5: "the resolution cache is separate from the auth cache and has its own TTL."

    Two knobs on ``Settings``, defaulting to different values, and changing one through the
    environment must not move the other (see ``test_settings_defaults`` in this file's neighbour
    for the environment-variable half; this asserts the class-level independence).
    """
    from app.auth.cache import PrincipalCache

    auth_clock = FakeClock()
    resolution_clock = FakeClock()
    auth_cache = PrincipalCache(positive_ttl=60.0, negative_ttl=10.0, clock=auth_clock)
    resolution_cache = CardEpicCache(ttl=300.0, clock=resolution_clock)

    assert auth_cache is not resolution_cache
    assert not isinstance(resolution_cache, PrincipalCache)

    # Advancing one clock/cache must not affect the other's stored expiry.
    resolution_cache.remember(TOKEN_A, "KAN-1", KAN_1)
    resolution_clock.advance(400.0)  # past the resolution TTL
    auth_clock.advance(0.0)
    hit, _ = resolution_cache.lookup(TOKEN_A, "KAN-1")
    assert hit is False, "the resolution TTL elapsed on its own clock"


# --- Bounded walk: chunking, the request cap, and the deadline ---------------------------------


def test_card_refs_beyond_the_selector_cap_are_chunked_into_multiple_requests(
    upstream: FakeCardEpicUpstream, cache: CardEpicCache, clock: FakeClock
) -> None:
    refs = [f"KAN-{i}" for i in range(1, 251)]  # 250 refs, cap of 100 -> 3 chunks
    upstream.cards_by_bearer[TOKEN_A] = {
        ref: ResolvedTicket(kind="card", id=i, ticket_number=ref, title="x", column="todo")
        for i, ref in enumerate(refs, start=1)
    }
    resolver = make_resolver(upstream, cache, clock, max_selectors_per_request=100)

    result = resolver.resolve(TOKEN_A, refs)

    assert len(upstream.card_calls) == 3
    assert [len(call[1]) for call in upstream.card_calls] == [100, 100, 50]
    assert all(result[ref] is not None for ref in refs)


def test_the_request_count_cap_bounds_a_huge_batch_to_partial_resolution(
    upstream: FakeCardEpicUpstream, cache: CardEpicCache, clock: FakeClock
) -> None:
    refs = [f"KAN-{i}" for i in range(1, 501)]  # 500 refs, 10-selector chunks -> 50 chunks needed
    upstream.cards_by_bearer[TOKEN_A] = {
        ref: ResolvedTicket(kind="card", id=i, ticket_number=ref, title="x", column="todo")
        for i, ref in enumerate(refs, start=1)
    }
    resolver = make_resolver(
        upstream, cache, clock, max_selectors_per_request=10, max_upstream_requests=3
    )

    result = resolver.resolve(TOKEN_A, refs)

    assert len(upstream.card_calls) == 3, "the cap stopped the walk rather than a hang"
    resolved = [ref for ref in refs if result[ref] is not None]
    unresolved = [ref for ref in refs if result[ref] is None]
    assert len(resolved) == 30  # 3 requests * 10 selectors
    assert len(unresolved) == 470


def test_hitting_the_total_deadline_leaves_the_rest_unresolved_rather_than_hanging(
    upstream: FakeCardEpicUpstream, cache: CardEpicCache, clock: FakeClock
) -> None:
    upstream.clock = clock
    upstream.advance_per_call = 3.5  # each request "takes" 3.5s of the fake clock
    refs = [f"KAN-{i}" for i in range(1, 401)]  # needs 4 chunks of 100
    upstream.cards_by_bearer[TOKEN_A] = {
        ref: ResolvedTicket(kind="card", id=i, ticket_number=ref, title="x", column="todo")
        for i, ref in enumerate(refs, start=1)
    }
    resolver = make_resolver(
        upstream,
        cache,
        clock,
        max_selectors_per_request=100,
        max_upstream_requests=10,  # high enough that the deadline is what stops it
        total_deadline_seconds=8.0,
    )

    result = resolver.resolve(TOKEN_A, refs)

    # t=0 -> call 1 (t=3.5), t=3.5 -> call 2 (t=7.0), t=7.0 -> call 3 (t=10.5), t=10.5 >= 8 -> stop
    assert len(upstream.card_calls) == 3
    resolved = [ref for ref in refs if result[ref] is not None]
    assert len(resolved) == 300
    assert all(result[ref] is None for ref in refs[300:])


# --- The over-disclosure guard: one caller's cache entry never answers another's ----------------


def test_a_callers_cache_entry_never_leaks_to_another_caller(
    upstream: FakeCardEpicUpstream, cache: CardEpicCache, clock: FakeClock
) -> None:
    """SLICES.md V5's named guard: "a note referencing a card the reader cannot see renders
    unresolved rather than leaking the title." KAN-1 is visible to caller A's bearer and to no
    one else's — pandan's own owner-scoping would answer this identically for caller B, and this
    test proves the *cache* respects that scoping rather than shortcutting it.
    """
    upstream.cards_by_bearer[TOKEN_A] = {"KAN-1": KAN_1}
    upstream.cards_by_bearer[TOKEN_B] = {}  # B's PAT cannot see this card at all
    resolver = make_resolver(upstream, cache, clock)

    result_a = resolver.resolve(TOKEN_A, ["KAN-1"])
    assert result_a == {"KAN-1": KAN_1}
    assert len(cache) == 1, "the cache is warm for A"

    # Same resolver, same warm cache, a *different* caller asking for the *same* ref.
    result_b = resolver.resolve(TOKEN_B, ["KAN-1"])

    assert result_b == {"KAN-1": None}, "B's title must never come from A's cache entry"
    assert upstream.card_calls == [
        (TOKEN_A, ("KAN-1",)),
        (TOKEN_B, ("KAN-1",)),
    ], "B's lookup must reach pandan itself, not answer from A's cache"


def test_the_cache_key_is_composite_never_a_bare_ticket_number(cache: CardEpicCache) -> None:
    """The behavioural test above proves the effect; this pins the mechanism it relies on, so a
    refactor that flattens the key back to a bare ticket number fails here directly rather than
    only through the scenario above (the "prove a guard by watching it fail" habit, aimed at the
    guard itself)."""
    cache.remember(TOKEN_A, "KAN-1", KAN_1)

    hit_a, ticket_a = cache.lookup(TOKEN_A, "KAN-1")
    hit_b, ticket_b = cache.lookup(TOKEN_B, "KAN-1")

    assert (hit_a, ticket_a) == (True, KAN_1)
    assert (hit_b, ticket_b) == (False, None)


# --- The cache never holds a raw bearer, mirroring test_principal_cache.py's [mutate] guard -----


def reachable_strings(root: object, *, max_depth: int = 8) -> list[str]:
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


def test_the_raw_bearer_never_reaches_the_cache_state() -> None:
    cache = CardEpicCache(ttl=300.0, clock=FakeClock())
    cache.remember(TOKEN_A, "KAN-1", KAN_1)
    cache.remember(TOKEN_B, "KAN-2", None)

    strings = reachable_strings(cache)

    leaks = sum(1 for s in strings if TOKEN_A in s or TOKEN_B in s)
    assert leaks == 0, (
        "a raw bearer is reachable from the cache's state; the key must be sha256(bearer), never "
        "the bearer itself. Values withheld on purpose."
    )
    assert digest(TOKEN_A) in strings
    assert digest(TOKEN_B) in strings


# --- Thread-safety --------------------------------------------------------------------------------


def test_concurrent_lookups_and_remembers_do_not_raise(clock: FakeClock) -> None:
    """Mirrors ``test_principal_cache.py``'s concurrency guard: a `del` racing a `del` on the same
    expired key is the failure mode, not a wrong answer."""
    cache = CardEpicCache(ttl=0.001, clock=clock, max_entries=50)
    errors: list[BaseException] = []

    def hammer(n: int) -> None:
        try:
            for i in range(200):
                cache.remember(f"token-{n}", f"KAN-{i % 20}", KAN_1)
                cache.lookup(f"token-{n}", f"KAN-{i % 20}")
                clock.advance(0.0005)
        except BaseException as exc:  # noqa: BLE001 - the test cares that nothing raises
            errors.append(exc)

    threads = [threading.Thread(target=hammer, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []


def test_the_cache_is_bounded(clock: FakeClock) -> None:
    cache = CardEpicCache(ttl=300.0, clock=clock, max_entries=10)
    for i in range(50):
        cache.remember(f"token-{i}", "KAN-1", KAN_1)
    assert len(cache) <= 10
