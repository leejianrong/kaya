#!/usr/bin/env bash
# Project-specific credential scan. Deliberately narrow and offline: it catches the
# leak this repo is actually at risk of (a pandan PAT pasted into a doc or a test
# fixture) plus the universal cases, with no network and no third-party action.
#
# This is NOT a substitute for a real scanner. Adding gitleaks or trufflehog to CI
# is a follow-up once there is application code to scan — tracked on board 18.
set -uo pipefail
cd "$(dirname "$0")/.."

status=0

# 1. Live-token shapes. The PAT prefixes are this suite's own (pandan ADR 0018:
#    pandan_pat_ current, kanban_pat_ still accepted, so both are live secrets).
patterns=(
  '(pandan_pat_|kanban_pat_|kaya_pat_)[A-Za-z0-9_-]{20,}'
  '(ghp_|gho_|ghu_|ghs_|github_pat_)[A-Za-z0-9_]{20,}'
  'BEGIN (RSA |EC |OPENSSH |PGP )?PRIVATE KEY'
  'AKIA[0-9A-Z]{16}'
)
for p in "${patterns[@]}"; do
  if hits=$(git grep -nIE "$p" -- . 2>/dev/null); then
    echo "✗ credential-shaped string found:"
    # Print the location only. Never echo the match itself — that would put the
    # secret in a CI log, which is the problem, not the fix.
    echo "$hits" | cut -d: -f1,2 | sed 's/^/    /'
    status=1
  fi
done

# 2. Secret-bearing files that must never be tracked, whatever .gitignore says
#    (a `git add -f` beats an ignore rule).
for f in .env .mcp.json; do
  if git ls-files --error-unmatch "$f" >/dev/null 2>&1; then
    echo "✗ $f is TRACKED by git and must not be"
    status=1
  fi
done

# 3. .gitignore must actually cover them, so the above can't start passing by accident.
for f in .env .mcp.json; do
  if ! git check-ignore -q "$f" 2>/dev/null; then
    echo "✗ $f is not covered by .gitignore"
    status=1
  fi
done

[ "$status" -eq 0 ] && echo "✓ no credential-shaped strings; .env and .mcp.json untracked and ignored"
exit "$status"
