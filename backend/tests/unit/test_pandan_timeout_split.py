"""One deadline could not be right for both of pandan's failure modes (KAN-666).

`MockTransport` cannot test this: it answers from a function and never puts a byte on a socket, so
no timeout it is given ever fires. These tests use a real loopback server and a real `httpx.Client`,
which is the only way "the read budget bounded that wait, not the connect budget" is a measurement
rather than a claim about a keyword argument.

**The numbers are the shipped ones, divided by `SCALE`.** Not invented, and not hard-coded either:
they are read off `Settings`' declared defaults, so lowering the shipped read budget below what a
cold start needs fails a test here instead of failing a person's login six weeks later. The scaling
is what keeps a suite that must stay fast from spending half a minute proving a half-minute budget.

The credential is `fakes.TOKEN`, a deliberately shapeless string. Nothing here needs a real PAT.
"""

import json
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from fakes import ALICE, TOKEN
from fastapi import HTTPException

from app.auth.cache import PrincipalCache
from app.auth.principal import UpstreamUnavailable
from app.auth.resolver import PrincipalResolver, principal_from_bearer
from app.auth.single_flight import SingleFlight
from app.auth.upstream import PandanIdentityUpstream, split_timeout
from app.config import Settings

SCALE = 50.0
"""Everything below runs at 1/50 of production. A literal test of a 30 s budget is a 30 s test."""

SHIPPED_CONNECT = float(Settings.model_fields["pandan_connect_timeout_seconds"].default)
SHIPPED_READ = float(Settings.model_fields["pandan_read_timeout_seconds"].default)
"""Read off the field defaults rather than the environment: a developer's `.env` must not be able
to change what this suite asserts about what kaya ships."""

OLD_SINGLE_DEADLINE = 10.0
"""`KAYA_PANDAN_TIMEOUT_SECONDS`, the one number these two replace. Kept here as a literal on
purpose — it no longer exists in the code, and the test that matters is that a wake-up which used
to land outside it now lands inside the read budget."""

MEASURED_COLD_WAIT = 22.0
"""How long a stopped fly machine kept kaya waiting before answering, measured on KAN-666 and
consistent with KAN-539's 11–23 s. This is the wait the split has to accommodate, so it is the wait
the fake pandan below reproduces — scaled, and from the first byte, because that is where the
measurement found it."""


