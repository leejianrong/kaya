#!/usr/bin/env bash
# Every external container image this repo names must be pinned by digest.
#
# KAN-538's central requirement, enforced rather than remembered. A base image referenced by tag
# changes underneath the build, which makes `org.opencontainers.image.revision` a claim about 1%
# of the artifact and silence about the other 99% — pandan's KAN-475, and the reason this card
# exists in the form it does.
#
# Offline, no registry call and no third-party action, so it runs in the pre-push hook and in the
# `Docs and secrets` CI job at no cost. It checks the *shape* of a reference, not that the digest
# still resolves; a digest that has been garbage-collected upstream is a different problem and
# needs the network to find.
#
# Deliberately NOT checked: images this repo builds itself (`kaya:dev` in the local k3d overlay).
# A locally built image has no registry digest to pin to, and demanding one would make the target
# unrunnable — which is how a guard gets deleted instead of satisfied.
set -uo pipefail
cd "$(dirname "$0")/.."

status=0
checked=0
exempt=0

# A reference is pinned when it carries `@sha256:<64 hex>`. Nothing else counts: `:latest` is
# obviously unpinned, and so is `:3.12.7-slim`, because a tag is mutable however specific it looks.
pinned() {
  [[ "$1" =~ @sha256:[0-9a-f]{64} ]]
}

# Ours, so exempt. Anchored on the whole reference rather than a substring: `kayabase/python` is
# somebody else's image and must still be pinned.
ours() {
  [[ "$1" =~ ^(kaya|kaya:.*|ghcr\.io/leejianrong/kaya(:.*)?)$ ]]
}

complain() {
  printf '✗ %s:%s\n    unpinned image reference: %s\n' "$1" "$2" "$3"
  printf '    resolve it with: docker buildx imagetools inspect %s | head -3\n' "${3%%@*}"
  status=1
}

# --- every Dockerfile in the repo -----------------------------------------------------------------
# KAN-573: this used to read the literal path `Dockerfile`, so `mcp/Dockerfile` (new in that card)
# would have been invisible to it — pinned by hand today, silently driftable tomorrow, which
# defeats the point of a guard. Found by `find` rather than a second literal path, so the *next*
# Dockerfile this repo adds is covered on its first commit rather than on whichever later commit
# somebody remembers to add it here. `.venv`/`node_modules`/`dist` are pruned because a vendored or
# built tree can legitimately contain a `Dockerfile` this repo does not own and did not write.
#
# The references live in ARG defaults, which is what makes them overridable and what makes them
# easy to leave unpinned. Read those, and read any literal FROM too, in case a stage stops using
# the ARGs.
while IFS= read -r -d '' dockerfile; do
  dockerfile=${dockerfile#./}
  while IFS=: read -r line content; do
    # `ARG NAME=ref` where the value looks like an image reference (has a `/` or a `:`).
    ref=$(sed -nE 's/^ARG[[:space:]]+[A-Z_]*(BASE|IMAGE)=(.+)$/\2/p' <<<"$content")
    if [ -z "$ref" ]; then
      # A literal `FROM ref [AS stage]`, skipping the `FROM ${VAR}` forms handled above.
      ref=$(sed -nE 's/^FROM[[:space:]]+([^$][^[:space:]]*).*$/\1/p' <<<"$content")
    fi
    [ -z "$ref" ] && continue
    if ours "$ref"; then exempt=$((exempt + 1)); continue; fi
    checked=$((checked + 1))
    pinned "$ref" || complain "$dockerfile" "$line" "$ref"
  done < <(grep -nE '^(ARG|FROM)[[:space:]]' "$dockerfile")
done < <(find . \
  \( -name .venv -o -name node_modules -o -name dist -o -name .git \) -prune -o \
  -type f -name Dockerfile -print0 | sort -z)

# --- compose and the manifests -------------------------------------------------------------------
# `image:` in YAML, wherever it appears. `deploy/k8s/overlays/` is included: an overlay that pins
# nothing is exactly as dangerous as a base that pins nothing, and the `ours` exemption is what
# lets the local overlay's `kaya:dev` through.
while IFS=: read -r file line content; do
  ref=$(sed -nE 's/^[[:space:]-]*image:[[:space:]]*"?([^"[:space:]#]+)"?.*$/\1/p' <<<"$content")
  [ -z "$ref" ] && continue
  # A kustomize `images:` block writes `name:` / `newName:`, not `image:`, so anything left here
  # is a real reference. Skip templated ones rather than failing on syntax we do not own.
  [[ "$ref" == *'${'* ]] && continue
  if ours "$ref"; then exempt=$((exempt + 1)); continue; fi
  checked=$((checked + 1))
  pinned "$ref" || complain "$file" "$line" "$ref"
done < <(grep -rnE '^[[:space:]-]*image:[[:space:]]' docker-compose.yml deploy 2>/dev/null)

if [ "$status" -ne 0 ]; then
  printf '\n  A tag is a mutable pointer. See the header of ./Dockerfile for why this is fatal\n'
  printf '  rather than untidy, and for how to resolve a digest.\n'
  exit 1
fi

printf '✓ %d external image reference(s) pinned by digest (%d of kaya'"'"'s own exempted)\n' \
  "$checked" "$exempt"
