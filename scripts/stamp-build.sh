#!/usr/bin/env bash
# Stamp a commit sha into kaya-client so the built artifact can say what it is (ADR 0007 §1).
#
#   scripts/stamp-build.sh <sha> [path-to-_build_stamp.py]
#
# Run this immediately before packaging and never commit the result. The full contract — where the
# file goes, what KAN-544's release gate asserts against it, and the two PyInstaller traps — is in
# kaya-client/src/kaya_client/_build_stamp.py's module docstring, next to the constant so the two
# cannot drift.
#
# The argument is validated here against the same rule provenance.py applies on the way out, so an
# unexpanded ${GITHUB_SHA}, a sentinel word, or an empty string fails the *build* loudly instead of
# reaching a user as a quietly wrong --version. The two ends agreeing is what makes "an artifact
# that can't identify itself doesn't ship" structural rather than aspirational.
set -euo pipefail

sha=${1:-}
out=${2:-"$(dirname "$0")/../kaya-client/src/kaya_client/_build_stamp.py"}

if [ -z "$sha" ]; then
  printf 'usage: %s <sha> [out]\n' "$0" >&2
  exit 2
fi

# Lowercase hex, 7–40 characters: what git writes and what $GITHUB_SHA carries.
if ! printf '%s' "$sha" | grep -qE '^[0-9a-f]{7,40}$'; then
  printf 'stamp-build: %q is not a commit sha; refusing to stamp it\n' "$sha" >&2
  exit 1
fi

# Git's null sha is valid hex and would otherwise sail through as provenance.
if printf '%s' "$sha" | grep -qE '^0+$'; then
  printf 'stamp-build: refusing to stamp the null sha\n' >&2
  exit 1
fi

if [ ! -f "$out" ]; then
  printf 'stamp-build: no stamp module at %s\n' "$out" >&2
  exit 1
fi

# Rewrite the one assignment, leaving the docstring that explains it in place. `COMMIT` appears
# exactly once as an assignment; the guard below fails the build if that ever stops being true
# rather than producing a file with two of them.
matches=$(grep -cE '^COMMIT = ' "$out")
if [ "$matches" != "1" ]; then
  printf 'stamp-build: expected exactly one COMMIT assignment in %s, found %s\n' "$out" "$matches" >&2
  exit 1
fi

tmp=$(mktemp)
sed -E "s|^COMMIT = .*$|COMMIT = \"${sha}\"|" "$out" > "$tmp"
mv "$tmp" "$out"

printf '✓ stamped %s with %s\n' "$out" "${sha:0:7}"