class SleepyPandan(BaseHTTPRequestHandler):
    """Accepts at once, answers late. A stopped fly machine behind a proxy that is wide awake."""

    delay: float = 0.0

    def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler's spelling
        time.sleep(type(self).delay)
        body = json.dumps({"id": str(ALICE.id), "email": ALICE.email}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        """Silence. The default writes every request to stderr."""


@pytest.fixture
def sleepy() -> Iterator[str]:
    """A loopback pandan that waits `MEASURED_COLD_WAIT / SCALE` before its first byte."""
    SleepyPandan.delay = MEASURED_COLD_WAIT / SCALE
    server = ThreadingHTTPServer(("127.0.0.1", 0), SleepyPandan)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def refused() -> Iterator[str]:
    """An origin nothing is listening on. Bound, read for its port, then closed.

    Port 0 and then close, rather than a number someone liked the look of: a hard-coded port is a
    test that fails on the machine where something else happens to be using it.
    """
    import socket

    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    yield f"http://127.0.0.1:{port}"


def upstream_against(origin: str, *, connect: float, read: float) -> PandanIdentityUpstream:
    return PandanIdentityUpstream(origin, timeout=split_timeout(connect=connect, read=read))


# --- The bug, reproduced, and then fixed --------------------------------------------------------


def test_the_old_single_deadline_turns_a_wake_up_into_an_outage(sleepy: str) -> None:
    """KAN-539's finding, at 1/50 scale: a valid PAT gets a `503` because pandan was asleep.

    This is the "written failing first" half. It has to keep passing — it is the description of the
    problem, and a change that made it fail would mean the wake-up was no longer being waited for at
    all, which is the opposite mistake.
    """
    single = OLD_SINGLE_DEADLINE / SCALE
    assert single < MEASURED_COLD_WAIT / SCALE, "the premise: the cold start exceeded the deadline"

    with pytest.raises(UpstreamUnavailable):
        upstream_against(sleepy, connect=single, read=single).introspect(TOKEN)


def test_a_sleeping_pandan_now_answers_within_the_read_budget(sleepy: str) -> None:
    """The fix. Same server, same delay, same valid token — the deadline is what changed."""
    upstream = upstream_against(sleepy, connect=SHIPPED_CONNECT / SCALE, read=SHIPPED_READ / SCALE)

    principal = upstream.introspect(TOKEN)

    assert principal == ALICE


def test_the_wait_is_charged_to_the_read_budget_and_not_the_connect_one(sleepy: str) -> None:
    """The control, and the reason the test above is not just "we made a number bigger".

    A connect budget far *shorter* than the wait, paired with a read budget longer than it, still
    succeeds — so the wait is being measured against `read`. Shrink `read` alone, leaving the same
    generous connect, and it fails. Nothing about this pair passes if httpx were treating the two as
    one deadline.
    """
    wait = MEASURED_COLD_WAIT / SCALE

    generous_read = upstream_against(sleepy, connect=wait / 4, read=SHIPPED_READ / SCALE)
    assert generous_read.introspect(TOKEN) == ALICE

    stingy_read = upstream_against(sleepy, connect=SHIPPED_READ / SCALE, read=wait / 4)
    with pytest.raises(UpstreamUnavailable):
        stingy_read.introspect(TOKEN)


# --- Q9 still holds: down is not the same as asleep ---------------------------------------------


def test_a_dead_upstream_still_fails_fast_and_reports_503(refused: str) -> None:
    """Q9's whole point, and the thing a longer deadline could have quietly cost.

    Two assertions, and the second is the one the split exists for: the failure arrives in a small
    fraction of the *read* budget. Before the split there was one number, so making it long enough
    for a wake-up would also have made a genuinely dead pandan take that long to report.
    """
    upstream = upstream_against(refused, connect=SHIPPED_CONNECT, read=SHIPPED_READ)
    resolver = PrincipalResolver(
        upstream=upstream,
        mirror=_NoMirror(),
        cache=PrincipalCache(positive_ttl=60.0, negative_ttl=10.0),
        single_flight=SingleFlight(),
    )

    began = time.perf_counter()
    with pytest.raises(HTTPException) as raised:
        principal_from_bearer(TOKEN, resolver)
    elapsed = time.perf_counter() - began

    assert raised.value.status_code == 503
    assert raised.value.status_code != 401, "an outage is never a rejection (Q9)"
    error = raised.value.detail["error"]
    assert error["code"] == "upstream_unavailable"
    assert error["upstream"] == "pandan"

    assert elapsed < SHIPPED_READ / 10, (
        f"a refused connection took {elapsed:.2f}s to report; the read budget is not supposed to "
        "apply to an upstream that was never reached"
    )


class _NoMirror:
    """Nothing gets mirrored on these paths — reaching a mirror at all would be the bug."""

    def ensure(self, principal: object) -> None:
        raise AssertionError("the mirror must not be touched for an upstream that never answered")


# --- The shape of the shipped configuration -----------------------------------------------------


def test_the_shipped_budgets_are_two_different_numbers_in_the_right_order() -> None:
    """Cheap, and it is the assertion that would have caught the original design if it had existed.

    `connect < old single deadline < read` is the whole of KAN-666 step 2 in one line: an outage is
    reported sooner than it used to be, and a wake-up is waited for longer than it used to be.
    """
    assert SHIPPED_CONNECT < OLD_SINGLE_DEADLINE < SHIPPED_READ
    assert SHIPPED_READ > MEASURED_COLD_WAIT, (
        "the read budget is below the cold start that was actually measured, so KAN-539's finding "
        "is back: a valid PAT gets a 503 because pandan was asleep"
    )


def test_split_timeout_leaves_no_phase_unbounded() -> None:
    """`httpx.Timeout` will happily hand back `None` for a phase nobody named, and `None` means
    *wait forever* — one unbounded phase is a held threadpool worker and a held Postgres session
    with no deadline at all, which is ADR 0003's failure mode with the safety net removed."""
    timeout = split_timeout(connect=5.0, read=30.0)

    assert timeout.connect == 5.0
    assert timeout.read == 30.0
    assert timeout.write == 5.0
    assert timeout.pool == 5.0
    assert None not in (timeout.connect, timeout.read, timeout.write, timeout.pool)


def test_the_upstream_still_accepts_a_plain_float_for_a_harness_that_wants_one() -> None:
    """Widening the annotation to `httpx.Timeout | float` must not break the one-number case.

    `test_pandan_upstream.py` passes a float throughout, and so does the measurement harness at
    `--timeout`. Asserted on the built client rather than on the constructor not raising: "it did
    not blow up" would also pass if the value were dropped on the floor.
    """
    upstream = PandanIdentityUpstream("https://pandan.invalid", timeout=1.5)
    try:
        assert upstream._client.timeout == httpx.Timeout(1.5)  # type: ignore[attr-defined]
    finally:
        upstream._client.close()  # type: ignore[attr-defined]


# --- The wiring, which is where a correct design gets a lifetime wrong --------------------------


@pytest.fixture
def fresh_singletons() -> Iterator[None]:
    """`app.auth.dependencies` memoises three objects; a test that builds one must not leak it."""
    from app.auth.dependencies import reset_auth

    reset_auth()
    yield
    reset_auth()


def test_the_shipped_client_carries_the_split_and_not_one_number(fresh_singletons: None) -> None:
    """`split_timeout` existing proves nothing if `get_upstream` does not call it.

    Reaching for `_client` on purpose: the assertion is about what was handed to httpx, and there
    is no public way to ask. The alternative — trusting that the constructor was called correctly —
    is how a configuration change gets shipped with no test standing behind it.
    """
    from app.auth.dependencies import get_upstream

    timeout = get_upstream()._client.timeout  # type: ignore[attr-defined]

    assert timeout.connect == SHIPPED_CONNECT
    assert timeout.read == SHIPPED_READ
    assert timeout.connect != timeout.read, "the two budgets collapsed back into one"


def test_the_single_flight_registry_is_one_object_for_the_whole_process(
    fresh_singletons: None,
) -> None:
    """The lifetime bug that breaks nothing and fixes nothing.

    A per-request `SingleFlight` still returns correct principals every single time; it just makes
    N upstream calls where one would do, which is the entire thing KAN-666 built it for. No
    assertion about a returned principal can tell the two apart, so this asserts identity instead.
    """
    from app.auth.dependencies import get_single_flight

    assert get_single_flight() is get_single_flight()


def test_reset_auth_drops_the_registry_with_the_rest(fresh_singletons: None) -> None:
    """Otherwise a registry outlives the test that made it, which is the flake `reset_auth` exists
    for — and this one would be worse than the cache's, because an in-flight entry left behind by a
    torn-down test would park the next test's caller on an `Event` nobody will ever set."""
    from app.auth.dependencies import get_single_flight, reset_auth

    first = get_single_flight()
    reset_auth()

    assert get_single_flight() is not first
