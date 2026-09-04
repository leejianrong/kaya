.DEFAULT_GOAL := help
SHELL := /bin/bash

PY_PACKAGES := backend kaya-client kaya-cli mcp

.PHONY: help
help: ## List every target
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------- works today

.PHONY: hooks
hooks: ## Install the pre-push gate (run once after cloning)
	@scripts/install-hooks.sh

.PHONY: docs-links
docs-links: ## Check that every internal doc link resolves
	@scripts/check-docs-links.sh

.PHONY: secret-scan
secret-scan: ## gitleaks over every tracked file + the .env / .mcp.json tracking assertions
	@scripts/secret-scan.sh

.PHONY: secret-scan-history
secret-scan-history: ## Same scanner over every commit. An audit, deliberately NOT part of `check`
	@scripts/secret-scan.sh --history

.PHONY: image-pins
image-pins: ## Fail if any external container image is referenced by tag instead of digest
	@scripts/check-image-pins.sh

# ADR 0007 §3. Diffed against the merge-base with main and never the remote tip, and classified by
# which pyproject.toml table moved rather than by which file did. KAN-544.
.PHONY: version-bump
version-bump: ## Fail if a shipped package changed behaviourally without a version bump
	@scripts/check-version-bump.sh

# Deliberately NOT a dependency of `check` and not in the pre-push hook, for the same reason
# `secret-scan-history` is not: it needs the network, and it goes red on a third party's timetable
# rather than on anything the pusher did. A scheduled workflow runs it weekly and reports into one
# issue. scripts/dependency-audit.sh explains the whole argument. KAN-699.
.PHONY: audit
audit: ## npm audit + pip-audit over every committed lockfile. An audit, deliberately NOT in `check`
	@scripts/dependency-audit.sh

.PHONY: install
install: ## Sync every package's dependencies (uv for Python, npm for the SPA)
	@for pkg in $(PY_PACKAGES); do echo "▸ $$pkg"; (cd $$pkg && uv sync --all-extras) || exit 1; done
	@echo "▸ frontend"; cd frontend && npm ci

.PHONY: db
db: ## Start Postgres 17 in the background and wait for it to be healthy
	@docker compose up -d --wait db
	@echo "✓ postgres ready on port $${KAYA_DB_PORT:-5432}"

.PHONY: db-down
db-down: ## Stop Postgres (keeps the volume)
	@docker compose down

.PHONY: image
image: ## Build the container image with TRUE provenance labels
	@scripts/image-build.sh

.PHONY: mcp-image
mcp-image: ## Build the MCP server image (TRUE provenance labels), then prove it serves stdio
	@scripts/mcp-image-build.sh

.PHONY: up
up: image ## Whole stack on :8000 from the image the manifests deploy (db, migrate, app)
	@docker compose up -d --wait db app
	@echo "✓ kaya on http://localhost:$${KAYA_APP_PORT:-8000}  ·  stop it with 'make down'"

.PHONY: down
down: ## Stop the whole stack (keeps the volume)
	@docker compose down

.PHONY: k3d
k3d: ## Apply deploy/k8s to a local k3d cluster and prove the pod serves
	@scripts/k3d-up.sh

.PHONY: k3d-down
k3d-down: ## Delete the local k3d cluster
	@scripts/k3d-up.sh --down

.PHONY: fly-deploy
fly-deploy: ## Deploy kaya to Fly.io (needs FLY_API_TOKEN — see docs/deploy/fly.md)
	@scripts/fly-deploy.sh

.PHONY: db-reset
db-reset: ## Stop Postgres and DELETE its volume
	@docker compose down -v

.PHONY: dev-backend
dev-backend: ## Backend only, with reload, on :8000
	@cd backend && uv run uvicorn app.main:app --reload --port 8000

.PHONY: dev-frontend
dev-frontend: ## SPA only, on :5173, proxying /api to :8000
	@cd frontend && npm run dev

.PHONY: dev
dev: ## Native hot-reload loop: db, then backend and SPA together
	@$(MAKE) --no-print-directory db
	@echo "▸ backend :8000  ·  spa :5173  ·  ctrl-c stops both"
	@trap 'kill 0' EXIT INT TERM; \
	  ( cd backend && uv run uvicorn app.main:app --reload --port 8000 ) & \
	  ( cd frontend && npm run dev ) & \
	  wait

.PHONY: lint
lint: ## ruff across the Python packages + eslint and svelte-check
	@for pkg in $(PY_PACKAGES); do echo "▸ $$pkg"; (cd $$pkg && uv run ruff check .) || exit 1; done
	@echo "▸ frontend"; cd frontend && npm run lint

.PHONY: test
test: ## Fast, no-infra test layer (what pre-push runs)
	@echo "▸ backend"; cd backend && uv run pytest tests/unit -q
	@for pkg in kaya-client kaya-cli mcp; do echo "▸ $$pkg"; (cd $$pkg && uv run pytest -q) || exit 1; done
	@echo "▸ frontend"; cd frontend && npm test

.PHONY: test-integration
test-integration: ## Real Postgres via testcontainers (needs Docker)
	@cd backend && uv run pytest tests/integration -q

# Extra flags for the measurement below, e.g.
#   make measure-auth MEASURE_ARGS="--split-only --last-contact 2026-08-08T17:47Z"
# `--split-only` is KAN-666's connect-vs-read experiment. It needs no Docker and no Postgres,
# because it makes one call and times it at the socket.
MEASURE_ARGS ?=

.PHONY: measure-auth
measure-auth: ## Re-measure introspection latency (needs Docker and a real PAT; KAN-539, KAN-666)
	@cd backend && uv run scripts/measure_introspection_latency.py $(MEASURE_ARGS)

.PHONY: build
build: ## Build the SPA into frontend/dist
	@cd frontend && npm run build

.PHONY: check
check: docs-links secret-scan image-pins version-bump lint test ## Everything the pre-push hook runs
	@echo "✓ all checks that apply to the current tree passed"

.PHONY: test-e2e
test-e2e: ## Playwright against a real, ephemeral stack + a fake pandan (needs Docker; KAN-1070)
	@scripts/test-e2e.sh
