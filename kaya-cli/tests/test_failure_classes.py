"""SLICES §V2a's six failure classes, end to end, each asserting **stream, shape and exit code**.

    unknown flag (2) · invalid enum (2) · missing token (1) · 404 (5) · 401 (3) · 403 (4)

KAN-542 built the error contract with no verbs to produce it, so it could only prove these at the
unit seam — `kaya-client/tests/test_error_contract.py` owns the shape and
`tests/test_exit_codes.py` owns the numbers, both by construction. This file is the card that gets
to close that: a `404` here is a real ``ApiError`` raised by the real ``KayaClient`` from a real
response, travelling the real funnel in ``main``, printed by the real ``report``.

**All three assertions in one test per class, deliberately.** Each half is easy to get right alone;
the way the contract breaks is one half silently taking the other's stream — a structured row on
stderr satisfies every assertion about the row's bytes while destroying the reason it exists. The
table below is therefore parametrised over the *event*, and each case asserts stdout, stderr and the
returned int together.

The three refusal classes are keyed on **status** rather than on the API's code string, which is why
each carries a code the backend does not emit today: the backend's vocabulary grows without this
package's knowledge and a new `404` code must still exit `5`.
"""

import json
import subprocess
import sys

import httpx
import pytest
from conftest import NOTES

from kaya_cli.__main__ import main

REFUSALS = [
    (404, "note_not_found", 5, ["note", "get", "NOTE-9999"]),
    (401, "invalid_token", 3, ["note", "list"]),
    (403, "note_forbidden", 4, ["note", "get", "NOTE-1"]),
    (404, "a_code_this_package_has_never_heard_of", 5, ["note", "get", "NOTE-9999"]),
    (401, "authentication_required", 3, ["note", "list"]),
]


@pytest.mark.parametrize(
    ("status", "code", "exit_code", "argv"),
    REFUSALS,
    ids=[f"{status} {code}" for status, code, _, _ in REFUSALS],
)
def test_an_api_refusal_reports_its_shape_stream_and_number(
    capsys, answering, status: int, code: str, exit_code: int, argv: list[str]
) -> None:
    answering(status, {"error": {"code": code, "message": "no"}})

    result = main(argv)
    captured = capsys.readouterr()

    assert result == exit_code
    assert captured.out == f"error\t{code}\tno\t\n"
    assert captured.err == ""


def test_an_unknown_flag_reports_its_shape_stream_and_number(capsys) -> None:
    """Class 1. Argparse's own `2`, but reached through `failures.EXIT_FOR_CODE["usage"]`, and with
    the half argparse could never do: the structured row on stdout beside the usage text on stderr.
    """
    result = main(["note", "list", "--nope"])
    captured = capsys.readouterr()

    assert result == 2
    assert captured.out.startswith("error\tusage\t")
    assert "--nope" in captured.out
    # The *top-level* usage block: `parse_args` collects unrecognised arguments at the root, so the
    # error is the root parser's even though the flag was typed after a verb.
    assert captured.err.startswith("usage: kaya ")
    assert "error\t" not in captured.err


def test_an_invalid_enum_reports_its_shape_stream_and_number(capsys) -> None:
    """Class 2. A value outside ``--format``'s choices is argv being wrong, not the API."""
    result = main(["note", "list", "--format", "hunan"])
    captured = capsys.readouterr()

    assert result == 2
    assert captured.out.startswith("error\tusage\t")
    assert "hunan" in captured.out
    assert captured.err.startswith("usage: kaya note list")
    assert "error\t" not in captured.err


def test_a_missing_token_reports_its_shape_stream_and_number(capsys) -> None:
    """Class 3, and the one whose *number* is worth arguing about.

    `1`, not `3`. Nothing was refused, because nothing was asked — there is no bearer to reject. A
    script reacting to `3` re-authenticates, and re-authenticating a credential that was never
    presented mints a PAT to fix a missing line of configuration. SLICES §V2a's table says `1` and
    `errors.MissingCredential` names the meaning ``no_credential`` so the raise site never picked a
    number.

    ``conftest``'s autouse fixture is what makes this reachable: it clears ``KAYA_TOKEN`` from the
    environment, so this is a genuinely unconfigured invocation rather than a mocked one.
    """
    result = main(["note", "list"])
    captured = capsys.readouterr()

    assert result == 1
    assert captured.out.startswith("error\tno_credential\t")
    assert captured.out.rstrip("\n").endswith("\tKAYA_TOKEN")
    assert captured.out.count("\t") == 3
    assert captured.err == ""


