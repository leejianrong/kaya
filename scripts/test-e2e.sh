#!/usr/bin/env bash
# `make test-e2e` (KAN-1070): boot an ephemeral kaya stack — Postgres, the migration, the app, and a
# fake pandan — and run the Playwright suite in frontend/e2e/ against it. SLICES.md §V3's
# "End-to-end" bullets are the exact scope; nothing here tries to cover search, wikilinks, MCP, the
# CLI, the graph view or embeds — those already have their own test layers.
#
# Ephemeral and isolated by construction, per CLAUDE.md's rule on parallel worktrees sharing a
# filesystem: its own COMPOSE_PROJECT_NAME and its own published ports, so this never touches a
# developer's persistent `make up` volume — and the whole stack comes down with `-v` unconditionally
# on the way out, pass or fail, via the trap below. Every note the suite creates also carries a
# run-scoped prefix in its title (`frontend/e2e/fixtures.ts`'s `prefixedTitle`), and
# `frontend/e2e/global-teardown.ts` deletes exactly those notes through the API before the compose
# teardown runs — belt and suspenders with tearing down the whole stack, per PLAN §Testing approach
# point 4 ("the e2e stack booting itself, with self-cleaning prefixed data").
#
# Overridable: KAYA_E2E_PROJECT (compose project name), KAYA_E2E_DB_PORT, KAYA_E2E_APP_PORT.
set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT="${KAYA_E2E_PROJECT:-kaya-e2e}"
DB_PORT="${KAYA_E2E_DB_PORT:-5544}"
APP_PORT="${KAYA_E2E_APP_PORT:-8099}"

# Never a real pandan credential — this is a bearer a stdlib HTTP server compares a header against,
# not a secret. Fixed per run (not per invocation of this script) is not required; a fresh value
# each run is one line cheaper than arguing it needs to be stable, and it rules out a stale value
# leftover from a previous, differently-configured run ever accidentally matching.
export KAYA_E2E_FAKE_PANDAN_TOKEN="kaya-e2e-fake-pat-$$-${RANDOM}"

COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.e2e.yml -p "$PROJECT")

need() {
  command -v "$1" >/dev/null 2>&1 || {
    printf '✗ %s is not on PATH. %s\n' "$1" "$2"
    exit 1
  }
}

need docker "Install Docker to run make test-e2e."
need npx "Install Node (frontend/package.json's engines) to run make test-e2e."

# Unconditional, pass or fail — see the header. `-v` because a stray volume from a killed run is
# exactly the kind of leftover CLAUDE.md's worktree rule exists to prevent, and this project name
# holds nothing worth keeping between runs.
cleanup() {
  status=$?
  echo "▸ tearing down the e2e stack ($PROJECT)"
  "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  exit "$status"
}
trap cleanup EXIT INT TERM

echo "▸ building and starting the e2e stack on :$APP_PORT (db :$DB_PORT, project $PROJECT)"
KAYA_DB_PORT="$DB_PORT" KAYA_APP_PORT="$APP_PORT" \
  "${COMPOSE[@]}" up -d --build --wait db app fake-pandan

echo "▸ running the Playwright suite"
(
  cd frontend
  KAYA_E2E_BASE_URL="http://localhost:${APP_PORT}" \
    KAYA_E2E_FAKE_PANDAN_TOKEN="$KAYA_E2E_FAKE_PANDAN_TOKEN" \
    npx playwright test
)
