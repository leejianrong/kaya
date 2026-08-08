#!/usr/bin/env bash
# Known-vulnerability scan across every ecosystem this repo has. KAN-699.
#
#   * frontend/            npm audit, against the committed package-lock.json
#   * backend/             pip-audit, against `uv export` of the committed uv.lock
#   * kaya-client/         "
#   * kaya-cli/            "
#   * mcp/                 "
#
# WHY THIS IS NOT A GATE. It is not in the pre-push hook and not in `make check`, and that is the
# design decision rather than an omission. `npm audit` exits non-zero on an advisory in a transitive
# DEV dependency you have no power to fix — `eslint-plugin-svelte` → `postcss` → `nanoid` was
# exactly that shape when this card was written — and a third party can publish an advisory at 3am
# and turn every unrelated PR red by morning. A gate that goes red for reasons the author cannot act
# on is the gate people learn to bypass, which is the same reasoning that keeps
# `secret-scan.sh --history` out of the hook (dev-playbook §6). So this runs weekly on a schedule
# and on demand, it reports into ONE issue, and it never blocks a merge.
#
# WHAT HAPPENS WHEN AN UNFIXABLE TRANSITIVE ADVISORY APPEARS — because it will. The weekly issue
# lists it, marked `dev-only` when the package is absent from the runtime dependency set, and stays
# open until it clears upstream. Nothing goes red, there is no allowlist file to curate and then let
# go stale, and no version has to be pinned backwards to buy silence. The complementary half is
# Dependabot (`.github/dependabot.yml`), which raises a PR for every advisory that DOES have a fix;
# what lands in the issue is by definition the residue Dependabot could not PR away.
#
# WHY THE dev-only MARKER IS WORTH THE EXTRA WORK. It is the first question a human asks about an
# advisory and the one that decides whether to act. Both halves compute it the same way: resolve the
# runtime-only dependency set separately, then mark any advisory whose package is absent from it. It
# is not a dismissal — a compromised build-time package is still a supply-chain problem — it is the
# difference between "ship a fix" and "wait for upstream".
#
# NETWORK. Required; both tools query an advisory database. That is the second reason this is not in
# the local gate, which is 22s and offline and stays that way.
#
# EXIT CODES, which .github/workflows/dependency-audit.yml depends on:
#   0  no known advisories anywhere
#   1  advisories found (a finding, NOT a malfunction)
#   2  the audit could not be run (tool missing, export failed, unparseable output)
#
# The workflow treats 1 as "write the issue and finish green" and 2 as "fail the run". Red therefore
# means the check stopped working; the issue means the check found something. Those are different
# facts, and conflating them is how a silently broken scanner passes for a clean tree.
#
# Usage:
#   scripts/dependency-audit.sh          # everything
#   scripts/dependency-audit.sh --npm    # frontend only
#   scripts/dependency-audit.sh --python # the four uv packages only
set -uo pipefail
cd "$(dirname "$0")/.."

want_npm=1
want_python=1
case "${1:-}" in
  --npm)    want_python=0 ;;
  --python) want_npm=0 ;;
  "") ;;
  *) echo "usage: $0 [--npm|--python]" >&2; exit 2 ;;
esac

PY_PACKAGES=(backend kaya-client kaya-cli mcp)

# pip-audit is fetched on demand rather than added to any package's dev extras: it is a repo-level
# tool, and putting it in four `[project.optional-dependencies]` blocks would put it in four wheels'
# metadata for nobody's benefit. The upper bound is deliberate — scripts/lib/audit_report.py parses
# this JSON by hand and a major bump is free to reshape it. Capping the tool does NOT stale the
# data: advisories come from the PyPI/OSV service at query time, not from anything in the wheel.
PIP_AUDIT_SPEC='pip-audit>=2.10,<3'

# The report parser is python3 rather than jq: python3 is already a hard requirement of this repo
# (four uv packages) and is present on every GitHub runner, and jq is neither.
REPORT=scripts/lib/audit_report.py

findings=0   # advisories seen; drives exit 1
broken=0     # things that could not be run; drives exit 2

tmp=$(mktemp -d) || { echo "✗ could not create a temp dir" >&2; exit 2; }
trap 'rm -rf "$tmp"' EXIT

if ! command -v python3 >/dev/null 2>&1; then
  echo "✗ python3 not found, and the report parser needs it" >&2
  exit 2
fi

# Runs the parser and folds its three-way exit into this script's two counters, so each caller
# below stays about its own ecosystem instead of repeating this.
report() {
  local label=$1 errfile=$2; shift 2
  local out rc
  out=$(python3 "$REPORT" "$@"); rc=$?
  if [ "$rc" -gt 1 ]; then
    echo "✗ $label — could not read the audit report"
    [ -s "$errfile" ] && sed 's/^/    /' "$errfile" >&2
    broken=1
    return
  fi
  printf '%s\n' "$out"
  [ "$rc" -eq 1 ] && findings=1
  return 0
}

