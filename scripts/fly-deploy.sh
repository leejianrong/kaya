#!/usr/bin/env bash
# Deploy kaya to Fly.io with the same provenance build-args scripts/image-build.sh computes for a
# local `docker build` (ADR 0007 §2) — a bare `flyctl deploy` leaves the Dockerfile's ARG defaults
# in place and every provenance label reads "unknown".
#
# Needs either an authenticated `flyctl auth login` session or FLY_API_TOKEN in the environment
# (flyctl reads the latter directly; see docs/deploy/fly.md for where that token comes from — this
# is the only path CI has, since it has no interactive session). Builds remotely on Fly's own
# builder — no local Docker required.
#
# Usage:  scripts/fly-deploy.sh [-- extra flyctl deploy args]
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -z "${FLY_API_TOKEN:-}" ] && ! flyctl auth whoami >/dev/null 2>&1; then
  echo "✗ no flyctl auth session and FLY_API_TOKEN is not set — see docs/deploy/fly.md" >&2
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

# tomllib needs 3.11+; the system `python3` on some hosts (this one included) is older, so try a
# newer interpreter first rather than assuming `python3` is new enough — the same assumption
# scripts/image-build.sh makes and inherits this host's problem with it.
py=python3
for candidate in python3.13 python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    py="$candidate"
    break
  fi
done

version=$("$py" - <<'PY'
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
