#!/usr/bin/env bash
# Verify every internal (relative) markdown link resolves, relative to the file
# containing it. Deterministic, offline, no third-party action. External URLs are
# deliberately NOT checked: a link-rot check that needs the network turns a green
# gate red for reasons unrelated to the change being pushed.
#
# Note the deliberate absence of `pipefail`: a `grep` that finds no links in a file
# exits 1, and under pipefail that reads as a failure. The first version of this
# script had exactly that bug and reported broken links in a tree that had none.
set -u

cd "$(dirname "$0")/.."

broken=0
files=0

while IFS= read -r file; do
  files=$((files + 1))
  dir=$(dirname "$file")

  # Every ](target) link, minus anchors and query strings. Fenced code blocks are stripped first —
  # a code sample containing `](...)`-shaped text (e.g. a Python type hint like `Callable[[], T])`)
  # reads as a broken link otherwise, which cost a real PR a false red build (KAN-1051).
  # `|| true` so a file with no links doesn't abort the loop.
  targets=$(awk '/^```/ { fenced = !fenced; next } !fenced' "$file" \
    | grep -oE '\]\([^)]+\)' 2>/dev/null | sed -E 's/^\]\(//; s/\)$//; s/[#?].*$//' || true)

  while IFS= read -r target; do
    [ -z "$target" ] && continue
    case "$target" in
      http://*|https://*|mailto:*|'//'*) continue ;;
    esac
    if [ ! -e "$dir/$target" ]; then
      printf 'BROKEN  %s -> %s\n' "$file" "$target"
      broken=$((broken + 1))
    fi
  done <<< "$targets"
# `*/node_modules/*` rather than `./node_modules/*`: the SPA's dependencies live in
# frontend/node_modules, and a root-anchored pattern misses them entirely — which means scanning
# thousands of vendored READMEs and reporting their broken links as ours. Same for the uv virtual
# environments under each Python package.
done < <(find . \
  -name '*.md' \
  -not -path '*/node_modules/*' \
  -not -path '*/.venv/*' \
  -not -path '*/dist/*' \
  -not -path './.git/*' \
  -not -path './.claude/worktrees/*' \
  | sort)

if [ "$broken" -gt 0 ]; then
  printf '✗ %d broken internal link(s)\n' "$broken"
  exit 1
fi

printf '✓ internal doc links resolve (%d markdown files checked)\n' "$files"