# ------------------------------------------------------------------------------- npm ------------

audit_npm() {
  if [ ! -f frontend/package-lock.json ]; then
    echo "▸ frontend (npm) — skipped, no package-lock.json"
    return
  fi
  if ! command -v npm >/dev/null 2>&1; then
    echo "✗ frontend (npm) — npm not found on PATH"
    broken=1
    return
  fi

  # `npm audit` exits 1 both for "advisories found" and for several real errors, so its exit code is
  # not load-bearing. The JSON decides: if it parses and carries a `metadata` block the audit ran,
  # and if it does not, something went wrong whatever the exit code claimed.
  ( cd frontend && npm audit --json ) > "$tmp/npm-all.json" 2>"$tmp/npm.err"
  # The runtime-only view, for the dev-only marker.
  ( cd frontend && npm audit --omit=dev --json ) > "$tmp/npm-prod.json" 2>/dev/null

  report "frontend (npm)" "$tmp/npm.err" npm "$tmp/npm-all.json" "$tmp/npm-prod.json"
}

# --------------------------------------------------------------------------- uv / Python --------

audit_python_package() {
  local pkg=$1

  # `--frozen` audits the committed lockfile rather than whatever a re-resolve would produce today,
  # which is the point: this must describe what CI installs and what a developer has, not a
  # hypothetical better resolution. `--no-emit-project` drops the package itself and
  # `--no-emit-local` drops the `../kaya-client` path source; neither has a PyPI advisory to look
  # up.
  #
  # MEASURED, because the obvious claim about `--no-deps` turned out to be wrong. pip-audit 2.10.1
  # was observed to resolve dependencies for an INCOMPLETE requirements file even with `--no-deps`
  # (`requests==2.19.0` alone came back as five packages). It does not matter here, and the reason
  # it does not matter is worth writing down: a `uv export` is already the complete transitive set,
  # so there is nothing left to resolve. Checked against `backend/` — 45 exported lines, 42 audited,
  # and the 42 are a strict SUBSET with nothing invented. `--no-deps` is passed anyway, as the
  # narrower request.
  #
  # The three dropped are `colorama`, `pywin32` and `tzdata`, all carrying `sys_platform == 'win32'`
  # markers that pip-audit evaluates against the interpreter running it. So this audit has a real
  # blind spot: a Windows-only dependency. Accepted rather than worked around — stripping the
  # markers to force them in risks an unresolvable set on Linux, and kaya runs on Linux in CI, in
  # its container and in the homelab (ADR 0010).
  local export_args=(--frozen --no-emit-project --no-emit-local --no-hashes --no-annotate
                     --format requirements.txt)

  if ! ( cd "$pkg" && uv export "${export_args[@]}" --all-extras ) \
        > "$tmp/$pkg-all.txt" 2>"$tmp/$pkg.err"; then
    echo "✗ $pkg (uv) — uv export failed"
    sed 's/^/    /' "$tmp/$pkg.err" >&2
    broken=1
    return
  fi
  # Without `--all-extras`: `[project.dependencies]` only, i.e. what a consumer installs. Offline —
  # it reads the same lockfile — so the second export costs nothing.
  ( cd "$pkg" && uv export "${export_args[@]}" ) > "$tmp/$pkg-runtime.txt" 2>/dev/null

  # pip-audit, like npm audit, exits non-zero for a finding and for a failure alike, so again the
  # JSON rules and only an unreadable report counts as a malfunction.
  uv run --no-project --quiet --with "$PIP_AUDIT_SPEC" \
    pip-audit --no-deps --format json --requirement "$tmp/$pkg-all.txt" \
    > "$tmp/$pkg.json" 2>>"$tmp/$pkg.err"

  report "$pkg (uv)" "$tmp/$pkg.err" pip "$pkg" "$tmp/$pkg.json" "$tmp/$pkg-runtime.txt"
}

# ------------------------------------------------------------------------------ run -------------

if [ "$want_npm" -eq 1 ]; then
  audit_npm
fi

if [ "$want_python" -eq 1 ]; then
  if ! command -v uv >/dev/null 2>&1; then
    echo "✗ the uv packages — uv not found on PATH"
    broken=1
  else
    for pkg in "${PY_PACKAGES[@]}"; do
      [ -d "$pkg" ] || continue
      audit_python_package "$pkg"
    done
  fi
fi

echo ""
if [ "$broken" -eq 1 ]; then
  echo "✗ the dependency audit could not be completed — see the errors above."
  echo "  That is a broken check, not a clean tree. Do not read it as 'no advisories'."
  exit 2
fi
if [ "$findings" -eq 1 ]; then
  echo "✗ known advisories found. This is a report, not a gate: nothing is blocked by it."
  echo "  Anything fixable should already have a Dependabot PR open. What is left is either waiting"
  echo "  on an upstream release or a deliberate accept — say which, in the tracking issue."
  exit 1
fi
echo "✓ no known advisories in any committed lockfile"
exit 0
