#!/usr/bin/env python3
"""Turn one audit tool's JSON into one section of the human report. KAN-699.

Called only by ``scripts/dependency-audit.sh``; see that file's header for why the audit is a
report rather than a gate. This half exists because both ``npm audit`` and ``pip-audit`` overload
their exit code — non-zero means "found something" *and* "failed", indistinguishably — so the
decision has to come from the report body. Reading the JSON is also what makes the ``dev-only``
marker possible, and that marker is the single most useful fact about an advisory nobody can fix.

Usage:
    audit_report.py npm <audit-all.json> <audit-omit-dev.json>
    audit_report.py pip <label> <pip-audit.json> <runtime-requirements.txt>

Exit codes match the caller's contract:
    0  clean
    1  advisories found
    2  the report could not be read — a malfunction, not a clean tree

Deliberately dependency-free: it runs under whatever ``python3`` is on the box, with no virtualenv
and no install step, because it has to work in the same breath as ``npm audit``.
"""

from __future__ import annotations

import json
import re
import sys

CLEAN, FOUND, UNREADABLE = 0, 1, 2

# Loudest first, so a report skimmed from the top reads worst-first.
SEVERITY_ORDER = ["critical", "high", "moderate", "medium", "low", "info", "unknown"]


def die(message: str) -> int:
    print(f"  ✗ {message}")
    return UNREADABLE


def load(path: str) -> object | None:
    """Parse a JSON file, or None. None always means "cannot trust this", never "clean"."""
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def normalise(name: str) -> str:
    """PEP 503 name normalisation, so `typing_extensions` and `Typing-Extensions` compare equal."""
    return re.sub(r"[-_.]+", "-", name).strip().lower()


def emit(header: str, rows: list[str], clean_note: str) -> int:
    print(f"▸ {header}")
    if not rows:
        print(f"  ✓ {clean_note}")
        return CLEAN
    count = len(rows)
    print(f"  ✗ {count} advisor{'y' if count == 1 else 'ies'}")
    for row in rows:
        print(row)
    return FOUND


def sort_key(severity: str) -> int:
    try:
        return SEVERITY_ORDER.index(severity.lower())
    except ValueError:
        return len(SEVERITY_ORDER)


# --------------------------------------------------------------------------------- npm ----------


def npm_advisory_urls(via: object) -> tuple[str, str]:
    """Pull a title and an advisory URL out of npm's `via`.

    `via` mixes two element types: a dict for a direct advisory, and a bare string naming another
    vulnerable package when the vulnerability is inherited. Only the dicts carry a URL, and a
    package can legitimately have none of them — hence the empty-string fallbacks rather than a
    KeyError that would be reported as a broken audit.
    """
    if not isinstance(via, list):
        return "", ""
    for entry in via:
        if isinstance(entry, dict):
            return str(entry.get("title", "")), str(entry.get("url", ""))
    return "", ""


def npm_report(all_path: str, prod_path: str) -> int:
    data = load(all_path)
    # `metadata` is npm's own summary block. Its absence means the tool errored (network, a corrupt
    # lockfile, an npm too old for `--json`) and printed something else into the file.
    if not isinstance(data, dict) or "metadata" not in data:
        return die("frontend (npm) — `npm audit --json` produced no usable report")

    vulns = data.get("vulnerabilities") or {}
    if not isinstance(vulns, dict):
        return die("frontend (npm) — unexpected `vulnerabilities` shape")

    # The runtime-only view. If it is missing, every advisory simply goes unmarked: an absent second
    # opinion must never be read as evidence that something is dev-only.
    prod = load(prod_path)
    prod_names = set()
    prod_known = isinstance(prod, dict) and "metadata" in prod
    if prod_known:
        prod_names = set((prod.get("vulnerabilities") or {}).keys())

    rows = []
    for name, item in sorted(vulns.items(), key=lambda kv: sort_key(str(kv[1].get("severity", "")))):
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity", "unknown"))
        rng = str(item.get("range", ""))
        title, url = npm_advisory_urls(item.get("via"))

        markers = []
        if prod_known and name not in prod_names:
            markers.append("dev-only")
        if item.get("isDirect"):
            markers.append("direct")
        # `fixAvailable` is `true`, `false`, or an object describing a fix that needs a semver-major
        # bump. The third case is the one worth calling out separately: it is a fix you can take,
        # but not one to merge unread.
        fix = item.get("fixAvailable")
        if isinstance(fix, dict):
            major = " (semver-major)" if fix.get("isSemVerMajor") else ""
            markers.append(f"fix: {fix.get('name')}@{fix.get('version')}{major}")
        elif fix:
            markers.append("fix: available")
        else:
            markers.append("NO FIX AVAILABLE")

        rows.append(
            f"      {name} {rng}  [{severity}]  {'  '.join(markers)}"
            + (f"\n        {title}" if title else "")
            + (f"\n        {url}" if url else "")
        )

    deps = (data.get("metadata") or {}).get("dependencies") or {}
    total = deps.get("total", "?")
    return emit("frontend (npm)", rows, f"no known advisories across {total} installed packages")


# --------------------------------------------------------------------------------- pip ----------


def runtime_names(path: str) -> set[str] | None:
    """Names from a `uv export` with no extras — i.e. what a consumer of the wheel installs.

    Returns None when the file is unreadable, which suppresses the dev-only marker rather than
    guessing. Environment markers (`; sys_platform == 'win32'`) are dropped; a package that is
    runtime on one platform is runtime.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return None
    names = set()
    for line in lines:
        line = line.split("#", 1)[0].split(";", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        names.add(normalise(re.split(r"[=<>!~\[ ]", line, maxsplit=1)[0]))
    return names


def pip_report(label: str, report_path: str, runtime_path: str) -> int:
    data = load(report_path)
    # pip-audit always emits a `dependencies` list, empty or not. Anything else means it failed
    # before it got to writing a report.
    if not isinstance(data, dict) or not isinstance(data.get("dependencies"), list):
        return die(f"{label} (uv) — pip-audit produced no usable report")

    runtime = runtime_names(runtime_path)

    rows = []
    audited = 0
    for dep in data["dependencies"]:
        if not isinstance(dep, dict):
            continue
        audited += 1
        name = str(dep.get("name", "?"))
        version = str(dep.get("version", "?"))
        for vuln in dep.get("vulns") or []:
            if not isinstance(vuln, dict):
                continue
            markers = []
            if runtime is not None and normalise(name) not in runtime:
                markers.append("dev-only")
            fixes = [str(v) for v in (vuln.get("fix_versions") or [])]
            markers.append(f"fix: {', '.join(fixes)}" if fixes else "NO FIX AVAILABLE")
            aliases = [str(a) for a in (vuln.get("aliases") or []) if str(a).startswith("CVE-")]
            ident = str(vuln.get("id", "?"))
            if aliases:
                ident += f" ({', '.join(aliases)})"
            rows.append(f"      {name}=={version}  [{ident}]  {'  '.join(markers)}")

    # pip-audit reports no severity at all, so unlike the npm half these rows are already in the
    # only order there is. Saying so beats a sort that silently does nothing.
    return emit(f"{label} (uv)", rows, f"no known advisories across {audited} pinned packages")


def main(argv: list[str]) -> int:
    if len(argv) >= 4 and argv[1] == "npm":
        return npm_report(argv[2], argv[3])
    if len(argv) >= 5 and argv[1] == "pip":
        return pip_report(argv[2], argv[3], argv[4])
    print(__doc__, file=sys.stderr)
    return UNREADABLE


if __name__ == "__main__":
    sys.exit(main(sys.argv))
