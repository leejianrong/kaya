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

import kaya_cli
from kaya_cli.__main__ import main

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def declared() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]


def test_main_prints_a_banner_and_exits_zero(capsys) -> None:
    code = main([])
    out = capsys.readouterr().out

    assert code == 0
    assert out.startswith("kaya ")
    assert kaya_cli.__version__ in out


def test_main_does_not_choke_on_arguments_it_does_not_understand_yet() -> None:
    assert main(["note", "list", "--format", "json"]) == 0


def test_there_is_exactly_one_console_script_and_it_is_named_kaya() -> None:
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
    """
    kaya = shutil.which("kaya")
    if kaya is None:  # pragma: no cover - only when run outside the project environment
        pytest.skip("`kaya` is not on PATH; run under `uv run pytest`")

    result = subprocess.run([kaya], capture_output=True, text=True, check=False)

    assert result.returncode == 0
    assert result.stdout.startswith("kaya ")
    assert result.stderr == ""


def test_the_module_is_also_runnable_with_dash_m() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "kaya_cli"], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0
    assert result.stdout.startswith("kaya ")
