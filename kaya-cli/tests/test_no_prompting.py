"""ADR 0005 §contract 9: no verb prompts when stdin is not a tty — "a structured failure instead of
a hang".

The failure this prevents is the worst one an agent can meet, because it produces no output at all.
A CLI that reads a missing value from stdin blocks forever behind a pipe with nothing in it; the
caller sees no row, no exit code and no error, and the only symptom is a timeout somewhere else.

Guarded from both directions, because either alone is weak:

- **Behaviourally**, by running the real process with stdin closed and a deadline. A test that
  called ``main`` in-process would prove nothing: pytest's stdin is already not a tty, so a prompt
  would raise ``OSError`` and be reported as a failure rather than as the hang it is in a shell.
- **Structurally**, by asserting the package's source contains no interactive read at all. There is
  no ``isatty`` branch in `kaya-cli`, which is stronger than a correct one: a branch that prompts
  only for a tty is a branch, and the first verb that forgets to check it is V2b's `note create`.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "kaya_cli"

TIMEOUT = 15.0
"""Generous. The assertion is "it answered", not "it was fast" — a machine under load must not turn
this into a flake, and a genuine hang is infinite."""

INTERACTIVE = {"input", "getpass", "raw_input"}
"""Every way this package could read a value from a person. ``sys.stdin`` is checked separately, by
name, because it is the one that would be spelled as an attribute rather than a call."""


@pytest.mark.parametrize(
    "argv",
    [[], ["note", "list"], ["note", "get", "NOTE-12"], ["note", "get"], ["--format", "json"]],
    ids=["bare", "list", "get", "get with no ref", "a flag with no verb"],
)
def test_no_invocation_waits_for_stdin(argv: list[str]) -> None:
    """Every argv shape, with stdin closed and nothing configured.

    ``note get`` with no ref is the case worth naming: a missing *required* argument is exactly
    where a CLI is tempted to ask for one, and the answer here is argparse's usage error.
    """
    result = subprocess.run(
        [sys.executable, "-m", "kaya_cli", *argv],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=TIMEOUT,
        check=False,
    )

    assert result.returncode in (0, 1, 2)


def test_an_unconfigured_read_is_a_structured_failure_not_a_prompt() -> None:
    """The specific case contract 9 is about: the CLI needs a credential and does not have one.

    "Ask for it" is the tempting behaviour and it is the one that hangs. The answer is
    ``MissingCredential`` — exit `1`, a four-field row on stdout naming the variable to set, and
    stderr left clean.
    """
    result = subprocess.run(
        [sys.executable, "-m", "kaya_cli", "note", "list"],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=TIMEOUT,
        check=False,
    )

    assert result.returncode == 1
    assert result.stdout.startswith("error\tno_credential\t")
    assert result.stdout.rstrip("\n").split("\t")[3] == "KAYA_TOKEN"
    assert result.stderr == ""


def test_a_closed_stdin_is_not_treated_as_input() -> None:
    """Piped-but-empty rather than closed. A ``read()`` on this returns ``""`` instead of raising,
    which is how "no verb prompts" and "no verb *reads*" come apart: a CLI that consumed stdin would
    succeed here and silently treat an empty pipe as an empty argument."""
    result = subprocess.run(
        [sys.executable, "-m", "kaya_cli", "note", "list"],
        capture_output=True,
        text=True,
        input="",
        timeout=TIMEOUT,
        check=False,
    )

    assert result.returncode == 1
    assert result.stdout.startswith("error\tno_credential\t")


# ------------------------------------------------------------------ the structural half


def _sources() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py"))


def test_the_package_contains_no_interactive_read() -> None:
    """No ``input()``, no ``getpass``, anywhere in the shipped package.

    Asserted over the AST rather than over the text, so a mention inside a docstring — this file's
    own subject matter — cannot make it pass or fail for the wrong reason.
    """
    assert _sources(), "no source files found; the path in this test is wrong"

    called: list[str] = []
    for path in _sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            is_named_call = isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            if is_named_call and node.func.id in INTERACTIVE:
                called.append(f"{path.name}: {node.func.id}()")

    assert called == []


def test_the_package_never_reads_stdin() -> None:
    """The other spelling. ``sys.stdin.read()`` is not a call to ``input`` and would hang the same
    way, and an ``isatty`` check would be a branch where there should be none."""
    for path in _sources():
        source = path.read_text(encoding="utf-8")
        code = "".join(
            line for line in source.splitlines(keepends=True) if not line.lstrip().startswith("#")
        )
        tree = ast.parse(code)
        docstrings = {
            node.value.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
            if isinstance(node.value.value, str)
        }
        without_prose = code
        for text in docstrings:
            without_prose = without_prose.replace(text, "")

        assert "stdin" not in without_prose, f"{path.name} reads stdin"
        assert "isatty" not in without_prose, f"{path.name} branches on a tty"
