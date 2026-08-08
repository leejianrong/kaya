"""`kaya --version`, both forms, asserted whole (ADR 0007 §1).

`kaya_client/tests/test_provenance.py` proves the string; this proves the *command* — that the flag
is wired to it, that it goes to stdout, and that it exits `0`. Between them there is no gap where
the CLI could print something else.
"""

import subprocess
import sys

import pytest
from kaya_client import provenance

import kaya_cli
from kaya_cli.__main__ import main

A_SHA = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"


@pytest.fixture
def stamped(monkeypatch):
    def stamp(sha: str) -> None:
        monkeypatch.setattr(provenance, "COMMIT", sha)

    return stamp


def test_version_on_a_released_build_is_the_version_and_the_short_sha(capsys, stamped) -> None:
    stamped(A_SHA)

    code = main(["--version"])

    assert capsys.readouterr().out == f"kaya {kaya_cli.__version__} (a1b2c3d)\n"
    assert code == 0


def test_version_on_a_source_checkout_says_it_is_not_a_released_build(capsys, stamped) -> None:
    """The explanatory clause, not a bare number. This exact silence cost pandan two false bug
    reports (`KAN-435`), which is why the assertion is on the whole line."""
    stamped("")

    code = main(["--version"])

    expected = f"kaya {kaya_cli.__version__} (source checkout, not a released build)\n"
    assert capsys.readouterr().out == expected
    assert code == 0


def test_an_unstamped_build_reports_the_source_form_rather_than_an_empty_sha(capsys, stamped):
    """The failure direction: "I am not a release" is safe, a plausible-looking sha is not."""
    stamped("")
    main(["--version"])
    out = capsys.readouterr().out

    assert "()" not in out
    assert "unknown" not in out
    assert out.strip() != f"kaya {kaya_cli.__version__}"
    assert "source checkout, not a released build" in out


@pytest.mark.parametrize("junk", ["", "   ", "unknown", "${GITHUB_SHA}", "0" * 40, "a1b2c3"])
def test_a_badly_stamped_build_reports_the_source_form_too(capsys, stamped, junk) -> None:
    stamped(junk)

    assert main(["--version"]) == 0
    assert capsys.readouterr().out.endswith("(source checkout, not a released build)\n")


def test_version_exits_zero_through_the_installed_script() -> None:
    """The value the console script hands the shell, from a real process.

    Every other test here calls `main` directly, so they would all pass with `--version` wired to
    something that printed and then raised. `--version` is a successful answer to a question, not
    an early exit, and KAN-542's code table starts from that.
    """
    result = subprocess.run(
        [sys.executable, "-m", "kaya_cli", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.startswith(f"kaya {kaya_cli.__version__} (")
    assert result.stdout.rstrip().endswith(")")
    assert result.stderr == ""


def test_the_checkout_this_test_runs_in_is_not_stamped() -> None:
    """Unstamped is the state of a working tree, and it is what the two forms above are about."""
    assert provenance.build_sha() is None
