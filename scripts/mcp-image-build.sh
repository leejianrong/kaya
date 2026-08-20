#!/usr/bin/env bash
# Build kaya's MCP server image with provenance labels that are TRUE, then prove it runs.
#
# `mcp/Dockerfile`'s twin of `scripts/image-build.sh` — same argument, same technique, a different
# package's version and a different proof at the end. See that script's header for the full case
# against `docker build` on its own leaving every label reading `unknown`; this one states only
# what differs.
#
#   version   mcp/pyproject.toml's version, not backend's — a different package, a different
#             number, read with tomllib rather than grepped for the reason image-build.sh gives.
#   revision  the commit, `-dirty`-suffixed exactly as image-build.sh computes it.
#   created   the build clock, RFC 3339 UTC.
#
# And where image-build.sh's only proof is reading its own labels back off the artifact, this one
# goes one step further: mcp/scripts/verify_stdio_image.py actually starts the built image as a
# real MCP host would (`docker run -i --rm <image>`, no shell) and drives `initialize` +
# `tools/list` over its stdin/stdout, then tears it down. A `docker build` exiting 0 proves the
# layers assembled; it says nothing about whether `ENTRYPOINT ["kaya-mcp"]` actually answers.
#
# Usage:  scripts/mcp-image-build.sh [tag]        (default: kaya-mcp:dev)
set -euo pipefail
cd "$(dirname "$0")/.."

IMAGE="${1:-${KAYA_MCP_IMAGE:-kaya-mcp:dev}}"
if [ $# -gt 0 ]; then shift; fi

revision=$(git rev-parse HEAD 2>/dev/null || echo unknown)
if [ "$revision" != unknown ] && ! git diff --quiet HEAD -- 2>/dev/null; then
  revision="${revision}-dirty"
fi

if [ "$revision" != unknown ] && [ -n "$(git ls-files --others --exclude-standard)" ]; then
  case "$revision" in
    *-dirty) ;;
    *) revision="${revision}-dirty" ;;
  esac
fi

created=$(date -u +%Y-%m-%dT%H:%M:%SZ)

version=$(python3 - <<'PY'
import pathlib, tomllib
data = tomllib.loads(pathlib.Path("mcp/pyproject.toml").read_text())
print(data["project"]["version"])
PY
)

printf '▸ building %s\n' "$IMAGE"
printf '    version   %s\n' "$version"
printf '    revision  %s\n' "$revision"
printf '    created   %s\n' "$created"

docker build \
  --file mcp/Dockerfile \
  --tag "$IMAGE" \
  --build-arg "VERSION=$version" \
  --build-arg "GIT_REVISION=$revision" \
  --build-arg "BUILD_DATE=$created" \
  "$@" \
  .

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

printf '▸ proving it actually serves the six tools over stdio (initialize + tools/list)\n'
( cd mcp && uv run python3 scripts/verify_stdio_image.py "$IMAGE" )
