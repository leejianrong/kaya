#!/usr/bin/env bash
# Build kaya's image with provenance labels that are TRUE.
#
# This script exists because a `LABEL org.opencontainers.image.revision` is a string, and a string
# is whatever the build was told to put there. `docker build` on its own is told nothing, so the
# Dockerfile's ARG defaults leave every provenance claim reading `unknown` — honest, and useless.
# Everything below is the work of making them useful instead:
#
#   revision  the commit, plus `-dirty` when the working tree it built from had uncommitted
#             changes. That suffix is the whole point. Without it the label names a commit whose
#             contents are NOT what is in the image, and a reader who trusts it will go and read
#             the wrong source when something breaks at 2am.
#   created   the build machine's clock, in RFC 3339 UTC.
#   version   backend/pyproject.toml's version, so the image and the package agree by construction
#             rather than by someone remembering.
#
# Usage:  scripts/image-build.sh [tag]        (default: kaya:dev)
set -euo pipefail
cd "$(dirname "$0")/.."

IMAGE="${1:-${KAYA_IMAGE:-kaya:dev}}"
# Shift it off so anything after it reaches `docker build` untouched (`--no-cache`, `--progress`).
if [ $# -gt 0 ]; then shift; fi

revision=$(git rev-parse HEAD 2>/dev/null || echo unknown)
if [ "$revision" != unknown ] && ! git diff --quiet HEAD -- 2>/dev/null; then
  revision="${revision}-dirty"
fi

# Untracked files count too: a new module that is in the build context but not in the commit makes
# the image differ from the sha just as surely as an edit to a tracked one does.
if [ "$revision" != unknown ] && [ -n "$(git ls-files --others --exclude-standard)" ]; then
  case "$revision" in
    *-dirty) ;;
    *) revision="${revision}-dirty" ;;
  esac
fi

created=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# Read the version out of pyproject.toml with a parser rather than a grep: `version = ` also
# appears in `requires-python` neighbourhoods and in dependency pins, and picking the wrong line
# would produce a label that is wrong in the one way nobody checks.
version=$(python3 - <<'PY'
import pathlib, tomllib
data = tomllib.loads(pathlib.Path("backend/pyproject.toml").read_text())
print(data["project"]["version"])
PY
)

printf '▸ building %s\n' "$IMAGE"
printf '    version   %s\n' "$version"
printf '    revision  %s\n' "$revision"
printf '    created   %s\n' "$created"

docker build \
  --file Dockerfile \
  --tag "$IMAGE" \
  --build-arg "VERSION=$version" \
  --build-arg "GIT_REVISION=$revision" \
  --build-arg "BUILD_DATE=$created" \
  "$@" \
  .

# Read the labels back off the built image rather than echoing what we passed in. A `LABEL` line
# that loses its `${VERSION}` interpolation — a stage that forgot to re-declare the ARG is the
# usual way — produces an image whose labels say `unknown` while this script's own output above
# says otherwise. Asserting against the artifact is the only version of this check worth running.
readback=$(docker image inspect "$IMAGE" \
  --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')
if [ "$readback" != "$revision" ]; then
  printf '✗ the image labels do not match the build: revision reads %q, expected %q\n' \
    "$readback" "$revision"
  exit 1
fi

printf '✓ %s built; labels verified against the artifact\n' "$IMAGE"
case "$revision" in
  *-dirty)
    printf '  note: built from a DIRTY tree. The revision label says so; do not publish this.\n' ;;
esac
