#!/usr/bin/env python3
"""Classify a `pyproject.toml` change by WHICH TABLE moved, not by which file did. KAN-544.

Called only by ``scripts/check-version-bump.sh``; that file's header carries the argument for the
guard as a whole. This half exists because "the pyproject changed" is not a usable signal. Every
Dependabot PR into ``kaya-client``, ``kaya-cli`` or ``mcp`` changes that file, and if each one
demanded a version bump the guard would be a red check somebody hand-fixes every Monday — and a
check people routinely hand-fix is a check people learn to ignore (ADR 0007's "a guard that gets
ignored protects nothing", arriving from the other direction).

The evidence is already in this repository's history. Commit ``84278e2``, "Update hatchling
requirement from >=1.27 to >=1.31.0 in /mcp", is a real merged Dependabot PR whose entire diff is
one line inside ``[build-system].requires``. A filename-level guard reddens it. A table-level guard
does not, and is still right about it: the version of the build backend does not change one byte of
what the built wheel contains.

### The rule

**Behavioural means "a consumer of the built wheel could tell".** Everything below follows from
that one sentence, and CLAUDE.md §Conventions §Versioning fixes the three cases that matter:

    uv.lock alone                      the dev/CI environment. Not in the wheel.   NOT behavioural
    [project].dependencies             becomes Requires-Dist in the wheel.             BEHAVIOURAL
    [project.optional-dependencies].dev  the test toolchain, per CLAUDE.md.        NOT behavioural

``uv.lock`` is classified by the caller, since it is a whole file rather than a table.

### Where judgement was applied, and which way

- **``[build-system].requires`` is not behavioural** — see ``84278e2`` above. **``build-backend``
  is**, because swapping hatchling for setuptools genuinely changes the artifact.
- **``[project.optional-dependencies]`` is per-extra.** ``dev`` is exempt by name because CLAUDE.md
  exempts it by name. Any *other* extra is something a consumer installs on purpose, so it counts.
- **``[tool.hatch.build…]`` is behavioural**, because it decides what goes into the wheel. Every
  other ``[tool.*]`` subtable (ruff, pytest, uv sources) configures the workspace, not the artifact.
- **An unrecognised key inside ``[project]`` fails closed**, i.e. counts as behavioural and is named
  in the output. PEP 621 fixes that table's vocabulary, so the two lists below are exhaustive today
  and an unknown key is either a typo or a standard that grew — both worth a human's attention.
- **An unrecognised *top-level* table fails open.** Only ``[project]``, ``[build-system]`` and
  ``[tool.hatch.build]`` can reach the wheel at all, so anything else is by construction local.

### Output protocol

Tab-separated lines on stdout, consumed by the shell caller:

    version<TAB><base><TAB><head><TAB>bumped|unbumped|downgraded|changed
    behavioural<TAB><table path><TAB><why it reaches a consumer>

Exit ``0`` when the comparison was made, whatever its verdict, and ``2`` when it could not be —
an unreadable pyproject is a malfunction, and must never be mistaken for a clean one.

Deliberately dependency-free and stdlib-only (``tomllib`` is in 3.12), for the same reason
``lib/audit_report.py`` is: the guard runs in a pre-push hook, where there is no virtualenv to
activate and no install step to wait for.
"""

from __future__ import annotations

import sys
import tomllib

COMPARED, UNREADABLE = 0, 2

# PEP 621's `[project]` table, split by whether a consumer of the wheel could tell. Between them
# these two sets are exhaustive over the standard, with `optional-dependencies` handled per-extra
# below — so `_UNKNOWN` really does mean unknown.
BEHAVIOURAL_PROJECT_KEYS = {
    "name": "the distribution name a consumer installs",
    "dependencies": "becomes Requires-Dist in the wheel",
    "requires-python": "becomes Requires-Python; it can make an install stop resolving",
    "scripts": "the console scripts an install puts on $PATH",
    "gui-scripts": "the GUI entry points an install puts on $PATH",
    "entry-points": "the plugin surface other packages discover",
    "dynamic": "changes which metadata the backend computes at build time",
}

NON_BEHAVIOURAL_PROJECT_KEYS = {
    # The bump itself. Counting it would make every bump justify itself.
    "version",
    # Descriptive metadata. It reaches the wheel, but nothing a consumer runs changes.
    "description",
    "readme",
    "keywords",
    "authors",
    "maintainers",
    "classifiers",
    "urls",
    "license",
    "license-files",
}