def test_a_missing_token_makes_no_request_at_all(fake_api) -> None:
    """The refusal happens before a session exists, so an unconfigured shell cannot accidentally
    reach a *default* deployment with an empty bearer and get told its credential is invalid."""

    def unreachable(request):  # pragma: no cover - the point is that it never runs
        raise AssertionError("a request was made with no credential configured")

    seen = fake_api(unreachable, token="")

    assert main(["note", "list"]) == 1
    assert seen == []


def test_an_unreachable_api_is_runtime_not_unauthenticated(capsys, fake_api) -> None:
    """Not one of the six, and included because it is the one most easily collapsed into them.

    "kaya is unreachable" and "kaya said no" are different facts. Under ADR 0005's table that is
    exit `1` against exit `3`, and a script reacting to `3` discards a working credential over a
    disconnected wifi.
    """

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    fake_api(refuse)

    assert main(["note", "list"]) == 1
    assert capsys.readouterr().out.startswith("error\tunreachable\t")


# ------------------------------------------------------------ the shape, in every format


@pytest.mark.parametrize(
    ("status", "code", "exit_code", "argv"),
    REFUSALS[:3],
    ids=[f"{status}" for status, _, _, _ in REFUSALS[:3]],
)
def test_every_refusal_carries_the_contract_keys_under_a_structured_format(
    capsys, answering, status: int, code: str, exit_code: int, argv: list[str]
) -> None:
    """"All keys always present", asserted through the CLI rather than through ``error_payload``.

    A consumer branching on ``code`` must never have to write ``if "arg" in error`` — a conditional
    on an error path is a branch nobody exercises until the day it matters.
    """
    answering(status, {"error": {"code": code, "message": "no"}})

    assert main([*argv, "--format", "json"]) == exit_code
    body = json.loads(capsys.readouterr().out)

    assert set(body) == {"error"}
    assert tuple(body["error"])[:3] == ("code", "message", "arg")


def test_the_row_always_has_four_fields_whatever_failed(capsys, answering) -> None:
    """Fixed arity is the row's spelling of "all keys always present": ``split("\\t")[3]`` must be a
    value and never an ``IndexError``."""
    events = [
        (lambda: main(["note", "list", "--nope"]), None),
        (lambda: main(["note", "list", "--format", "hunan"]), None),
        (lambda: main(["note", "list"]), None),
        (lambda: main(["note", "get", "NOTE-9999"]), (404, "note_not_found")),
        (lambda: main(["note", "list"]), (401, "invalid_token")),
        (lambda: main(["note", "get", "NOTE-1"]), (403, "note_forbidden")),
    ]
    for run, refusal in events:
        if refusal is not None:
            status, code = refusal
            _install(answering, status, code)
        run()
        row = capsys.readouterr().out.rstrip("\n").split("\t")

        assert row[0] == "error"
        assert len(row) == 4


def _install(answering, status: int, code: str) -> None:
    answering(status, {"error": {"code": code, "message": "no"}})


def test_a_failure_after_a_success_would_arrive_on_one_ordered_stream(capsys, answering) -> None:
    """The reason contract 3 puts the row on **stdout** rather than stderr, stated as a test.

    An agent reading the CLI should not have to merge two streams to find out what happened. There
    is no partial-success verb in V2a, so the closest available check is that a successful render
    and a refusal reach the same stream in the order they happened.
    """
    answering(200, NOTES)
    main(["note", "list"])
    answering(404, {"error": {"code": "note_not_found", "message": "no"}})
    main(["note", "get", "NOTE-9999"])

    captured = capsys.readouterr()
    lines = captured.out.splitlines()

    assert lines[0].startswith("NOTE-12")
    assert lines[-1].startswith("error\tnote_not_found")
    assert captured.err == ""


# ------------------------------------------------------------------ and at the shell


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["note", "list", "--nope"], 2),
        (["note", "list", "--format", "hunan"], 2),
        (["note", "list"], 1),
    ],
    ids=["unknown flag", "invalid enum", "missing token"],
)
def test_the_number_reaches_the_shell(argv: list[str], expected: int) -> None:
    """``main``'s return value is not the same fact as ``$?``.

    Every other test here calls ``main`` directly, which proves the number is computed and proves
    nothing about whether it reaches an operator's ``if [ $? -eq 2 ]``. Only the three classes that
    need no faked transport can be checked this way — the other three are asserted above through the
    same funnel, and `test_error_reporting.py::test_the_exit_code_reaches_the_shell` covers the
    console script's ``sys.exit(main(...))`` line itself.
    """
    result = subprocess.run(
        [sys.executable, "-m", "kaya_cli", *argv], capture_output=True, text=True, check=False
    )

    assert result.returncode == expected
    assert result.stdout.startswith("error\t")
