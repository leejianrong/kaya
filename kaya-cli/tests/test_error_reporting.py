"""Both streams and the exit code, asserted together — because the bug is always in the seam.

ADR 0005 §contract 3 is two claims about one event: the structured row goes to **stdout** and the
human ``usage:`` text goes to **stderr**. Either half is easy to get right alone. The way it breaks
is one of them silently taking the other's stream, which no test asserting a single stream can see.
So every test here asserts stdout, stderr and the return value in one go.

`test_exit_codes.py` owns the numbers. This file owns where the bytes go.
"""

import json
import subprocess
import sys

import pytest

from kaya_cli.__main__ import main


def run(*argv: str) -> subprocess.CompletedProcess[str]:
    """The real process, because ``main``'s return value is not the same fact as ``$?``.

    Every other test here calls ``main`` directly; that proves the code is computed and proves
    nothing about whether it reaches the shell. The console script's ``sys.exit(main(...))`` is one
    line and it is the line an operator's ``if [ $? -eq 2 ]`` depends on.
    """
    return subprocess.run(
        [sys.executable, "-m", "kaya_cli", *argv], capture_output=True, text=True, check=False
    )


# --------------------------------------------------------------- the unknown flag


def test_an_unknown_flag_puts_usage_on_stderr_and_the_row_on_stdout(capsys) -> None:
    """The card's headline case, all three assertions in one place.

    argparse's default would have printed the usage block, called ``sys.exit(2)``, and emitted
    nothing a program could read. `kaya_cli.parsing` intercepts both halves so both audiences are
    served from one event.
    """
    code = main(["--nope"])
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out.startswith("error\tusage\t")
    assert captured.out.endswith("\n")
    assert captured.err.startswith("usage: kaya")
    assert "kaya: error: unrecognized arguments: --nope" in captured.err


def test_the_row_names_the_flag_argparse_rejected(capsys) -> None:
    """A row that said only "usage" would leave the caller with a code and no way to act on it."""
    main(["--nope"])
    row = capsys.readouterr().out.rstrip("\n").split("\t")

    assert row[0] == "error"
    assert row[1] == "usage"
    assert "--nope" in row[2]
    assert len(row) == 4


def test_an_unknown_positional_is_also_a_usage_error(capsys) -> None:
    """A word the CLI does not have must be *refused*, not ignored.

    This replaces V1's placeholder assertion that unknown argv returned `0`. A CLI that silently
    accepts a verb it does not have is a CLI that reports success for work it never did — the exact
    shape of failure an agent cannot detect. `note list` is a real verb since KAN-541, so the
    assertion moved to a word that is not; the property is unchanged.
    """
    code = main(["notebook", "list"])
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out.startswith("error\tusage\t")
    assert "usage: kaya" in captured.err


def test_nothing_structured_reaches_stderr(capsys) -> None:
    """The inverse of the contract, which is the half a refactor breaks.

    Moving the row to stderr "so errors go where errors go" would satisfy every assertion about the
    row's bytes and break the reason it exists: an agent reading the CLI should not have to merge
    two streams to find out what happened.
    """
    main(["--nope"])
    captured = capsys.readouterr()

    assert "error\t" not in captured.err
    assert "usage:" not in captured.out


def test_the_exit_code_reaches_the_shell() -> None:
    result = run("--nope")

    assert result.returncode == 2
    assert result.stdout.startswith("error\tusage\t")
    assert result.stderr.startswith("usage: kaya")


# ------------------------------------------------------------------ the quiet paths


def test_a_bare_invocation_still_succeeds_on_stdout_alone(capsys, answering) -> None:
    """ADR 0005 §contract 7. The parser is empty, so this is the path most at risk from it.

    KAN-549 gave a bare invocation a **session**, so it now needs an API to succeed against. What
    this file still owns is the stream discipline: everything on stdout, stderr untouched, and no
    error row on a successful read. `tests/test_bare_invocation.py` owns what the output says.
    """
    answering(200, {"notes": []})
    code = main([])
    captured = capsys.readouterr()

    assert code == 0
    assert captured.out.startswith("kaya ")
    assert captured.err == ""
    assert "error\t" not in captured.out


def test_a_bare_invocation_with_no_credential_reports_on_stdout(capsys) -> None:
    """The other half, and the reason contract 7 carries a note about it: with nothing configured a
    bare `kaya` is a *failure*, and it has to be the same four-field row every other failure is — on
    stdout, stderr clean, and with no banner in front of it for a reader to have to skip."""
    code = main([])
    captured = capsys.readouterr()

    assert code == 1
    assert captured.out.startswith("error\tno_credential\t")
    assert captured.err == ""


def test_help_exits_zero_and_is_not_an_error(capsys) -> None:
    """``--help`` is argparse ending the process, not a failure. It gets no error row.

    The distinction is `parsing.ParserExit` against ``UsageError``, and it is worth a test because
    the tempting simplification — treat every argparse exit as a failure and return its status — is
    correct for exit `2` and silently emits an error row for exit `0`.
    """
    code = main(["--help"])
    captured = capsys.readouterr()

    assert code == 0
    assert captured.out.startswith("usage: kaya")
    assert "error\t" not in captured.out
    assert captured.err == ""


def test_argparse_never_exits_the_process_itself() -> None:
    """The interception, stated as the property it buys.

    A ``SystemExit`` escaping ``main`` would bypass the funnel entirely, and the failure it reported
    would be the one path with no test on it. ``pytest.raises(SystemExit)`` inverted: nothing here
    may raise it at all.
    """
    for argv in (["--nope"], ["--help"], [], ["note"], ["note", "get"]):
        assert isinstance(main(argv), int)


# ---------------------------------------------------------------- the shared shape


def test_a_reported_failure_renders_through_the_client(capsys) -> None:
    """`kaya-cli` owns the stream and the number; `kaya-client` owns every byte of the shape.

    Asserted by rendering the same failure both ways and comparing. If a formatting rule ever
    appeared in this package — ADR 0004's "a projection rule appearing in `kaya-cli/` is a bug" —
    the two would diverge and this is what would say so.
    """
    from kaya_client import ApiError, render_error

    from kaya_cli.failures import report

    failure = ApiError(404, {"error": {"code": "note_not_found", "message": "no such note"}})
    code = report(failure)

    assert capsys.readouterr().out == f"{render_error(failure)}\n"
    assert code == 5


@pytest.mark.parametrize("fmt", ["human", "json"])
def test_report_honours_the_format_it_is_given(capsys, fmt: str) -> None:
    """KAN-541 wires ``--format`` to this argument. The seam is here so that 541 adds a flag rather
    than a branch, and so the error under ``--format json`` is the client's object, unedited."""
    from kaya_client import ApiError

    from kaya_cli.failures import report

    failure = ApiError(403, {"error": {"code": "note_forbidden", "message": "not yours"}})
    assert report(failure, fmt=fmt) == 4

    out = capsys.readouterr().out
    if fmt == "json":
        assert json.loads(out) == {
            "error": {"code": "note_forbidden", "message": "not yours", "arg": ""}
        }
    else:
        assert out == "error\tnote_forbidden\tnot yours\t\n"
