"""The table-level rules `scripts/lib/pyproject_diff.py` encodes, pinned. KAN-544, ADR 0007 §3.

**Why these live in this package's suite.** They test a repository script rather than
`kaya_client`, exactly as `test_provenance.py` already tests `scripts/stamp-build.sh` — the two are
halves of one mechanism, and `kaya-client` is the only Python suite that runs on every PR without
belonging to an adapter. Nothing here imports `kaya_client`; the subprocess boundary is the point,
since the shell caller is the only real consumer.

**Why they are worth writing at all.** ADR 0007 §5's mutation tests prove the guard fires and stays
quiet on whole git states, which is the acceptance criterion and is not repeatable in CI. These
pin the individual rules underneath, and the rule most worth pinning is the one that stops the
guard being useful if it goes wrong in the *quiet* direction: `[project.dependencies]` is
behavioural and `uv.lock`, `[build-system].requires` and the `dev` extra are not. Get the first one
wrong and an unreleased change ships; get the others wrong and every Dependabot PR reddens until
someone deletes the guard.

The `uv.lock` half of that rule is the shell caller's, not this script's — `not_behavioural()` in
`scripts/check-version-bump.sh` — because a lockfile is a whole file rather than a table.
"""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

CLASSIFIER = Path(__file__).resolve().parents[2] / "scripts" / "lib" / "pyproject_diff.py"

BASE = """\
[project]
name = "kaya-client"
version = "0.3.0"
description = "the shared core"
requires-python = ">=3.12"
dependencies = ["httpx>=0.28"]

[project.optional-dependencies]
dev = ["pytest>=8.3", "ruff>=0.9"]

[build-system]
requires = ["hatchling>=1.31.0"]
build-backend = "hatchling.build"

[tool.ruff]
line-length = 100

[tool.hatch.build.targets.wheel]
packages = ["src/kaya_client"]
"""


