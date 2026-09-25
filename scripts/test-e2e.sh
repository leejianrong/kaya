#!/usr/bin/env bash
# `make test-e2e` (KAN-1070): boot an ephemeral kaya stack — Postgres, the migration, and the app —
# and run the Playwright suite in frontend/e2e/ against it. SLICES.md §V3's "End-to-end" bullets are
# the exact scope; nothing here tries to cover search, wikilinks, MCP, the CLI, the graph view or
# embeds — those already have their own test layers.
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
  "${COMPOSE[@]}" up -d --build --wait db app

# `make test-e2e` used to hand Playwright a bearer a `fake-pandan` stand-in accepted unconditionally
# (ADR 0002's identity path forwarded it there). ADR 0012's cutover (KAN-1740) deleted that call —
# kaya only accepts a `kaya_pat_…` it minted and hashed itself — so this seeds a *real* one straight
# into this stack's own database, through the already-running `app` container's own installed code
# (same `KAYA_AUTH_SECRET`, same models, no separate Python environment or dependency set for this
# script to drift from the app's). `python -` reads the program from stdin rather than needing a file
# copied into the runtime image (`Dockerfile`'s runtime stage carries `app`, not `scripts/` — this is
# test-only tooling and stays that way).
echo "▸ seeding a real kaya_pat_… for the suite"
KAYA_E2E_TOKEN="$(
  "${COMPOSE[@]}" exec -T app python - <<'PYEOF'
import uuid

from app.db import get_sessionmaker
from app.config import get_settings
from app.identity.models import KayaAccount
from app.identity.pat import PersonalAccessToken, generate_token

ACCOUNT_ID = uuid.UUID("e2e0e2e0-e2e0-4e2e-8e2e-e2e0e2e0e2e0")
EMAIL = "e2e@kaya.test"

with get_sessionmaker()() as session:
    account = session.get(KayaAccount, ACCOUNT_ID)
    if account is None:
        account = KayaAccount(
            id=ACCOUNT_ID,
            email=EMAIL,
            hashed_password="not-a-real-hash",
            is_active=True,
            is_superuser=False,
            is_verified=False,
        )
        session.add(account)
        session.commit()

    raw, prefix, token_hash = generate_token(get_settings().kaya_auth_secret)
    session.add(
        PersonalAccessToken(
            user_id=account.id,
            name="e2e suite",
            token_hash=token_hash,
            token_prefix=prefix,
            scope="write",
        )
    )
    session.commit()

print(raw)
PYEOF
)"

if [[ "$KAYA_E2E_TOKEN" != kaya_pat_* ]]; then
  echo "✗ seeding the e2e account did not produce a kaya_pat_… token (got: $KAYA_E2E_TOKEN)"
  exit 1
fi

echo "▸ running the Playwright suite"
(
  cd frontend
  # Idempotent — a no-op in the common case (browser already downloaded) and a one-time ~10-30s
  # fetch on a fresh clone. Without this, a first `make test-e2e` on a machine that has never run
  # Playwright before fails with "browser not found" instead of just working, which is exactly the
  # first-run experience this target exists to give. CI installs the same way, as its own step
  # (`--with-deps` there, for the OS package layer `ubuntu-latest` needs and a sandboxed dev
  # environment already has) — see .github/workflows/ci.yml.
  npx playwright install chromium
  KAYA_E2E_BASE_URL="http://localhost:${APP_PORT}" \
    KAYA_E2E_TOKEN="$KAYA_E2E_TOKEN" \
    npx playwright test
)
