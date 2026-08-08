"""ADR 0002's resolver, end to end, with pandan and Postgres both faked at their seams.

The assertions that carry the weight are the **call counts**, not the returned principals. A
resolver with a broken cache still returns the right answer every time; a resolver that re-mirrors
on every request still returns the right answer every time. Only "how many times did you ask
pandan" and "how many times did you touch the mirror" can tell those apart, which is the same
lesson KAN-560 wrote into V5's guard.
"""

import pytest
from fakes import ALICE, OTHER_TOKEN, TOKEN, FakeClock, FakeMirror, FakeUpstream
from fastapi import HTTPException

from app.auth.cache import PrincipalCache
from app.auth.principal import TokenRejected, UpstreamUnavailable
from app.auth.resolver import PrincipalResolver, principal_from_bearer


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
