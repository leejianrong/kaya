#!/usr/bin/env bash
# An artifact that can't say what it is does not ship. ADR 0007 §2, KAN-544.
#
#   scripts/check-release-artifact.sh <artifact> <sha>
#
# Executes the thing that was just built, reads `--version`, and fails unless it reports a real
# commit sha matching the commit being released. `--version` printing the right string on a
# developer's machine proves nothing about what the pipeline produced, which is why this runs the
# binary rather than reading the source it was built from.
#
# THREE THINGS HERE ARE DELIBERATE.
#
# 1. THE WHOLE LINE IS COMPARED, NOT JUST THE SHA. A sha-only gate passes an artifact carrying the
#    right commit beside the wrong version, and that is the ONLY way this mechanism can fail
#    quietly — `kaya_cli.__version__` falls back to `0.0.0` when `importlib.metadata` cannot find
#    the distribution, which is loud in no way at all. Every other failure prints the words
#    "source checkout, not a released build", which any comparison catches.
#
# 2. THE EXPECTED VERSION IS READ FROM pyproject.toml, NOT FROM THE ARTIFACT. Asking the artifact
#    what version it thinks it is and then checking it against itself is not a check. The
#    repository is the authority; the binary is the thing on trial.
#
# 3. THE EXPECTED SHA IS VALIDATED BEFORE IT IS USED. `${GITHUB_SHA:0:7}` of an unset variable is
#    the empty string, and a gate comparing against `kaya 0.2.0 ()` would pass an artifact nobody
#    could identify. Same rule as scripts/stamp-build.sh and `provenance.build_sha()` apply at the
#    other two ends, so all three agree by construction.
set -uo pipefail
cd "$(git rev-parse --show-toplevel)"

artifact=${1:-}
sha=${2:-}

if [ -z "$artifact" ] || [ -z "$sha" ]; then
  printf 'usage: %s <artifact> <sha>\n' "$0" >&2
  exit 2
fi

if [ ! -x "$artifact" ]; then
  printf '✗ %s is not an executable file — there is nothing to ask\n' "$artifact" >&2
  exit 1
fi

# See note 3 above. `0+` is git's null sha: valid hex, and provenance about nothing.
if ! printf '%s' "$sha" | grep -qE '^[0-9a-f]{7,40}$' || printf '%s' "$sha" | grep -qE '^0+$'; then
  printf '✗ %q is not a commit sha; refusing to gate against it\n' "$sha" >&2
  exit 1
fi

version=$(python3 -c '
import sys, tomllib
with open("kaya-cli/pyproject.toml", "rb") as f:
    print(tomllib.load(f)["project"]["version"])
') || {
  printf '✗ could not read [project].version from kaya-cli/pyproject.toml\n' >&2
  exit 1
}

want="kaya ${version} (${sha:0:7})"

got=$("$artifact" --version 2>/dev/null)
code=$?

if [ "$code" -ne 0 ]; then
  printf '✗ %s --version exited %d; a release artifact answers this question successfully\n' \
    "$artifact" "$code" >&2
  exit 1
fi

if [ "$got" != "$want" ]; then
  printf '✗ the built artifact cannot identify itself.\n' >&2
  printf '      expected: %s\n' "$want" >&2
  printf '      got:      %s\n' "$got" >&2
  case "$got" in
    *"source checkout, not a released build"*)
      printf '    It was never stamped. `scripts/stamp-build.sh <sha>` runs AFTER the tests and\n' >&2
      printf '    BEFORE the build; if the build ran first, it packaged an empty COMMIT.\n' >&2
      ;;
    "kaya 0.0.0 "*)
      printf '    The sha is there but the version fell back to 0.0.0, so `importlib.metadata`\n' >&2
      printf '    did not find the distribution. This is the silent failure --copy-metadata\n' >&2
      printf '    insures against, and the reason this gate compares the whole line.\n' >&2
      ;;
    *)
      printf '    The version or the sha disagrees with the commit being released.\n' >&2
      ;;
  esac
  printf '    ADR 0007 §2: an artifact that can not say what it is does not ship.\n' >&2
  exit 1
fi

printf '✓ %s identifies itself as %s\n' "$artifact" "$got"
