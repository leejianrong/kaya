"""In-memory stand-ins for the resolver's three collaborators.

Each one fakes at a *seam that already existed for its own reasons* rather than at a boundary
invented to make testing easier: the upstream is a Protocol because ADR 0002 makes pandan a
runtime dependency worth isolating, the mirror is a Protocol because "this UUID must be
addressable as a foreign key" is a separate job from "who is calling", and the clock is injected
because a TTL test that sleeps for a real 60 seconds is a slow test today and a flaky one later.

Together they make the whole of ADR 0002's resolver runnable with no network, no database and —
importantly — no real PAT anywhere near this repository.
"""

import uuid

from app.auth.principal import Principal, UpstreamUnavailable

# Deliberately shapeless. Kaya has no token format (ADR 0002), so a fixture that looked like a
# real PAT would be quietly asserting the opposite of the thing under test — and would trip
# scripts/secret-scan.sh, which is exactly the guard that should object to a PAT-shaped literal.
TOKEN = "a-caller-supplied-string-kaya-does-not-parse"
OTHER_TOKEN = "a-different-caller-supplied-string"

ALICE = Principal(id=uuid.UUID("11111111-1111-4111-8111-111111111111"), email="alice@example.com")
BOB = Principal(id=uuid.UUID("22222222-2222-4222-8222-222222222222"), email="bob@example.com")


class FakeClock:
    """A monotonic clock that only moves when a test says so."""

    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeUpstream:
    """An ``IdentityUpstream`` backed by a dict, counting every call it receives.

    The call count is the assertion that matters for the cache: a resolver that re-introspects on
    every request still returns the right principal, so every result-shaped assertion passes while
    the cache does nothing at all.
    """

    def __init__(self, known: dict[str, Principal] | None = None) -> None:
        self.known = dict(known or {})
        self.available = True
        self.calls: list[str] = []

    def introspect(self, bearer: str) -> Principal | None:
        self.calls.append(bearer)
        if not self.available:
            raise UpstreamUnavailable("https://pandan.invalid/api/v1/me is unreachable")
        return self.known.get(bearer)

    @property
    def call_count(self) -> int:
        return len(self.calls)


class FakeMirror:
    """A ``PrincipalMirror`` that remembers what it was asked to ensure."""

    def __init__(self) -> None:
        self.ensured: list[Principal] = []

    def ensure(self, principal: Principal) -> None:
        self.ensured.append(principal)
