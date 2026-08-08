#!/usr/bin/env python3
"""KAN-539 — how long does `PrincipalResolver.resolve()` actually take?

PLAN §Open risks says a cache miss adds a full round trip to pandan and a scale-to-zero backend can
make that seconds. This script is the number that settles or escalates that row, and it exists as a
script rather than a test because it needs a **real PAT**, a **real pandan** and a **real Postgres**
— three things the suite is deliberately built to run without.

It lives in `backend/` rather than the repo-root `scripts/` for one reason: it imports `app.auth`
and runs under the backend's locked environment. `cd backend && uv run scripts/...` is the whole
setup, and repo-root `scripts/` is bash-only besides.

    cd backend && uv run scripts/measure_introspection_latency.py

Three phases, in the order the experiment requires:

1. **First miss.** One `resolve()` before anything else has touched pandan. This is the cold-miss
   sample *if and only if* pandan was genuinely idle beforehand, and the script cannot verify that
   for you — see `--last-contact`. Fly stops a `min_machines_running = 0` machine after roughly
   five minutes without traffic, so a cold sample has to be earned by waiting, not by asking.
2. **Warm miss.** The cache is cleared and `resolve()` re-run, N times. Pandan is awake by now, so
   this is one round trip plus the just-in-time mirror write, and the two are timed separately —
   knowing the split is what says whether the mitigation is the cache or something else.
3. **Cache hit.** `resolve()` with the entry present, N times. Claimed to be a dict lookup; this is
   where that gets proven rather than asserted.

`--split-only` (KAN-666) is a fourth, separate experiment and runs *instead* of those three. It
times one introspection at the socket and reports **connect** and **read** as two numbers, because
KAN-539 measured the round trip as a total and the fix proposed for it — a short connect budget and
a long read budget — is only worth building if the cold time is in the read. It needs no Postgres
and makes exactly one call, so a cold sample costs one wait rather than one wait plus a container
pull. The two modes cannot be combined: each of them wants to be the first thing to touch pandan.

**The credential is handled by reference and never printed.** The token is read from
`KAYA_MEASURE_PAT` or from `~/.config/pandan/config.toml`, held in one local, and passed straight to
the resolver. Nothing derived from it — not a prefix, not a length, not the resolved email — reaches
stdout. With no token available the script says so and exits 0, so it can never become a CI job that
needs a secret.

**No `import app.*` at module top.** This sets `DATABASE_URL` at runtime, so a top-level app import
would bind the engine to whatever the environment said first. Same trap as the integration suite
(CLAUDE.md §Two inherited traps), same defence: every app import goes inside a function body.
"""

from __future__ import annotations

import argparse
import os
import socket
import ssl
import statistics
import sys
import time
import tomllib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PANDAN_CONFIG = Path.home() / ".config" / "pandan" / "config.toml"
POSTGRES_IMAGE = "postgres:17-alpine"
HEALTH_PATH = "/healthz"
"""The floor: a round trip through the same proxy to the same app, with no database and no auth.

Verified 2026-08-08: pandan has **no JSON health endpoint**. `/healthz`, `/health` and
`/api/v1/health` all answer `200 text/html` with the SPA's `index.html` — the catch-all that serves
the single-page app. So this measures fly's proxy plus a static file, which is the right shape for a
floor and is not what the path name suggests. Spike 0001's `GET /healthz` row is the same call.
"""

TOKEN_ENV = "KAYA_MEASURE_PAT"
"""Its own name rather than a general-purpose one, so nothing else can pick it up by accident."""


# --- Credential and origin, both by reference ----------------------------------------------------


