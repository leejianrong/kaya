"""In-memory stand-ins used across the unit layer.

Before ADR 0012's cutover (KAN-1740) this module also held `FakeUpstream`/`FakeMirror`, the two
collaborators ADR 0002's `PrincipalResolver` was built to run against with no network. That
resolver is gone — `app/auth/kaya_principal.py`'s lookup is a plain database read a unit test fakes
by overriding `get_principal` directly with a fixed `Principal`, not by faking a collaborator three
layers down — so what remains here is the still-generically-useful part: fixed `Principal`s for
"alice"/"bob", opaque bearer strings that assert nothing about kaya's own token shape, an injectable
clock. (`FakeTeamUpstream` went with ADR 0011's team stack, ADR 0017.)
"""

import uuid

from app.auth.principal import Principal

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
