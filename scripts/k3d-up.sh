#!/usr/bin/env bash
# Apply deploy/k8s to a throwaway local cluster and prove the pod actually serves (ADR 0010).
#
# The ADR's words: "a manifest set that has never been applied is a guess". This is the thing that
# stops it being a guess, and it therefore ends with requests rather than with `kubectl apply`
# reporting success — `apply` succeeding only means the API server liked the YAML.
#
# No registry, deliberately. `docker build` → `k3d image import` → `imagePullPolicy: Never` puts
# the image in the node's containerd store directly. A local registry would mean a second
# container to run, an insecure-registry entry in the cluster config, and a push on every
# iteration, in exchange for nothing this needs.
#
#     scripts/k3d-up.sh          create if absent, build, import, apply, smoke-test
#     scripts/k3d-up.sh --down   delete the cluster
#
# Overridable: KAYA_K3D_CLUSTER (default `kaya`), KAYA_K3D_PORT (default 8080).
set -euo pipefail
cd "$(dirname "$0")/.."

CLUSTER="${KAYA_K3D_CLUSTER:-kaya}"
PORT="${KAYA_K3D_PORT:-8080}"
IMAGE="${KAYA_IMAGE:-kaya:dev}"

# Every kubectl call names its context. Two reasons, and neither is about any particular machine:
# the `k3d-<name>` context exists only for as long as the cluster does, so a target that relies on
# "whatever is current" depends on state it did not establish; and this has to be runnable
# somewhere other than the laptop it was written on — the homelab is the stated target (ADR 0010)
# and nobody there will have this kubeconfig.
CONTEXT="k3d-${CLUSTER}"
KUBECTL=(kubectl --context "$CONTEXT")

BASE_URL="http://localhost:${PORT}"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    printf '✗ %s is not on PATH. %s\n' "$1" "$2"
    exit 1
  }
}

if [ "${1:-}" = "--down" ]; then
  k3d cluster delete "$CLUSTER"
  printf '✓ cluster %s deleted\n' "$CLUSTER"
  exit 0
fi

need k3d 'https://k3d.io — `brew install k3d` or the install script'
need kubectl 'https://kubernetes.io/docs/tasks/tools/'
need docker 'the image has to be built before it can be imported'

# --- 1. the cluster ------------------------------------------------------------------------------
if k3d cluster list "$CLUSTER" >/dev/null 2>&1; then
  printf '▸ reusing cluster %s\n' "$CLUSTER"
else
  printf '▸ creating cluster %s\n' "$CLUSTER"
  # One server, no agents. This is a manifest check, not a capacity test, and a second node buys
  # nothing while costing another ~500 MiB of a laptop's memory.
  #
  # `--port 8080:80@loadbalancer` publishes k3s's Traefik on the host, which is what makes the
  # Ingress — rather than a port-forward past it — the thing under test.
  k3d cluster create "$CLUSTER" \
    --servers 1 \
    --agents 0 \
    --port "${PORT}:80@loadbalancer" \
    --wait
fi

# --- 2. the image --------------------------------------------------------------------------------
scripts/image-build.sh "$IMAGE"

printf '▸ importing %s into %s\n' "$IMAGE" "$CLUSTER"
k3d image import "$IMAGE" --cluster "$CLUSTER"

# --- 3. the manifests ----------------------------------------------------------------------------
printf '▸ applying deploy/k8s/overlays/local to %s\n' "$CONTEXT"
"${KUBECTL[@]}" apply -k deploy/k8s/overlays/local

# The image is imported, not pulled, and its tag never changes — so `apply` alone leaves an
# already-running pod on the previous build with no diff to notice. Restarting is what makes a
# second run mean anything.
"${KUBECTL[@]}" -n kaya rollout restart statefulset/kaya-postgres deployment/kaya >/dev/null
"${KUBECTL[@]}" -n kaya rollout status statefulset/kaya-postgres --timeout=180s
"${KUBECTL[@]}" -n kaya rollout status deployment/kaya --timeout=180s

# --- 4. the part that makes this a proof rather than an apply ------------------------------------
# Through the Ingress, on the host's port, exactly as a browser would reach it.
printf '\n▸ smoke test through the ingress at %s\n' "$BASE_URL"

fail=0
BODY_FILE=$(mktemp)
trap 'rm -f "$BODY_FILE"' EXIT

check() {
  local label="$1" path="$2" expect_status="$3" expect_grep="$4"
  local status body
  status=$(curl -sS -o "$BODY_FILE" -w '%{http_code}' "${BASE_URL}${path}" 2>/dev/null || echo 000)
  body=$(cat "$BODY_FILE")

  if [ "$status" != "$expect_status" ] || ! grep -q "$expect_grep" <<<"$body"; then
    printf '  ✗ %-34s %s → %s  %s\n' "$label" "$path" "$status" "${body:0:120}"
    fail=1
    return
  fi
  printf '  ✓ %-34s %s → %s  %s\n' "$label" "$path" "$status" "${body:0:80}"
}

# Liveness, which the probes in deployment.yaml also use.
check "health"                     /health                    200 '"status":"ok"'
# The SPA, from the same origin as the API — the single-artifact claim, checked.
check "the built SPA at the root"  /                          200 '<div id="app">'
# A client-side deep link. History fallback, so a pasted URL loads the app.
check "history fallback"           /notes/NOTE-12             200 '<div id="app">'
# And the half that the fallback must NOT swallow: an API path with no token is a JSON refusal,
# not the index page. `backend/tests/unit/test_spa_single_origin.py` is the exhaustive version;
# this is the same assertion made against a real pod behind a real ingress.
check "the API is not swallowed"   /api/v1/notes              401 '"code":"authentication_required"'
check "an unknown API path 404s"   /api/v1/nonesuch           404 '"code":"not_found"'

printf '\n'
if [ "$fail" -ne 0 ]; then
  printf '✗ the manifests applied but the pod does not serve correctly.\n'
  printf '  kubectl --context %s -n kaya logs deployment/kaya\n' "$CONTEXT"
  exit 1
fi

printf '✓ deploy/k8s applies and the pod serves, at %s\n' "$BASE_URL"
printf '  logs:   kubectl --context %s -n kaya logs -f deployment/kaya\n' "$CONTEXT"
printf '  delete: make k3d-down      (the cluster costs ~575 MiB while it runs)\n'
