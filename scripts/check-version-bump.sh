#!/usr/bin/env bash
# A behavioural change to a shipped package bumps that package's version in the same PR.
#
# ADR 0007 §3, and CLAUDE.md §Conventions §Versioning is the specification. Two things about this
# guard are decisions rather than implementation details, and both exist because the sibling
# project got them wrong.
#
# 1. IT DIFFS AGAINST THE MERGE-BASE WITH main, NEVER THE REMOTE TIP.
#
#    `git merge-base HEAD origin/main`. Pandan diffs against the tip, which is its open bug
#    KAN-484: once main moves on, a two-dot diff against the tip reports every file main changed
#    since the branch point as though the branch had changed it, *backwards*. A docs-only branch
#    then looks like it edited someone else's source and downgraded their version, and goes red.
#    The merge-base is the only ref against which "what did this branch do" has an answer, and it
#    is stable under a merge commit: merging main in moves the merge-base forward to match, so the
#    diff stays exactly the branch's own work. A guard that false-positives gets ignored, and a
#    guard that gets ignored protects nothing.
#
# 2. IT CLASSIFIES A pyproject.toml CHANGE BY WHICH TABLE MOVED, NOT BY THE FILENAME.
#
#    That work is `scripts/lib/pyproject_diff.py`, which has the whole argument and the table
#    list. The short version: every Dependabot PR into these three packages edits `pyproject.toml`,
#    and this repository has already merged one — 84278e2, a one-line `[build-system].requires`
#    bump into /mcp — that a filename-level guard would have reddened for nothing.
#
# Scope is the three shipped packages. `backend/` is deployed rather than distributed and has no
# version anyone installs; `frontend/` ships inside it.
#
# Offline, no network and no virtualenv — a handful of `git` calls and one `tomllib` parse per
# package — so it belongs in the pre-push gate next to the other cheap guards.
#
# Escape hatch: none, deliberately. The fix is a one-line version bump, which is cheaper than an
# override would be to design.
set -uo pipefail
cd "$(git rev-parse --show-toplevel)"

# The three distributions. `backend` is deployed, not installed, so it has no consumer to break.
PACKAGES=(kaya-client kaya-cli mcp)

status=0
checked=0

# `origin/main` on any normal clone. The override is for a fork whose upstream is not `origin`;
# it is not a way to soften the check, since any ref you point it at still has to be an ancestor.
main_ref=${KAYA_MAIN_REF:-}
if [ -z "$main_ref" ]; then
  for candidate in origin/main main; do
    if git rev-parse --verify --quiet "$candidate^{commit}" >/dev/null; then
      main_ref=$candidate
      break
    fi
  done
fi

if [ -z "$main_ref" ]; then
  # A clone with no main to compare against has no "same PR" for a bump to be in. Say so and
  # pass: failing here would break `git init` sandboxes and teach --no-verify for no safety.
  printf '– no origin/main or main in this clone; nothing to diff a version bump against\n'
  exit 0
fi

base=$(git merge-base HEAD "$main_ref" 2>/dev/null)
if [ -z "$base" ]; then
  printf '✗ no merge-base between HEAD and %s\n' "$main_ref"
  printf '    Usually a shallow clone. CI needs actions/checkout with fetch-depth: 0;\n'
  printf '    locally, `git fetch --unshallow origin` restores enough history.\n'
  printf '    Failing rather than skipping: a guard that cannot see the base ref has\n'
  printf '    checked nothing, and must not report that as a pass.\n'
  exit 1
fi

# Package-relative paths that cannot change what a consumer of the wheel gets. Everything not
# matched here is behavioural, so the failure direction is "ask a human" rather than "wave it
# through" — a new source directory is caught by default instead of by remembering to list it.
not_behavioural() {
  case "$1" in
    uv.lock | .python-version | .gitignore) return 0 ;;  # the dev and CI environment
    *.md | docs/*) return 0 ;;                            # prose
    LICENSE* | NOTICE*) return 0 ;;
    tests/*) return 0 ;;                                  # not in the wheel
    pyproject.toml) return 0 ;;                           # classified per table, below
    *) return 1 ;;
  esac
}

for pkg in "${PACKAGES[@]}"; do
  [ -d "$pkg" ] || continue

  changed=$(git diff --name-only "$base" HEAD -- "$pkg")
  [ -z "$changed" ] && continue

  # A package that did not exist at the merge-base has no previous version to have bumped.
  if ! git cat-file -e "$base:$pkg/pyproject.toml" 2>/dev/null; then
    printf '– %s is new since the merge-base; no previous version to bump\n' "$pkg"
    continue
  fi
  # ...and one deleted on this branch has no version to bump either.
  if ! git cat-file -e "HEAD:$pkg/pyproject.toml" 2>/dev/null; then
    printf '– %s is gone at HEAD; nothing to version\n' "$pkg"
    continue
  fi

  reasons=()
  while IFS= read -r file; do
    [ -z "$file" ] && continue
    not_behavioural "${file#"$pkg"/}" || reasons+=("$file")
  done <<<"$changed"

  # The tables, always — not only when pyproject.toml is in the diff. When it isn't, the two
  # blobs are identical and this reports `unbumped` with no behavioural tables, which is exactly
  # the answer a source-only change needs.
  base_toml=$(mktemp) && head_toml=$(mktemp)
  git show "$base:$pkg/pyproject.toml" >"$base_toml"
  git show "HEAD:$pkg/pyproject.toml" >"$head_toml"
  verdict=$(python3 scripts/lib/pyproject_diff.py "$base_toml" "$head_toml")
  classified=$?
  rm -f "$base_toml" "$head_toml"

  if [ "$classified" -ne 0 ]; then
    printf '✗ %s: could not classify its pyproject.toml (see above)\n' "$pkg"
    status=1
    continue
  fi

  from=""; to=""; moved=""
  while IFS=$'\t' read -r kind a b c; do
    case "$kind" in
      version) from=$a; to=$b; moved=$c ;;
      behavioural) reasons+=("$pkg/pyproject.toml $a — $b") ;;
    esac
  done <<<"$verdict"

  checked=$((checked + 1))
  if [ ${#reasons[@]} -eq 0 ]; then
    printf '✓ %s: changed, nothing behavioural (version %s)\n' "$pkg" "$to"
    continue
  fi

  if [ "$moved" = "bumped" ] || [ "$moved" = "changed" ]; then
    printf '✓ %s: %s → %s, %d behavioural change(s)\n' "$pkg" "$from" "$to" "${#reasons[@]}"
    continue
  fi

  status=1
  if [ "$moved" = "downgraded" ]; then
    printf '✗ %s: version went BACKWARDS, %s → %s\n' "$pkg" "$from" "$to"
  else
    printf '✗ %s: behavioural change with no version bump (still %s)\n' "$pkg" "$to"
  fi
  for reason in "${reasons[@]}"; do
    printf '    %s\n' "$reason"
  done
  printf '    Bump [project].version in %s/pyproject.toml in THIS PR (ADR 0007 §3).\n' "$pkg"
  printf '    If none of the above is behavioural, the classifier is wrong and belongs in\n'
  printf '    scripts/lib/pyproject_diff.py — not worked around here.\n'
done

if [ "$status" -ne 0 ]; then
  printf '\n  Diffed against %s (merge-base with %s), never the remote tip:\n' \
    "$(git rev-parse --short "$base")" "$main_ref"
  printf '  see this script'"'"'s header, and ADR 0007 §3.\n'
  exit 1
fi

printf '✓ version-bump guard: %d shipped package(s) with changes since %s, all consistent\n' \
  "$checked" "$(git rev-parse --short "$base")"