def _pandan_config(path: Path | None) -> dict[str, Any]:
    """The `pandan` CLI's config, or an empty mapping. Unreadable is the same as absent here."""
    try:
        parsed = tomllib.loads((path or PANDAN_CONFIG).read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    # The CLI nests under `[pandan]`; tolerate a flat file too rather than guessing wrong.
    section = parsed.get("pandan")
    return section if isinstance(section, dict) else parsed


def load_credential(
    env: dict[str, str] | None = None, config_path: Path | None = None
) -> str | None:
    """The bearer, or `None` if there is none to be had.

    `None` is a first-class answer, not an error: it is what makes this script safe to run anywhere,
    including a CI runner that has no PAT and must never be given one.

    Both parameters default to `None` and are resolved inside, rather than defaulting to the live
    environment in the signature — a default argument is bound once at import, which would make the
    "no credential anywhere" case untestable without editing the module.
    """
    environ = os.environ if env is None else env
    from_env = environ.get(TOKEN_ENV)
    if from_env:
        return from_env
    token = _pandan_config(config_path).get("token")
    return token if isinstance(token, str) and token else None


def load_origin(env: dict[str, str] | None = None, config_path: Path | None = None) -> str:
    """Pandan's origin. Configuration, not a secret — it is printed."""
    environ = os.environ if env is None else env
    from_env = environ.get("KAYA_PANDAN_URL")
    if from_env:
        return from_env.rstrip("/")
    api_url = _pandan_config(config_path).get("api_url")
    if isinstance(api_url, str) and api_url:
        return api_url.rstrip("/")
    return "https://simple-kanban-jian.fly.dev"


# --- Timing ---------------------------------------------------------------------------------------


@dataclass
class Samples:
    """Durations in milliseconds, reported the way spike 0001 reports them: median first."""

    label: str
    values: list[float] = field(default_factory=list)

    def add(self, seconds: float) -> None:
        self.values.append(seconds * 1000.0)

    @property
    def n(self) -> int:
        return len(self.values)

    @property
    def median(self) -> float:
        return statistics.median(self.values)

    def row(self) -> str:
        if not self.values:
            return f"| {self.label} | — | not measured |"
        note = f"[n={self.n}]"
        if self.n > 1:
            note += f" min {_ms(min(self.values))}, max {_ms(max(self.values))}"
        return f"| {self.label} | {_ms(self.median)} | {note} |"


def _ms(value: float) -> str:
    """Milliseconds, at a precision that does not overstate what a network measurement knows."""
    if value >= 100:
        return f"{value:,.0f} ms"
    if value >= 1:
        return f"{value:.2f} ms"
    return f"{value * 1000:.1f} µs"


class Stopwatch:
    """One split per collaborator, so a miss can be read as `round trip + mirror write`."""

    def __init__(self) -> None:
        self.last: dict[str, float] = {}

    @contextmanager
    def split(self, name: str) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            self.last[name] = time.perf_counter() - started


class TimedUpstream:
    """Wraps the real `PandanIdentityUpstream`. Records; changes nothing."""

    def __init__(self, inner: Any, watch: Stopwatch) -> None:
        self._inner = inner
        self._watch = watch

    def introspect(self, bearer: str) -> Any:
        with self._watch.split("upstream"):
            return self._inner.introspect(bearer)


class TimedMirror:
    """Wraps the real `SqlAlchemyPrincipalMirror`, including its commit."""

    def __init__(self, inner: Any, watch: Stopwatch) -> None:
        self._inner = inner
        self._watch = watch

    def ensure(self, principal: Any) -> None:
        with self._watch.split("mirror"):
            self._inner.ensure(principal)


# --- The connect/read split (KAN-666) -----------------------------------------------------------


@dataclass
class PhaseSplit:
    """One introspection call, timed at the two phases ``httpx.Timeout`` actually bounds.

    KAN-539 measured the round trip as one number. KAN-666's whole design rests on that number
    having a *shape* — the assumption that fly's proxy accepts the connection while the app machine
    is still booting, so a cold call is slow in the **read** and fast in the **connect**. That
    assumption had never been measured, and it can falsify the design: if connect is slow too, then
    splitting the deadline buys nothing and the fix has to be somewhere else.

    Durations are seconds.
    """

    origin: str
    path: str
    started_at: str

    dns: float
    """``getaddrinfo``. Inside httpx's connect budget, and usually a resolver cache hit."""

    tcp: float
    """``socket.connect`` — the TCP handshake against fly's edge, nothing of pandan's yet."""

    tls: float
    """``SSLContext.wrap_socket`` — the TLS handshake. On `.fly.dev` this terminates at the edge
    proxy, which is precisely why it might complete while the machine behind it is stopped."""

    write: float
    """``sendall`` of a request that fits in one segment. Bounded by ``Timeout(write=…)``."""

    ttfb: float
    """Request written → **first byte of the response**. This is the wait a stopped fly machine
    turns into 20 seconds, and it is exactly what ``Timeout(read=…)`` bounds."""

    body: float
    """First byte → EOF. Separate from ``ttfb`` because ``read`` is a *per-read* deadline in httpx,
    not a deadline on the whole response, and conflating them would overstate what it bounds."""

    status_line: str
    """The response's first line only. The body carries an email address and is never kept."""

    tls_peer: str
    """Who presented the certificate, and over which protocol.

    Not decoration. It is the structural half of the finding: if the certificate is fly's own
    wildcard rather than anything of pandan's, then TLS is terminated at the edge proxy and the app
    machine is not a participant in the handshake at all — which is *why* connect cannot depend on
    whether that machine is running. The timings say what happens; this says why.
    """

    hops: str
    """A fixed allow-list of response headers — `server`, `via`, `fly-request-id`. Named
    explicitly rather than dumped, for the same reason the access log carries `ACCESS_FIELDS` and
    nothing else: a response is unvetted, and "print the headers" is how something that should not
    be in a PR body ends up in one."""

    @property
    def connect(self) -> float:
        """What ``Timeout(connect=…)`` covers: name resolution through to a usable socket."""
        return self.dns + self.tcp + self.tls

    @property
    def read(self) -> float:
        """What ``Timeout(read=…)`` covers, at its worst: the longest single wait for bytes."""
        return max(self.ttfb, self.body)

    @property
    def total(self) -> float:
        return self.connect + self.write + self.ttfb + self.body


def measure_phase_split(
    *, bearer: str, origin: str, connect_timeout: float, read_timeout: float
) -> PhaseSplit:
    """Time one ``GET /api/v1/me`` at the socket, so "connect" and "read" name specific things.

    Deliberately **not** instrumented through httpx. httpx establishes a connection somewhere inside
    its pool's request handling, and its event hooks fire around the request as a whole; a split
    teased out of them would be a split inferred from an implementation detail, and the number would
    only be as trustworthy as that inference. A raw ``socket.connect`` plus ``wrap_socket`` plus a
    hand-written request line gives two numbers nobody has to take on faith, and they line up with
    the phases ``httpx.Timeout`` bounds one-for-one.

    **The credential goes into the request bytes and nowhere else.** It is not printed, not logged,
    not put in the returned object, and the response body — which carries an email address — is
    counted and dropped. Only the status line survives.

    No ``app`` import at module top; ``ME_PATH`` is imported here so the measurement is against the
    same path the resolver calls rather than against a second copy of the string.
    """
    from app.auth.upstream import ME_PATH  # function body — see the module docstring

    parsed = urlsplit(origin)
    host = parsed.hostname
    if host is None:
        raise ValueError(f"{origin} has no host to connect to")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    started_at = datetime.now(UTC).isoformat(timespec="seconds")

    began = time.perf_counter()
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    dns = time.perf_counter() - began

    family, socktype, proto, _canonname, sockaddr = addresses[0]
    raw = socket.socket(family, socktype, proto)
    raw.settimeout(connect_timeout)
    began = time.perf_counter()
    raw.connect(sockaddr)
    tcp = time.perf_counter() - began

    if parsed.scheme == "https":
        context = ssl.create_default_context()
        # http/1.1 only. Offering h2 would make the response framing depend on which protocol the
        # proxy picked, and the timing question here has nothing to do with either.
        context.set_alpn_protocols(["http/1.1"])
        began = time.perf_counter()
        sock: socket.socket = context.wrap_socket(raw, server_hostname=host)
        tls = time.perf_counter() - began
        tls_peer = _describe_peer(sock)
    else:
        sock, tls, tls_peer = raw, 0.0, "no TLS (plain http)"

    request = (
        f"GET {ME_PATH} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"Authorization: Bearer {bearer}\r\n"
        "Accept: application/json\r\n"
        "User-Agent: kaya-measure-phase-split/KAN-666\r\n"
        # `close` so the read loop ends at EOF rather than needing to parse a framing header, and so
        # this connection cannot be reused by accident and warm a subsequent sample.
        "Connection: close\r\n"
        "\r\n"
    ).encode()

    try:
        sock.settimeout(read_timeout)
        began = time.perf_counter()
        sock.sendall(request)
        write = time.perf_counter() - began

        began = time.perf_counter()
        first = sock.recv(65536)
        ttfb = time.perf_counter() - began

        began = time.perf_counter()
        while sock.recv(65536):
            pass
        body = time.perf_counter() - began
    finally:
        sock.close()

    # First line only, and ASCII-decoded defensively: everything after it is unvetted and one field
    # of it is a person's email address.
    status_line = first.split(b"\r\n", 1)[0].decode("ascii", "replace")[:64]
    hops = _allowed_headers(first)

    return PhaseSplit(
        origin=origin,
        path=ME_PATH,
        started_at=started_at,
        dns=dns,
        tcp=tcp,
        tls=tls,
        write=write,
        ttfb=ttfb,
        body=body,
        status_line=status_line,
        tls_peer=tls_peer,
        hops=hops,
    )


HOP_HEADERS = ("server", "via", "fly-request-id")
"""The only response headers this script will repeat. An allow-list rather than a deny-list,
because a deny-list has to be right about every header a proxy might one day add."""


def _describe_peer(sock: socket.socket) -> str:
    """Who answered the handshake, in one line. Public certificate data only."""
    cert = sock.getpeercert() or {}  # type: ignore[attr-defined]
    issuer = ", ".join(
        value for rdn in cert.get("issuer", ()) for key, value in rdn if key == "organizationName"
    )
    subject = ", ".join(
        value for rdn in cert.get("subject", ()) for key, value in rdn if key == "commonName"
    )
    names = [value for key, value in cert.get("subjectAltName", ()) if key == "DNS"]
    alpn = sock.selected_alpn_protocol()  # type: ignore[attr-defined]
    return (
        f"subject CN={subject or '—'}, SAN={'/'.join(names) or '—'}, "
        f"issuer O={issuer or '—'}, ALPN={alpn or 'none'}"
    )


def _allowed_headers(head: bytes) -> str:
    """`HOP_HEADERS` and nothing else, from the first chunk of the response."""
    found = []
    for raw_line in head.split(b"\r\n\r\n", 1)[0].split(b"\r\n")[1:]:
        name, _, value = raw_line.decode("ascii", "replace").partition(":")
        if name.strip().lower() in HOP_HEADERS:
            found.append(f"{name.strip().lower()}={value.strip()[:60]}")
    return "; ".join(found) or "none of " + "/".join(HOP_HEADERS)


COLD_TTFB_SECONDS = 3.0
"""Above this, a first-byte wait is a machine boot rather than a round trip.

KAN-539 measured a warm round trip at 387 ms and cold ones at 11–23 s. Anything in between is
neither, and the verdict below says so rather than rounding it to the nearer story.
"""

FAST_CONNECT_SECONDS = 1.0
"""Below this, connect is "fast" in the sense KAN-666's step 2 needs: short enough that a 5 s
connect budget is comfortable, and small enough beside a cold read that splitting them separates a
dead upstream from a sleeping one."""


def split_verdict(split: PhaseSplit) -> str:
    """The sentence the card asks for, derived rather than eyeballed."""
    if split.ttfb < COLD_TTFB_SECONDS:
        return (
            "NOT a cold sample — the first byte came back in under "
            f"{COLD_TTFB_SECONDS:.0f} s, so pandan was already awake. Discard it and wait longer."
        )
    if split.connect < FAST_CONNECT_SECONDS:
        return (
            "COLD, and connect is fast. The wait is entirely in the read, so a split deadline "
            "separates a dead pandan from a sleeping one: KAN-666 steps 2 and 3 both apply."
        )
    return (
        "COLD, and connect is slow too. Splitting the deadline buys nothing, because the connect "
        "budget would have to be as long as the read budget to let a wake-up through: KAN-666 "
        "step 2 is falsified and only step 3 applies."
    )


def split_report(split: PhaseSplit, *, last_contact: str | None, label: str | None) -> str:
    """A markdown table for the PR body, in the same shape as the one below it."""
    return "\n".join(
        [
            f"### {label or 'Introspection, split by phase'} — {split.started_at}",
            "",
            f"One `GET {split.path}` against `{split.origin}`, timed at the socket.",
            "",
            "| Phase | What it is | Bounded by | Elapsed |",
            "|-------|------------|------------|---------|",
            f"| DNS | `getaddrinfo` | `connect` | {_ms(split.dns * 1000)} |",
            f"| TCP | `socket.connect` to fly's edge | `connect` | {_ms(split.tcp * 1000)} |",
            f"| TLS | `wrap_socket` handshake | `connect` | {_ms(split.tls * 1000)} |",
            f"| **connect, total** | DNS + TCP + TLS | `Timeout(connect=…)` | "
            f"**{_ms(split.connect * 1000)}** |",
            f"| write | `sendall` of the request | `Timeout(write=…)` | "
            f"{_ms(split.write * 1000)} |",
            f"| **read (TTFB)** | request on the wire → first response byte | `Timeout(read=…)` | "
            f"**{_ms(split.ttfb * 1000)}** |",
            f"| read (body) | first byte → EOF | `Timeout(read=…)` | {_ms(split.body * 1000)} |",
            f"| total | | | {_ms(split.total * 1000)} |",
            "",
            f"Response status line: `{split.status_line}`.",
            f"TLS peer: `{split.tls_peer}`.",
            f"Response hops: `{split.hops}`.",
            f"Last known pandan contact before this run: {last_contact or 'not stated'}.",
            "",
            f"**Verdict:** {split_verdict(split)}",
        ]
    )


# --- The measurement --------------------------------------------------------------------------


@dataclass
class Result:
    origin: str
    started_at: str
    first_miss: dict[str, float]
    health_body: str
    floor: Samples
    miss_total: Samples
    miss_upstream: Samples
    miss_mirror: Samples
    hit: Samples


def measure(
    *,
    bearer: str,
    origin: str,
    session_factory: Callable[[], Any],
    warm_repeats: int,
    hit_repeats: int,
    timeout: float,
) -> Result:
    """Everything below runs against the real objects. Nothing here is faked."""
    from app.auth.cache import PrincipalCache
    from app.auth.mirror import SqlAlchemyPrincipalMirror
    from app.auth.resolver import PrincipalResolver
    from app.auth.single_flight import SingleFlight
    from app.auth.upstream import PandanIdentityUpstream, split_timeout

    watch = Stopwatch()
    session = session_factory()
    cache = PrincipalCache(positive_ttl=60.0, negative_ttl=10.0)
    resolver = PrincipalResolver(
        # `--timeout` becomes the *read* budget and the connect budget both, because this harness
        # is measuring rather than serving: a connect that needs longer than the read budget is a
        # number worth seeing, not a failure worth reporting promptly.
        upstream=TimedUpstream(
            PandanIdentityUpstream(origin, timeout=split_timeout(connect=timeout, read=timeout)),
            watch,
        ),
        mirror=TimedMirror(SqlAlchemyPrincipalMirror(session), watch),
        cache=cache,
        single_flight=SingleFlight(),
    )

    started_at = datetime.now(UTC).isoformat(timespec="seconds")

    # 1. The first miss, before this process has sent pandan a single byte. TLS handshake included,
    #    because a cold kaya pays for that too.
    began = time.perf_counter()
    resolver.resolve(bearer)
    first_miss = {
        "total": (time.perf_counter() - began) * 1000.0,
        "upstream": watch.last["upstream"] * 1000.0,
        "mirror": watch.last["mirror"] * 1000.0,
    }

    # 2. The floor. Pandan is awake now, so this is pure round trip against the same origin — the
    #    number that says which part of a miss is network and which part is work.
    floor = Samples("`GET /healthz` (the floor: proxy + app, no database, no auth)")
    with httpx.Client(timeout=timeout) as client:
        first_health = client.get(origin + HEALTH_PATH)  # discard the timing: TLS handshake
        # The body is recorded, not the timing: if the upstream reports an uptime or a start time,
        # that is independent evidence about whether the first miss above woke a stopped machine.
        # Unauthenticated endpoint, so there is nothing here to withhold.
        health_body = f"{first_health.status_code} {first_health.text[:200]}"
        for _ in range(warm_repeats):
            began = time.perf_counter()
            client.get(origin + HEALTH_PATH)
            floor.add(time.perf_counter() - began)

    # 3. Warm misses. Clearing the cache is the only thing standing in for "a token this process has
    #    not seen"; the resolver takes exactly the path it takes for a genuinely new bearer.
    miss_total = Samples("`resolve()`, warm miss")
    miss_upstream = Samples("— of which `GET /api/v1/me`")
    miss_mirror = Samples("— of which the mirror write")
    for _ in range(warm_repeats):
        cache.clear()
        began = time.perf_counter()
        resolver.resolve(bearer)
        miss_total.add(time.perf_counter() - began)
        miss_upstream.add(watch.last["upstream"])
        miss_mirror.add(watch.last["mirror"])

    # 4. Cache hits. The cache is warm from the loop above; nothing is cleared.
    hit = Samples("`resolve()`, cache hit")
    for _ in range(hit_repeats):
        began = time.perf_counter()
        resolver.resolve(bearer)
        hit.add(time.perf_counter() - began)

    session.close()
    return Result(
        origin=origin,
        started_at=started_at,
        first_miss=first_miss,
        health_body=health_body,
        floor=floor,
        miss_total=miss_total,
        miss_upstream=miss_upstream,
        miss_mirror=miss_mirror,
        hit=hit,
    )


def report(result: Result, *, last_contact: str | None, label: str | None) -> str:
    """A markdown table, in spike 0001's shape, ready to paste into a PR body."""
    first = result.first_miss
    # The cold-start signal is in the **round trip**, not the total. The first mirror write is
    # slow too — it opens the pool's first connection and inserts into an empty table — and reading
    # that as evidence about pandan is how a warm run gets reported as a cold one.
    ratio = first["upstream"] / result.miss_upstream.median if result.miss_upstream.n else 0.0
    verdict = (
        "consistent with a cold start"
        if ratio >= 3
        else "NOT consistent with a cold start — pandan was probably already awake"
    )

    lines = [
        f"### {label or 'Introspection latency'} — {result.started_at}",
        "",
        f"Origin `{result.origin}`. Medians, repeat counts in brackets.",
        "",
        "| Call | Median | Notes |",
        "|------|--------|-------|",
        result.floor.row(),
        f"| `resolve()`, **first miss** | {_ms(first['total'])} | [n=1] "
        f"{_ms(first['upstream'])} upstream + {_ms(first['mirror'])} mirror. "
        f"The round trip is {ratio:.1f}× the warm one: {verdict}. "
        "The mirror split here also carries the pool's first connection and an insert into an "
        "empty table, so it is not comparable to the warm figure below |",
        result.miss_total.row(),
        result.miss_upstream.row(),
        result.miss_mirror.row(),
        result.hit.row(),
        "",
        f"Last known pandan contact before this run: {last_contact or 'not stated'}.",
        f"`GET {HEALTH_PATH}` answered `{result.health_body}`.",
    ]
    return "\n".join(lines)


# --- Wiring ---------------------------------------------------------------------------------------


@contextmanager
def _database(database_url: str | None) -> Iterator[Callable[[], Any]]:
    """A migrated Postgres and a session factory over it.

    Defaults to a throwaway container rather than `make db`: worktrees share a filesystem and a
    port, and a measurement must not be the thing that stamps a revision into somebody else's
    database (CLAUDE.md §Conventions).
    """
    if database_url is None:
        from testcontainers.community.postgres import PostgresContainer

        with (
            PostgresContainer(POSTGRES_IMAGE, driver="psycopg") as postgres,
            _migrated(postgres.get_connection_url()) as factory,
        ):
            yield factory
        return
    with _migrated(database_url) as factory:
        yield factory


@contextmanager
def _migrated(database_url: str) -> Iterator[Callable[[], Any]]:
    os.environ["DATABASE_URL"] = database_url

    from alembic import command
    from alembic.config import Config

    from app.db import get_sessionmaker, reset_engine  # after DATABASE_URL — see module docstring

    reset_engine()
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    try:
        yield get_sessionmaker()
    finally:
        reset_engine()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--warm-repeats", type=int, default=7)
    parser.add_argument("--hit-repeats", type=int, default=1000)
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="seconds. Generous: a cold fly machine is the thing being measured, not a failure.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="an already-migrated Postgres; omit to provision a throwaway one via testcontainers",
    )
    parser.add_argument(
        "--last-contact",
        default=None,
        help="when pandan was last touched, for the record. The script cannot know this.",
    )
    parser.add_argument("--label", default=None, help="heading for the emitted table")
    parser.add_argument(
        "--split-only",
        action="store_true",
        help=(
            "KAN-666: time one `GET /api/v1/me` at the socket and report connect vs read, then "
            "stop. No Postgres, no repeats, no second call — which is the point. A cold sample is "
            "earned by waiting, and this mode spends the one call it is worth on the split."
        ),
    )
    parser.add_argument(
        "--connect-timeout",
        type=float,
        default=10.0,
        help="seconds, --split-only. Deliberately longer than the shipped budget: the question is "
        "how long connect takes, and a deadline that fires answers it with an exception.",
    )
    args = parser.parse_args(argv)

    bearer = load_credential()
    if bearer is None:
        print(
            f"No PAT available (${TOKEN_ENV} unset, no token in {PANDAN_CONFIG}). "
            "Nothing measured, and that is a clean exit: this script must never be something CI "
            "needs a credential for.",
            file=sys.stderr,
        )
        return 0

    origin = load_origin()

    if args.split_only:
        print(
            f"Timing one {origin} introspection at the socket. Nothing else is touched.",
            file=sys.stderr,
        )
        split = measure_phase_split(
            bearer=bearer,
            origin=origin,
            connect_timeout=args.connect_timeout,
            read_timeout=args.timeout,
        )
        print(split_report(split, last_contact=args.last_contact, label=args.label))
        return 0

    print(
        f"Measuring against {origin}. Postgres is provisioned first, before pandan is touched — "
        "otherwise the container startup would be the thing that warms the upstream.",
        file=sys.stderr,
    )

    with _database(args.database_url) as session_factory:
        result = measure(
            bearer=bearer,
            origin=origin,
            session_factory=session_factory,
            warm_repeats=args.warm_repeats,
            hit_repeats=args.hit_repeats,
            timeout=args.timeout,
        )

    print(report(result, last_contact=args.last_contact, label=args.label))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
