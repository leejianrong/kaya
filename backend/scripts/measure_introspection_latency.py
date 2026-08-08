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
    from app.auth.upstream import PandanIdentityUpstream

    watch = Stopwatch()
    session = session_factory()
    cache = PrincipalCache(positive_ttl=60.0, negative_ttl=10.0)
    resolver = PrincipalResolver(
        upstream=TimedUpstream(PandanIdentityUpstream(origin, timeout=timeout), watch),
        mirror=TimedMirror(SqlAlchemyPrincipalMirror(session), watch),
        cache=cache,
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