def classify(tmp_path: Path, head: str, base: str = BASE) -> tuple[str, list[str]]:
    """Run the classifier over two pyprojects. Returns (version verdict, behavioural tables)."""
    base_path, head_path = tmp_path / "base.toml", tmp_path / "head.toml"
    base_path.write_text(textwrap.dedent(base))
    head_path.write_text(textwrap.dedent(head))

    done = subprocess.run(
        [sys.executable, str(CLASSIFIER), str(base_path), str(head_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    verdict, tables = "", []
    for line in done.stdout.splitlines():
        kind, *fields = line.split("\t")
        if kind == "version":
            verdict = fields[2]
        elif kind == "behavioural":
            tables.append(fields[0])
    return verdict, tables


def edited(old: str, new: str) -> str:
    assert old in BASE, f"fixture drifted: {old!r} is not in BASE"
    return BASE.replace(old, new)


# --- the three rules CLAUDE.md §Conventions §Versioning fixes by name -----------------------------


def test_a_runtime_dependency_is_behavioural(tmp_path) -> None:
    """It becomes `Requires-Dist`, so it changes what a consumer installs."""
    _, tables = classify(tmp_path, edited('dependencies = ["httpx>=0.28"]',
                                          'dependencies = ["httpx>=0.29"]'))

    assert tables == ["[project].dependencies"]


def test_the_dev_extra_is_not_behavioural(tmp_path) -> None:
    """The test toolchain. A `pytest` bump is not a release, and CLAUDE.md says so by name."""
    _, tables = classify(tmp_path, edited('dev = ["pytest>=8.3", "ruff>=0.9"]',
                                          'dev = ["pytest>=8.5", "ruff>=0.9"]'))

    assert tables == []


def test_any_other_extra_is_behavioural(tmp_path) -> None:
    """`dev` is exempt by name, not extras in general — anything else is installed on purpose."""
    _, tables = classify(tmp_path, BASE.replace(
        'dev = ["pytest>=8.3", "ruff>=0.9"]',
        'dev = ["pytest>=8.3", "ruff>=0.9"]\ncli = ["rich>=13"]',
    ))

    assert tables == ["[project.optional-dependencies].cli"]


# --- the Dependabot shapes this repository has actually merged ------------------------------------


def test_a_build_system_requires_bump_is_not_behavioural(tmp_path) -> None:
    """Commit 84278e2, verbatim: "Update hatchling requirement from >=1.27 to >=1.31.0 in /mcp",
    whose entire diff is this one line. A filename-level guard reddens that merged PR."""
    _, tables = classify(tmp_path, edited('requires = ["hatchling>=1.31.0"]',
                                          'requires = ["hatchling>=1.32.0"]'))

    assert tables == []


def test_swapping_the_build_backend_is_behavioural(tmp_path) -> None:
    """`requires` is the tool's version; `build-backend` is a different tool, and a different
    artifact. No bot rewrites this key, so exempting it would buy nothing."""
    _, tables = classify(tmp_path, edited('build-backend = "hatchling.build"',
                                          'build-backend = "setuptools.build_meta"'))

    assert tables == ["[build-system].build-backend"]


# --- everything else in the table list -----------------------------------------------------------


@pytest.mark.parametrize(
    ("old", "new", "table"),
    [
        ('requires-python = ">=3.12"', 'requires-python = ">=3.13"', "[project].requires-python"),
        ('name = "kaya-client"', 'name = "kaya-core"', "[project].name"),
        ('packages = ["src/kaya_client"]', 'packages = ["src/kc"]', "[tool.hatch.build]"),
    ],
)
def test_the_rest_of_the_behavioural_surface(tmp_path, old, new, table) -> None:
    assert classify(tmp_path, edited(old, new))[1] == [table]


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ('description = "the shared core"', 'description = "the shared core, restated"'),
        ("line-length = 100", "line-length = 99"),  # [tool.ruff] — the workspace, not the wheel
        ('version = "0.3.0"', 'version = "0.4.0"'),  # the bump cannot justify itself
    ],
)
def test_the_rest_of_the_quiet_surface(tmp_path, old, new) -> None:
    assert classify(tmp_path, edited(old, new))[1] == []


def test_an_unknown_project_key_fails_closed(tmp_path) -> None:
    """PEP 621 fixes that table's vocabulary, so an unknown key is a typo or a standard that grew.
    Both are worth a human's attention, and naming it is cheaper than a silent pass."""
    _, tables = classify(tmp_path, BASE.replace(
        'name = "kaya-client"', 'name = "kaya-client"\nrequires-extras = ["nonsense"]',
    ))

    assert tables == ["[project].requires-extras"]


def test_an_unknown_top_level_table_fails_open(tmp_path) -> None:
    """Only `[project]`, `[build-system]` and `[tool.hatch.build]` can reach the wheel at all."""
    assert classify(tmp_path, BASE + '\n[something-local]\nkey = "value"\n')[1] == []


# --- the version verdict the shell reads ---------------------------------------------------------


@pytest.mark.parametrize(
    ("old", "new", "verdict"),
    [
        ('version = "0.3.0"', 'version = "0.3.0"', "unbumped"),
        ('version = "0.3.0"', 'version = "0.4.0"', "bumped"),
        ('version = "0.3.0"', 'version = "1.0.0"', "bumped"),
        ('version = "0.3.0"', 'version = "0.2.0"', "downgraded"),
        # A PEP 440 release segment followed by a pre-release marker still orders.
        ('version = "0.3.0"', 'version = "0.4.0rc1"', "bumped"),
        ('version = "0.3.0"', 'version = "0.2.0rc1"', "downgraded"),
        # Nothing to order by, so no ordering is claimed. The shell treats `changed` as a bump,
        # because a deliberate move to an unorderable version is still a deliberate move.
        ('version = "0.3.0"', 'version = "rolling"', "changed"),
    ],
)
def test_the_version_verdict(tmp_path, old, new, verdict) -> None:
    assert classify(tmp_path, edited(old, new))[0] == verdict


def test_an_unreadable_pyproject_is_a_malfunction_not_a_clean_tree(tmp_path) -> None:
    """Exit 2, never 0. "I could not tell" must never reach the shell as "nothing to see"."""
    base, head = tmp_path / "base.toml", tmp_path / "head.toml"
    base.write_text(BASE)
    head.write_text("this is not = = toml")

    done = subprocess.run(
        [sys.executable, str(CLASSIFIER), str(base), str(head)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert done.returncode == 2
    assert "could not parse" in done.stderr
