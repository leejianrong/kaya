"""`scripts/lib/release_drift.py`'s decision, pinned (KAN-1763).

The decision is a pure function of the commits since the latest `v*` tag (their changed paths), the
tag's age and the clock, so none of this needs git or GitHub. It lives in this package's suite for
the same reason `test_version_bump_classifier.py` does: it tests a repository script, and this is
the Python suite that runs on every PR.

Mutating the guard: delete `backend/app/identity/` from `DEPLOY_SENSITIVE` and the first
parametrised case fails.
"""

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "lib" / "release_drift.py"
_spec = importlib.util.spec_from_file_location("release_drift", SCRIPT)
assert _spec and _spec.loader
rd = importlib.util.module_from_spec(_spec)
sys.modules["release_drift"] = rd
_spec.loader.exec_module(rd)

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def commit(*paths: str, subject: str = "change") -> "rd.Commit":
    return rd.Commit(subject=subject, paths=tuple(paths))


def decide(commits: list, age_days: float, tag: str = "v0.24.0") -> "rd.Decision":
    return rd.decide(commits, tag, NOW - timedelta(days=age_days), NOW)


@pytest.mark.parametrize(
    "path",
    [
        "backend/app/identity/router.py",
        "backend/app/auth/dependencies.py",
        "backend/app/config.py",
        "backend/alembic/versions/0009_x.py",
        "fly.toml",
        "Dockerfile",
        ".github/workflows/release.yml",
    ],
)
def test_a_deploy_sensitive_path_opens_on_day_zero(path: str) -> None:
    d = decide([commit(path)], age_days=0.1)
    assert d.action == "open"
    assert d.deploy_sensitive is True
    assert path in d.sensitive_paths


def test_zero_commits_closes() -> None:
    assert decide([], age_days=30).action == "close"


def test_fresh_ordinary_code_change_stays_quiet() -> None:
    assert decide([commit("backend/app/api/notes.py")], age_days=3).action == "none"


def test_old_ordinary_code_change_opens() -> None:
    d = decide([commit("frontend/src/App.svelte")], age_days=8)
    assert d.action == "open"
    assert d.deploy_sensitive is False


def test_exactly_seven_days_is_not_more_than_seven() -> None:
    assert decide([commit("backend/app/api/notes.py")], age_days=7).action == "none"


def test_docs_only_drift_never_opens_however_old() -> None:
    commits = [commit("docs/PLAN.md"), commit("README.md"), commit("docs/adr/0001.md")]
    assert decide(commits, age_days=90).action == "none"


def test_test_only_and_ci_only_drift_do_not_count_as_shipped() -> None:
    commits = [commit("backend/tests/unit/test_x.py"), commit(".github/workflows/ci.yml")]
    assert decide(commits, age_days=90).action == "none"


def test_title_names_count_and_tag() -> None:
    d = decide([commit("backend/app/config.py"), commit("docs/x.md")], age_days=2)
    assert d.title == "Release needed: main is 2 commits ahead of v0.24.0"


def test_title_is_singular_for_one_commit() -> None:
    assert decide([commit("fly.toml")], age_days=1).title.endswith("1 commit ahead of v0.24.0")


def test_body_reports_the_three_facts() -> None:
    d = decide([commit("backend/app/auth/x.py", subject="Rotate thing")], age_days=9.5)
    assert "9 days" in d.body
    assert "Rotate thing" in d.body
    assert "backend/app/auth/x.py" in d.body
    assert "never tags" in d.body


def test_no_tag_at_all_does_not_open() -> None:
    d = rd.decide([commit("fly.toml")], None, None, NOW)
    assert d.action == "none"


def test_parse_log_reads_the_git_log_shape() -> None:
    raw = "\x1eaaa\x1fFirst\n\nbackend/app/config.py\nfly.toml\n\x1ebbb\x1fSecond\n\ndocs/a.md\n"
    commits = rd.parse_log(raw)
    assert [c.subject for c in commits] == ["First", "Second"]
    assert commits[0].paths == ("backend/app/config.py", "fly.toml")
    assert commits[1].paths == ("docs/a.md",)
