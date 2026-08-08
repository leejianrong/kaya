#!/usr/bin/env bash
# Credential scan. Three checks, and only the first is a scanner's job (KAN-580):
#
#   1. gitleaks over every tracked file, with this repo's own PAT rule added.
#   2. .env and .mcp.json are not TRACKED by git.
#   3. .gitignore actually covers them.
#
# 2 and 3 survived the swap from the hand-rolled grep on purpose. gitleaks and trufflehog
# scan content; neither has an opinion about whether a secret-bearing file has become
# tracked, and `git add -f` beats an ignore rule. Dropping them while "upgrading" the scan
# would be a net loss dressed as an improvement.
#
# WHY GITLEAKS, and why only one. See the PR for KAN-580; the short version is that
# trufflehog's distinguishing feature is live credential verification, which means network
# calls, and this scan runs in the pre-push hook where a slow gate gets bypassed and a
# bypassed gate protects nothing (dev-playbook §6). gitleaks also has `--redact`, which is
# what makes the property below cheap to keep.
#
# NEVER PRINT THE MATCH. A finding names a file and a line, never the secret. Echoing the
# match would copy the credential into a public Actions log, which is the problem, not the
# fix. That is enforced twice over: `--redact` blanks the Secret and Match fields inside
# gitleaks, and the report template below has no field that could carry them even if it
# did not.
#
# Usage:
#   scripts/secret-scan.sh              # tracked working tree (the gate)
#   scripts/secret-scan.sh --history    # every blob in every commit (on-demand audit)
set -uo pipefail
cd "$(dirname "$0")/.."
root=$(pwd)

mode=tree
case "${1:-}" in
  --history) mode=history ;;
  "") ;;
  *) echo "usage: $0 [--history]" >&2; exit 2 ;;
esac

status=0

# --- 1. gitleaks -------------------------------------------------------------------------

gitleaks=$(scripts/ensure-gitleaks.sh) || exit 1

tmp=$(mktemp -d) || { echo "✗ could not create a temp dir" >&2; exit 1; }
trap 'rm -rf "$tmp"' EXIT

# The report template. Location and rule id, nothing else — see NEVER PRINT THE MATCH above.
# The rule id is safe and worth having: "aws-access-token" tells you what to rotate, and
# tells you at a glance when a finding is a false positive worth an allowlist entry.
cat > "$tmp/finding.tmpl" <<'TMPL'
{{range .}}    {{.File}}:{{.StartLine}}  [{{.RuleID}}]
{{end}}
TMPL

scan() {
  # Exit code is what we act on; the report goes to stdout and gitleaks' own progress
  # lines go to stderr, where they are useful evidence that the scan actually ran.
  "$gitleaks" "$@" \
    --config "$root/.gitleaks.toml" \
    --no-banner \
    --redact \
    --report-format template \
    --report-template "$tmp/finding.tmpl" \
    --report-path -
}

if [ "$mode" = history ]; then
  # Every blob in every commit. NOT part of the gate — see the tree branch below for why.
  echo "▸ scanning full history (this is the audit, not the gate)"
  if ! out=$(scan git "$root" 2>&1 >"$tmp/report"); then
    echo "✗ credential found in git history:"
    cat "$tmp/report"
    echo "  A finding here cannot be fixed by a commit. Rotate the credential first — it is"
    echo "  published and must be assumed compromised — then decide about rewriting history."
    status=1
  fi
  printf '%s\n' "$out" >&2
else
  # WHY THE TRACKED WORKING TREE, and not the whole directory or the whole history.
  #
  # Not the whole directory: `gitleaks dir .` reads ignored files too — verified, it is not
  # a .gitignore-aware walker. That means it reads your local `.env`, which on a working
  # machine holds a real pandan PAT and is *supposed* to. A gate that fails on the correct
  # state of a developer's machine is a gate that gets `--no-verify`d on day one. It would
  # also walk .venv, node_modules and .claude/worktrees/ — the last of which is an entire
  # second checkout, with its own .env.
  #
  # Not the history: a finding in a past commit cannot be cleared by making a commit, only
  # by rewriting history. Wiring that into the pre-push hook and into CI means one old blob
  # blocks every unrelated PR until someone rewrites main, so the realistic outcome is that
  # the gate gets bypassed or deleted. History is audited on demand instead —
  # `make secret-scan-history`, which was run at KAN-580 time and was clean across all 25
  # commits this repo had then.
  #
  # What is left is exactly the set a `git push` can publish, with working-tree content, so
  # an uncommitted paste is caught before it is ever committed.
  mkdir -p "$tmp/tree" || { echo "✗ could not create a staging dir" >&2; exit 1; }

  # NUL-delimited so a path with a space or a newline in it still round-trips. The filter
  # drops files that are tracked but deleted in the working tree: there is nothing to read,
  # and the deletion is what is being pushed.
  present() {
    git ls-files -z | while IFS= read -r -d '' f; do
      [ -f "$f" ] && printf '%s\0' "$f"
    done
  }

  if cp --help 2>/dev/null | grep -q -- '--parents'; then
    # GNU coreutils: one `cp` for the whole set instead of two forks per file. Measured at
    # 0.05s against 0.84s for the loop below, on 134 files — worth the branch, because this
    # runs on every push.
    present | xargs -0 -r cp -p --parents -t "$tmp/tree" \
      || { echo "✗ could not stage the tracked tree for scanning" >&2; exit 1; }
  else
    # BSD cp (macOS) has no --parents, and no --help either, which is what the probe above
    # detects. Correctness first: slower, same result.
    while IFS= read -r -d '' f; do
      mkdir -p "$tmp/tree/$(dirname "$f")" && cp -p -- "$f" "$tmp/tree/$f" \
        || { echo "✗ could not stage $f for scanning" >&2; exit 1; }
    done < <(present)
  fi
  files=$(find "$tmp/tree" -type f | wc -l | tr -d ' ')

  # Scanned from inside the staging dir so findings come out as repo-relative paths rather
  # than as paths into a temp directory nobody can act on.
  if ! out=$(cd "$tmp/tree" && scan dir . 2>&1 >"$tmp/report"); then
    echo "✗ credential-shaped string found in a tracked file:"
    cat "$tmp/report"
    echo "  Rotate it, then remove it. If it is a false positive, add an allowlist entry to"
    echo "  .gitleaks.toml with a one-line reason — not a blanket exclusion."
    status=1
  fi
  printf '%s\n' "$out" >&2
  scanned="$files tracked file(s)"
fi

# --- 2. files that must never be tracked, whatever .gitignore says -----------------------
# `git add -f` beats an ignore rule, and no content scanner will tell you it happened.
for f in .env .mcp.json; do
  if git ls-files --error-unmatch "$f" >/dev/null 2>&1; then
    echo "✗ $f is TRACKED by git and must not be"
    status=1
  fi
done

# --- 3. .gitignore must actually cover them ----------------------------------------------
# So that check 2 cannot start passing by accident, on a tree where the file simply has not
# been created yet.
for f in .env .mcp.json; do
  if ! git check-ignore -q "$f" 2>/dev/null; then
    echo "✗ $f is not covered by .gitignore"
    status=1
  fi
done

if [ "$status" -eq 0 ]; then
  if [ "$mode" = history ]; then
    echo "✓ gitleaks found nothing in git history; .env and .mcp.json untracked and ignored"
  else
    echo "✓ gitleaks clean over $scanned; .env and .mcp.json untracked and ignored"
  fi
fi
exit "$status"
