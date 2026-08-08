.DEFAULT_GOAL := help
SHELL := /bin/bash

# Targets are grouped by whether they work TODAY or wait on a slice. Nothing here pretends to run
# code that doesn't exist yet — see CLAUDE.md §Build status.

PY_PACKAGES := backend kaya-client kaya-cli mcp

.PHONY: help
help: ## List every target
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "  Targets marked (V3+) need application code that has not landed yet."

# ---------------------------------------------------------------- works today

.PHONY: hooks
hooks: ## Install the pre-push gate (run once after cloning)
	@scripts/install-hooks.sh

.PHONY: docs-links
docs-links: ## Check that every internal doc link resolves
	@scripts/check-docs-links.sh

.PHONY: secret-scan
secret-scan: ## Grep the working tree for credential-shaped strings
	@scripts/secret-scan.sh

.PHONY: image-pins
image-pins: ## Fail if any external container image is referenced by tag instead of digest
	@scripts/check-image-pins.sh

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

.PHONY: measure-auth
measure-auth: ## Re-measure introspection latency (needs Docker and a real PAT; KAN-539)
	@cd backend && uv run scripts/measure_introspection_latency.py

.PHONY: build
build: ## Build the SPA into frontend/dist
	@cd frontend && npm run build

.PHONY: check
check: docs-links secret-scan image-pins lint test ## Everything the pre-push hook runs
	@echo "✓ all checks that apply to the current tree passed"

# ------------------------------------------------------------------- (V3+)

.PHONY: test-e2e
test-e2e: ## (V3+) Boots the stack itself
	@scripts/not-yet.sh test-e2e "KAN-552 (SPA shell)"
