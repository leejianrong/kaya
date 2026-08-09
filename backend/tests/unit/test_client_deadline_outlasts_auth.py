"""The alarm on a deadline that lives in one package and is spent by another (KAN-716).

A request that misses the principal cache pays kaya's whole authentication budget before kaya has
looked at a note: `KAYA_PANDAN_CONNECT_TIMEOUT_SECONDS` to reach pandan, then
`KAYA_PANDAN_READ_TIMEOUT_SECONDS` to wait for its answer (KAN-666, `app/auth/upstream.py`). Those
two are a floor under how long *this* service may legitimately take to answer a first request on a
cold token.

`kaya-client` has to outlast that floor. A client deadline under it abandons a request the backend
was about to answer successfully and reports a `TransportError` on a working credential — which is
KAN-666's bug exactly, one layer out, and worse: the caller never learns the server was fine. That
is not hypothetical drift. KAN-540 set the client's deadline to 30 s reasoning from KAN-539's
measured 21.8 s cold introspection, which was right when written; KAN-666 then raised the backend's
worst case to 35 s and nothing anywhere noticed, because neither card could see the other's number.

**Neither package can check this for itself.** ADR 0004 points the dependency arrow at `kaya-client`
— adapters depend on the client, the client depends on neither — so the client may not import the
backend, and the backend importing the client would reverse the arrow and put an httpx-shaped
dependency in the deployed service to read one float. So the alarm goes where the change would
actually be made: raising the read budget in `app/config.py` is an edit to this package, and this is
the package whose test suite runs after it.

The number on the other side is read out of the client's **AST**, not imported: `kaya-client` is not
on this package's path and must not become so, and a text scan for `40.0` would match this
docstring. Same technique, and the same reason, as `test_error_extras_stay_addressable.py` — which
is this guard's sibling, KAN-542's version of the identical cross-package problem — and
`test_no_unscoped_note_query.py` before it.

What this does *not* do is pin the client's number from here. Lowering `DEFAULT_READ_TIMEOUT` is a
change to `kaya-client`, and `kaya-client/tests/test_client.py` catches it there. This side owns one
direction: **the backend must not outgrow what the client will wait for.**
"""

import ast
from pathlib import Path

from app.config import Settings

CLIENT_SOURCE = (
    Path(__file__).resolve().parents[3] / "kaya-client" / "src" / "kaya_client" / "client.py"
)
"""The client module, as a file rather than an import. `parents[3]` is the repository root:
`backend/tests/unit/<this file>`."""

CLIENT_READ_DEADLINE = "DEFAULT_READ_TIMEOUT"
"""The constant the invariant is about. `DEFAULT_TIMEOUT` is an `httpx.Timeout` built from it and
from `DEFAULT_CONNECT_TIMEOUT`, and a call expression is not something an AST scan should be trying
to evaluate — so the client keeps the two phases as plain literals and this reads the one that
bounds the wait for an answer."""

HANDLING_MARGIN_SECONDS = 5.0
"""What kaya is allowed for the request it was actually asked to serve, on top of authenticating it.

Generous against measurement rather than guessed: KAN-539 timed the entire warm path — the pandan
round trip *and* the mirror write — at 387 ms, of which the write was 4.7 ms, and a note read after
that is one indexed `SELECT`. Five seconds is an order of magnitude of headroom over the slowest
thing anyone has measured here, and it is deliberately not tighter: the point of a margin is to
absorb what has not been measured yet (a cold Postgres pool, a loaded pod, V2b's writes), and a
margin sized to today's numbers would need revisiting every time one of them moved.

It is a *floor*, not a target. The client is free to wait longer than this demands; what it may not
do is wait less."""


def float_constants(source: str, *, filename: str = "<memory>") -> dict[str, float]:
    """Every module-level ``NAME = <number>`` in the source.

    Deliberately narrow. Only a bare assignment of a numeric literal at module scope counts, so a
    constant that grows into an expression, moves inside a function, or turns into a call stops
    being found — and a constant that cannot be found is a failure below, not a silent pass. That is
    the right failure direction: the guard says "go and look", and something has changed that wants
    looking at.
    """
    found: dict[str, float] = {}

    for node in ast.parse(source, filename=filename).body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        else:
            continue

        value = node.value
        if not isinstance(value, ast.Constant) or not isinstance(value.value, int | float):
            continue
        if isinstance(value.value, bool):
            continue

        for target in targets:
            if isinstance(target, ast.Name):
                found[target.id] = float(value.value)

    return found


