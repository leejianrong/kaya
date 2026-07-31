.DEFAULT_GOAL := help
SHELL := /bin/bash

# Targets are grouped by whether they work TODAY or wait on a slice. Nothing here
# pretends to run code that doesn't exist yet — see CLAUDE.md §Build status.

.PHONY: help
help: ## List every target
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "  Targets marked (V1+) need application code that has not landed yet."

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

.PHONY: check
check: docs-links secret-scan ## Everything the pre-push hook runs today
	@echo "✓ all checks that apply to the current tree passed"

# ------------------------------------------------------------------- (V1+)

.PHONY: up
up: ## (V1+) Whole stack: db + app image serving the SPA
	@scripts/not-yet.sh up "KAN-531 (repo scaffold) + KAN-538 (container)"

.PHONY: dev
dev: ## (V1+) Native hot-reload loop
	@scripts/not-yet.sh dev "KAN-531 (repo scaffold)"

.PHONY: test
test: ## (V1+) Fast, no-infra test layer
	@scripts/not-yet.sh test "KAN-531 (repo scaffold)"

.PHONY: test-integration
test-integration: ## (V1+) Real Postgres via testcontainers
	@scripts/not-yet.sh test-integration "KAN-531 (repo scaffold)"

.PHONY: test-e2e
test-e2e: ## (V3+) Boots the stack itself
	@scripts/not-yet.sh test-e2e "KAN-552 (SPA shell)"

.PHONY: lint
lint: ## (V1+) ruff + eslint + type-check
	@scripts/not-yet.sh lint "KAN-531 (repo scaffold)"

.PHONY: k3d
k3d: ## (V1+) Apply the k8s manifests to a local cluster
	@scripts/not-yet.sh k3d "KAN-538 (manifests)"
