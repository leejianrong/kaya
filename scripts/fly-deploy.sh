#!/usr/bin/env bash
# Deploy kaya to Fly.io with the same provenance build-args scripts/image-build.sh computes for a
# local `docker build` (ADR 0007 §2) — a bare `flyctl deploy` leaves the Dockerfile's ARG defaults
# in place and every provenance label reads "unknown".
#
# Requires FLY_API_TOKEN in the environment (flyctl reads it directly; see docs/deploy/fly.md for
# where that token comes from). Builds remotely on Fly's own builder — no local Docker required.
#
# Usage:  scripts/fly-deploy.sh [-- extra flyctl deploy args]
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -z "${FLY_API_TOKEN:-}" ]; then
  echo "✗ FLY_API_TOKEN is not set — see docs/deploy/fly.md" >&2
  exit 1
fi

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
data = tomllib.loads(pathlib.Path("backend/pyproject.toml").read_text())
print(data["project"]["version"])
PY
)

printf '▸ deploying kaya-jian to Fly\n'
printf '    version   %s\n' "$version"
printf '    revision  %s\n' "$revision"
printf '    created   %s\n' "$created"
case "$revision" in
  *-dirty)
    printf '  note: DIRTY tree. Deploying uncommitted changes — the revision label says so.\n' ;;
esac

flyctl deploy \
  --build-arg "VERSION=$version" \
  --build-arg "GIT_REVISION=$revision" \
  --build-arg "BUILD_DATE=$created" \
  "$@"