def _client_read_deadline() -> float:
    assert CLIENT_SOURCE.is_file(), (
        f"{CLIENT_SOURCE} is not there, so this guard has checked nothing. It is a path across the "
        "repository on purpose (see the module docstring); if `kaya-client` moved, move this too "
        "rather than deleting the check."
    )

    constants = float_constants(CLIENT_SOURCE.read_text(encoding="utf-8"), filename="client.py")
    assert CLIENT_READ_DEADLINE in constants, (
        f"`{CLIENT_READ_DEADLINE}` is no longer a module-level numeric literal in {CLIENT_SOURCE}. "
        "The client's request deadline has to stay readable from here, because nothing else "
        "connects it to this package's authentication budget — see the module docstring."
    )
    return constants[CLIENT_READ_DEADLINE]


def _auth_budget() -> tuple[float, float]:
    """The shipped budgets, off the field defaults rather than the environment.

    A developer's `.env` must not be able to change what this asserts about what kaya ships — the
    same reasoning, and the same spelling, as `test_pandan_timeout_split.py`.
    """
    connect = float(Settings.model_fields["pandan_connect_timeout_seconds"].default)
    read = float(Settings.model_fields["pandan_read_timeout_seconds"].default)
    return connect, read


def test_the_scan_finds_the_two_numbers_it_is_about_to_compare() -> None:
    """Without this, every assertion below could pass by finding nothing at all."""
    connect, read = _auth_budget()

    assert connect > 0 and read > 0
    assert _client_read_deadline() > 0


def test_the_client_outlasts_the_worst_case_authentication() -> None:
    """The guard. Raising this package's read budget past what `kaya-client` will wait for is a bug.

    Both budgets, not just the read one: a first request on an uncached token pays the connect phase
    and *then* the read phase, so the worst case is their sum, and a guard against the read budget
    alone would wave through a connect budget raised to a minute.
    """
    connect, read = _auth_budget()
    client_deadline = _client_read_deadline()
    required = connect + read + HANDLING_MARGIN_SECONDS

    assert client_deadline >= required, (
        f"kaya's worst-case authentication is now {connect:g}s to reach pandan plus {read:g}s to "
        f"wait for it = {connect + read:g}s, and `kaya-client`'s {CLIENT_READ_DEADLINE} is "
        f"{client_deadline:g}s. A client that gives up first turns a request this backend was "
        "about to answer into a TransportError on a working credential (KAN-716) — KAN-666's bug "
        "one layer out. Either keep KAYA_PANDAN_*_TIMEOUT_SECONDS in app/config.py inside "
        f"{client_deadline - HANDLING_MARGIN_SECONDS:g}s, or raise "
        f"{CLIENT_READ_DEADLINE} in kaya-client/src/kaya_client/client.py to at least "
        f"{required:g}s — in that package, with its version bumped, and with the invariant comment "
        "there updated."
    )


def test_the_margin_leaves_kaya_room_to_do_the_work_it_was_asked_to_do() -> None:
    """The margin is the whole reason this is an inequality and not an equality.

    Stated separately because it is the part a future edit is most likely to quietly spend: setting
    the client's deadline to exactly the auth budget satisfies "outlasts" in a reading that leaves
    zero time for the note read the caller actually wanted.
    """
    connect, read = _auth_budget()

    assert _client_read_deadline() - (connect + read) >= HANDLING_MARGIN_SECONDS


def test_the_scan_reads_a_literal_and_is_not_fooled_by_one_that_looks_like_it() -> None:
    """An emptiness assertion passes for the wrong reason unless the scanner is shown working.

    The failure mode that matters is the *quiet* one: a scan that returns nothing for a constant
    that is still there would make the guard above vacuous rather than red.
    """
    assert float_constants("DEFAULT_READ_TIMEOUT = 40.0\n") == {"DEFAULT_READ_TIMEOUT": 40.0}
    assert float_constants("DEFAULT_READ_TIMEOUT: float = 40\n") == {"DEFAULT_READ_TIMEOUT": 40.0}

    # Not module-level, so not found — and `_client_read_deadline` turns that into a red test
    # naming the constant, rather than into a pass.
    assert float_constants("def f():\n    DEFAULT_READ_TIMEOUT = 40.0\n") == {}

    # Not a literal. `httpx.Timeout(...)` and `A + B` are exactly the shapes this must refuse
    # rather than half-understand.
    assert float_constants("DEFAULT_READ_TIMEOUT = BUDGET + MARGIN\n") == {}
    assert float_constants("DEFAULT_TIMEOUT = httpx.Timeout(read=40.0)\n") == {}

    # A docstring mentioning the number is prose, which is the whole reason this is an AST scan.
    assert float_constants('"""The deadline is 40.0 seconds."""\n') == {}
