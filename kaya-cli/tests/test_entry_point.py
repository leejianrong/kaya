"""One console script, named `kaya`, that actually runs.

Q39 settled that there is exactly one entry point. That is worth a test rather than a convention,
because a second script is the sort of thing that gets added helpfully — an alias, a `kaya-notes`
"for clarity" — and then has to be supported forever once someone's shell history depends on it.
"""

import shutil
import subprocess
import sys
import tomllib
from importlib.metadata import entry_points
from pathlib import Path

import pytest
from conftest import NOTES

import kaya_cli
from kaya_cli.__main__ import main, version_string

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def declared() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]


def test_main_prints_a_banner_and_exits_zero(capsys, answering) -> None:
    """KAN-549 gave a bare invocation a session, so it needs an API to answer it. What is asserted
    here is unchanged: the banner is the first thing on stdout and the exit code is `0`."""
    answering(200, NOTES)
    code = main([])
    out = capsys.readouterr().out

    assert code == 0
    assert out.startswith("kaya ")
    assert kaya_cli.__version__ in out


def test_the_banner_leads_with_the_version_line(capsys, answering) -> None:
    """So provenance is available from a mistyped command, not only from someone who knew to ask.

    ADR 0007's diagnostic only helps if the person confused by a symptom reaches it. KAN-549 put
    two more lines under this one and left it first, deliberately.
    """
    answering(200, NOTES)
    main([])
    first_line = capsys.readouterr().out.splitlines()[0]

    assert first_line == version_string()


def test_help_is_printed_to_stdout_and_exits_zero(capsys) -> None:
    code = main(["--help"])
    out = capsys.readouterr().out

    assert code == 0
    assert "--version" in out
    assert out.startswith("usage: kaya")


def test_a_verb_that_has_not_landed_yet_is_a_usage_error(capsys) -> None:
    """`note list` and `note get` landed in KAN-541. A word that has not is still unknown.

    This assertion has survived three shapes: a placeholder that returned `0` for everything, then
    KAN-543's "`note list` is not a verb yet", and now `note archive`. The invariant it has always
    been about is the one that matters — exiting `0` on a command that did nothing is the kind of
    quiet success a script cannot tell from a real one. `2` is SLICES §V2a's number for a usage
    error, and it comes from `failures.EXIT_FOR_CODE["usage"]` rather than from argparse.
    `test_verbs.py` owns which words *do* exist; `test_error_reporting.py` owns the stdout half.
    """
    code = main(["note", "archive"])

    assert code == 2
    assert "archive" in capsys.readouterr().err


def test_there_is_exactly_one_console_script_and_it_is_named_kaya() -> None:
    """No `ky`, and specifically not as a second `[project.scripts]` entry (ADR 0007 §4).

    Pandan declared `pdn` that way and had to withdraw it as a whole card (`KAN-442`): a packaging
    installer generates the alias, but the release is a PyInstaller `--onefile` build producing
    exactly one executable, so it existed for `uv tool install` users and never for anyone who
    downloaded the release asset. The README documents a symlink instead, which works on both.
    """
    scripts = declared()["scripts"]

    assert list(scripts) == ["kaya"], f"Q39: exactly one console script, got {list(scripts)}"
    assert scripts["kaya"] == "kaya_cli.__main__:main"


def test_the_entry_point_is_registered_on_the_installed_distribution() -> None:
    registered = {ep.name: ep.value for ep in entry_points(group="console_scripts")}

    assert registered.get("kaya") == "kaya_cli.__main__:main"


def test_the_distribution_is_named_kaya_notes_not_kaya() -> None:
    """PLAN §Naming: bare `kaya` on PyPI is an abandoned stub, so the distribution is `kaya-notes`
    while the *script* stays `kaya`. The two names are allowed to differ and must."""
    assert declared()["name"] == "kaya-notes"
    assert declared()["license"] == "Apache-2.0"


def test_the_installed_script_runs_end_to_end() -> None:
    """The one test that would catch a broken `[project.scripts]` target.

    Every other test here imports the module, so they would all pass with the console script
    pointing at a function that doesn't exist. This one runs the installed `kaya` binary.

    **It drives ``--version`` rather than a bare invocation, since KAN-549.** A bare `kaya` now
    opens a session, and this subprocess has no API and no credential — it would be asserting on the
    refusal path, which is a weaker witness for "the entry point works" and a stronger dependency on
    the environment. ``--version`` is answered before the dispatch, so it exercises argv → parser →
    ``main`` → stdout with nothing else in the way. The bare path with no token is checked below.
    """
    kaya = shutil.which("kaya")
    if kaya is None:  # pragma: no cover - only when run outside the project environment
        pytest.skip("`kaya` is not on PATH; run under `uv run pytest`")

    result = subprocess.run([kaya, "--version"], capture_output=True, text=True, check=False)

    assert result.returncode == 0
    assert result.stdout.startswith("kaya ")
    assert result.stderr == ""


def test_the_installed_script_answers_a_bare_invocation_with_no_credential() -> None:
    """ADR 0005 §contract 7's note, through the real console script: "a structured auth error, not a
    stack trace". Exit `1`, one four-field row on stdout, and nothing at all on stderr — which is
    where a traceback would be, and is the reason this assertion is worth its own test."""
    kaya = shutil.which("kaya")
    if kaya is None:  # pragma: no cover - only when run outside the project environment
        pytest.skip("`kaya` is not on PATH; run under `uv run pytest`")

    result = subprocess.run([kaya], capture_output=True, text=True, check=False)

    assert result.returncode == 1
    assert result.stdout.startswith("error\tno_credential\t")
    assert result.stderr == ""


def test_the_module_is_also_runnable_with_dash_m() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "kaya_cli", "--version"], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0
    assert result.stdout.startswith("kaya ")
