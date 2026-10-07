#!/usr/bin/env python3
"""Decide whether main has drifted far enough past the latest v* tag to need a release (KAN-1763).

On 2026-09-27 main sat 14 commits and three weeks past the last tag, so the live Fly app ran
pre-cutover code and nothing said so. `.github/workflows/release-drift.yml` calls this and keeps
one issue up to date. This script only decides and prints JSON; it never tags, deploys or talks to
GitHub, and `decide` is a pure function so the rules are unit-tested without either.

Rules. A release is due when the commits since the tag touch the deploy-sensitive surface (any day
count), or when the tag is more than 7 days old and at least one commit changed shipped code.
Docs, tests and CI-only changes do not count as shipped code. Zero commits since the tag means
caught up, which closes the issue.

Usage: release_drift.py [--now ISO8601]   (run from inside a checkout with tags fetched)
"""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from fnmatch import fnmatchcase

DEPLOY_SENSITIVE = (
    "backend/app/identity/*",
    "backend/app/auth/*",
    "backend/app/config.py",
    "backend/alembic/*",
    "fly.toml",
    "Dockerfile",
    ".github/workflows/release.yml",
)
"""fnmatch patterns (`*` crosses `/`). A change here can alter what a deploy does or needs."""

MAX_AGE_DAYS = 7


@dataclass(frozen=True)
class Commit:
    subject: str
    paths: tuple[str, ...]


@dataclass(frozen=True)
class Decision:
    action: str  # "open" | "close" | "none"
    title: str
    body: str
    ahead: int
    age_days: int
    deploy_sensitive: bool
    sensitive_paths: tuple[str, ...]
    shipped_commits: int


def is_sensitive(path: str) -> bool:
    return any(fnmatchcase(path, pattern) for pattern in DEPLOY_SENSITIVE)


def is_shipped(path: str) -> bool:
    """Does a change to this path alter what runs in production?"""
    if is_sensitive(path):
        return True
    if path.endswith(".md") or path.startswith("docs/"):
        return False
    if path.startswith(".github/"):
        return False
    return not (path.startswith("tests/") or "/tests/" in path)


def parse_log(raw: str) -> list[Commit]:
    """Parse `git log --format=%x1e%H%x1f%s --name-only` output."""
    commits = []
    for chunk in raw.split("\x1e"):
        if not chunk.strip():
            continue
        head, _, rest = chunk.partition("\n")
        subject = head.partition("\x1f")[2]
        paths = tuple(line for line in rest.splitlines() if line.strip())
        commits.append(Commit(subject=subject, paths=paths))
    return commits


def decide(commits: list[Commit], tag: str | None, tag_date: datetime | None, now: datetime) -> Decision:
    ahead = len(commits)
    if tag is None or tag_date is None:
        return Decision("none", "", "No v* tag found, nothing to compare against.", ahead, 0, False, (), 0)

    age_days = int((now - tag_date).total_seconds() // 86400)
    sensitive = sorted({p for c in commits for p in c.paths if is_sensitive(p)})
    shipped = sum(1 for c in commits if any(is_shipped(p) for p in c.paths))
    plural = "commit" if ahead == 1 else "commits"
    title = f"Release needed: main is {ahead} {plural} ahead of {tag}"

    if ahead == 0:
        action = "close"
    elif sensitive or ((now - tag_date).total_seconds() > MAX_AGE_DAYS * 86400 and shipped > 0):
        action = "open"
    else:
        action = "none"

    lines = [
        f"main is {ahead} {plural} ahead of `{tag}`, which is {age_days} days old.",
        f"{shipped} of those commits change shipped code.",
        "",
    ]
    if sensitive:
        lines.append("Deploy-sensitive files changed since the tag:")
        lines += [f"- `{p}`" for p in sensitive]
        lines.append("")
    lines.append("Commits since the tag:")
    lines += [f"- {c.subject}" for c in commits[:50]]
    if ahead > 50:
        lines.append(f"- and {ahead - 50} more")
    lines += [
        "",
        "To cut the release, follow `docs/runbooks/deploy-checklist.md` (version bump, then tag the",
        "merged sha). This workflow only reports: it never tags or deploys. The issue closes by",
        "itself when a new tag catches up.",
    ]
    return Decision(action, title, "\n".join(lines), ahead, age_days, bool(sensitive),
                    tuple(sensitive), shipped)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--now", help="ISO 8601 clock override, for tests")
    args = parser.parse_args()
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(UTC)

    tags = _git("tag", "--list", "v*", "--sort=-v:refname").split()
    tag = tags[0] if tags else None
    tag_date = None
    commits: list[Commit] = []
    if tag:
        tag_date = datetime.fromisoformat(_git("log", "-1", "--format=%cI", tag).strip())
        commits = parse_log(_git("log", "--format=%x1e%H%x1f%s", "--name-only", f"{tag}..HEAD"))
    print(json.dumps(asdict(decide(commits, tag, tag_date, now)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