# CLAUDE.md §Conventions §Versioning names this extra and calls it the test toolchain. Every other
# extra is something someone installs deliberately, so every other extra counts.
EXEMPT_EXTRA = "dev"


def die(message: str) -> int:
    print(f"pyproject_diff: {message}", file=sys.stderr)
    return UNREADABLE


def load(path: str) -> dict | None:
    """Parse a pyproject, or None. None always means "cannot trust this", never "unchanged"."""
    try:
        with open(path, "rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return None


def emit(kind: str, *fields: str) -> None:
    print("\t".join((kind, *fields)))


def numeric(version: str) -> tuple[int, ...] | None:
    """The leading numeric release segment of a PEP 440 version, or None if it isn't one.

    Enough to order `0.2.0` before `0.3.0` without depending on `packaging`, and honest about
    everything else: a version this cannot parse is reported as `changed` rather than as a bump,
    so the shell never claims an ordering it did not establish.
    """
    head = version.split("+", 1)[0].split("-", 1)[0]
    parts = head.split(".")
    out: list[int] = []
    for part in parts:
        digits = ""
        for char in part:
            if not char.isdigit():
                break
            digits += char
        if not digits:
            break
        out.append(int(digits))
        if digits != part:  # `1.0rc1` — the release segment stops here
            break
    return tuple(out) if out else None


def compare_versions(base: str, head: str) -> str:
    if base == head:
        return "unbumped"
    low, high = numeric(base), numeric(head)
    if low is None or high is None:
        return "changed"
    if high > low:
        return "bumped"
    return "downgraded"


def project_differences(base: dict, head: dict) -> list[tuple[str, str]]:
    """Behavioural differences inside `[project]`, as (table path, why) pairs."""
    found: list[tuple[str, str]] = []
    base_project = base.get("project", {})
    head_project = head.get("project", {})

    for key in sorted(set(base_project) | set(head_project)):
        if key == "optional-dependencies":
            continue
        if base_project.get(key) == head_project.get(key):
            continue
        if key in NON_BEHAVIOURAL_PROJECT_KEYS:
            continue
        why = BEHAVIOURAL_PROJECT_KEYS.get(
            key,
            "not a key this guard knows; failing closed rather than waving it through",
        )
        found.append((f"[project].{key}", why))

    base_extras = base_project.get("optional-dependencies", {})
    head_extras = head_project.get("optional-dependencies", {})
    for extra in sorted(set(base_extras) | set(head_extras)):
        if extra == EXEMPT_EXTRA:
            continue
        if base_extras.get(extra) == head_extras.get(extra):
            continue
        found.append(
            (
                f"[project.optional-dependencies].{extra}",
                "an extra a consumer installs on purpose (only `dev` is exempt)",
            )
        )
    return found


def build_system_differences(base: dict, head: dict) -> list[tuple[str, str]]:
    """`build-backend` counts; `requires` does not. See the module docstring and commit 84278e2."""
    base_bs = base.get("build-system", {})
    head_bs = head.get("build-system", {})
    if base_bs.get("build-backend") == head_bs.get("build-backend"):
        return []
    return [("[build-system].build-backend", "a different backend builds a different artifact")]


def hatch_build_differences(base: dict, head: dict) -> list[tuple[str, str]]:
    """`[tool.hatch.build…]` decides what is inside the wheel. No other `[tool.*]` does."""
    base_build = base.get("tool", {}).get("hatch", {}).get("build")
    head_build = head.get("tool", {}).get("hatch", {}).get("build")
    if base_build == head_build:
        return []
    return [("[tool.hatch.build]", "it decides which modules end up inside the wheel")]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        return die("usage: pyproject_diff.py <base-pyproject> <head-pyproject>")

    base, head = load(argv[0]), load(argv[1])
    if base is None:
        return die(f"could not parse {argv[0]}")
    if head is None:
        return die(f"could not parse {argv[1]}")

    base_version = str(base.get("project", {}).get("version", ""))
    head_version = str(head.get("project", {}).get("version", ""))
    emit("version", base_version, head_version, compare_versions(base_version, head_version))

    for table, why in (
        project_differences(base, head)
        + build_system_differences(base, head)
        + hatch_build_differences(base, head)
    ):
        emit("behavioural", table, why)

    return COMPARED


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
