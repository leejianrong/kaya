"""ADR 0007 §1: `--version` identifies the build, and an unidentifiable build says so.

The assertions here are on whole strings rather than on substrings, deliberately. Pandan's
`--version` was *correct* about the version number and still caused two false bug reports
(`KAN-435`), because what it left out was the part that mattered. A test that only checks "the
version appears somewhere" passes on exactly the output that caused the incident.
"""

import subprocess
from pathlib import Path

import pytest

from kaya_client import provenance
from kaya_client.provenance import SOURCE_CHECKOUT, build_sha, version_line

REPO_ROOT = Path(__file__).resolve().parents[2]
STAMP_MODULE = REPO_ROOT / "kaya-client" / "src" / "kaya_client" / "_build_stamp.py"
STAMP_SCRIPT = REPO_ROOT / "scripts" / "stamp-build.sh"

A_SHA = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"


@pytest.fixture
def stamped(monkeypatch):
    """Pretend to be a release build stamped with ``sha``."""

    def stamp(sha: str) -> None:
        monkeypatch.setattr(provenance, "COMMIT", sha)

    return stamp


def test_a_released_build_prints_the_version_and_the_short_sha(stamped) -> None:
    stamped(A_SHA)

    assert version_line("kaya", "1.2.3") == "kaya 1.2.3 (a1b2c3d)"


def test_a_source_checkout_says_so_in_words(stamped) -> None:
    """The clause is the deliverable. A bare number here is the pandan bug, restored."""
    stamped("")

    assert version_line("kaya", "1.2.3") == "kaya 1.2.3 (source checkout, not a released build)"


def test_an_unstamped_build_never_reports_an_empty_or_placeholder_sha(stamped) -> None:
    """The failure direction. `()` or `(unknown)` would both read as provenance to a human."""
    stamped("")
    line = version_line("kaya", "1.2.3")

    assert build_sha() is None
    assert "()" not in line
    assert "unknown" not in line
    assert SOURCE_CHECKOUT in line


@pytest.mark.parametrize(
    ("stamp", "why"),
    [
        ("", "never stamped"),
        ("   ", "stamped with whitespace"),
        ("unknown", "a sentinel word someone thought was harmless"),
        ("${GITHUB_SHA}", "a workflow template that never expanded"),
        ("$GITHUB_SHA", "the same, unbraced"),
        ("HEAD", "a revision name rather than a revision"),
        ("dev", "a build-system default"),
        ("a1b2c3", "six characters — shorter than anything git abbreviates to"),
        ("A1B2C3D4E5F6", "uppercase, which git does not write"),
        ("g1h2i3j4k5l6", "the right shape, but not hex"),
        (A_SHA + "9", "forty-one characters"),
        ("0" * 40, "git's null sha, which is valid hex and means nothing"),
        ("0000000", "the null sha, abbreviated"),
    ],
)
def test_every_way_a_stamp_can_be_wrong_degrades_to_the_source_form(stamped, stamp, why) -> None:
    """One direction is safe and the other is not.

    Refusing a real sha costs a release job a red check. *Accepting* a fake one puts a binary in
    someone's `$PATH` claiming provenance it does not have, which is the failure that cannot be
    detected downstream — so everything that is not unmistakably a sha resolves to `None`.
    """
    stamped(stamp)

    assert build_sha() is None, why
    assert version_line("kaya", "1.2.3").endswith(f"({SOURCE_CHECKOUT})"), why


def test_build_sha_returns_the_whole_sha_and_the_line_shortens_it(stamped) -> None:
    """`build_sha` is the fact; the seven characters are a presentation choice made in one place."""
    stamped(A_SHA)

    assert build_sha() == A_SHA
    assert version_line("kaya", "1.2.3").endswith(f"({A_SHA[:7]})")


def test_a_seven_character_stamp_is_accepted_whole(stamped) -> None:
    stamped("a1b2c3d")

    assert version_line("kaya", "1.2.3") == "kaya 1.2.3 (a1b2c3d)"


def test_the_program_name_and_version_come_from_the_caller(stamped) -> None:
    """Why this is not hard-coded: V6's MCP server reports its own provenance through this same
    function rather than growing a second copy of the string (ADR 0004)."""
    stamped(A_SHA)

    assert version_line("kaya-mcp", "0.9.1") == "kaya-mcp 0.9.1 (a1b2c3d)"


def test_the_committed_stamp_is_empty() -> None:
    """A committed sha would make every source checkout claim to be a release of one old commit.

    That is the same class of failure as pandan's stale binary and harder to notice, because the
    string looks right. The release job therefore stamps *after* the tests and before the build;
    see `_build_stamp.py`'s docstring.
    """
    assert 'COMMIT = ""' in STAMP_MODULE.read_text(encoding="utf-8")


def _stamp_into(tmp_path: Path, sha: str) -> subprocess.CompletedProcess:
    target = tmp_path / "_build_stamp.py"
    target.write_text('"""doc."""\n\nCOMMIT = ""\n', encoding="utf-8")
    return subprocess.run(
        ["bash", str(STAMP_SCRIPT), sha, str(target)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_stamp_script_writes_a_module_that_reads_back_as_the_sha(tmp_path) -> None:
    result = _stamp_into(tmp_path, A_SHA)
    written = (tmp_path / "_build_stamp.py").read_text(encoding="utf-8")
    namespace: dict = {}
    exec(compile(written, "_build_stamp.py", "exec"), namespace)

    assert result.returncode == 0, result.stderr
    assert namespace["COMMIT"] == A_SHA
    assert '"""doc."""' in written, "the docstring explaining the constant survives the rewrite"


@pytest.mark.parametrize("bad", ["", "unknown", "${GITHUB_SHA}", "0" * 40, "a1b2c3", A_SHA.upper()])
def test_the_stamp_script_refuses_anything_that_is_not_a_sha(tmp_path, bad) -> None:
    """Both ends apply the same rule, so a bad stamp fails the *build* rather than a user's read."""
    result = _stamp_into(tmp_path, bad)

    assert result.returncode != 0
    assert 'COMMIT = ""' in (tmp_path / "_build_stamp.py").read_text(encoding="utf-8")
