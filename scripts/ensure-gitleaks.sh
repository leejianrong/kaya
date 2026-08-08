#!/usr/bin/env bash
# Resolve a gitleaks binary at the version this repo has pinned, and print its path on
# stdout. Everything else this script says goes to stderr, so callers can safely do
# `bin=$(scripts/ensure-gitleaks.sh)`.
#
# Why a bootstrap rather than a GitHub Action (KAN-580): the scan has to run in three
# places — the pre-push hook, `make secret-scan`, and CI — and an action only covers the
# third. Two mechanisms means two configs, two rule sets and two ways for local and CI to
# disagree about what a leak is. One pinned binary, fetched the same way everywhere, means
# the command in CI is character-for-character the command you ran before pushing.
#
# It also sidesteps gitleaks-action's licence key, which is required for repositories
# owned by an organisation. kaya is personal today; that is not a property to build a
# required status check on.
#
# THE PIN. VERSION and the four digests below are the whole trust anchor. A tarball that
# does not match its digest is deleted, not used — this runs in a pre-push hook, so a
# compromised release must not become code execution on a dev machine. To bump: read the
# new `gitleaks_<v>_checksums.txt` from the release page and replace all five values
# together. Never update VERSION alone; a stale digest fails closed, which is the point.
set -uo pipefail

VERSION=8.30.1
# sha256 of the release tarball, per platform, from gitleaks_8.30.1_checksums.txt.
SHA256_linux_x64=551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb
SHA256_linux_arm64=e4a487ee7ccd7d3a7f7ec08657610aa3606637dab924210b3aee62570fb4b080
SHA256_darwin_x64=dfe101a4db2255fc85120ac7f3d25e4342c3c20cf749f2c20a18081af1952709
SHA256_darwin_arm64=b40ab0ae55c505963e365f271a8d3846efbc170aa17f2607f13df610a9aeb6a5

say() { printf '%s\n' "$*" >&2; }
die() { printf '✗ %s\n' "$*" >&2; exit 1; }

# --- platform ------------------------------------------------------------------------
# gitleaks' asset names, which are not uname's: x86_64 is "x64", and it ships no Windows
# tarball we would use (WSL reports Linux, which is what we want anyway).
case "$(uname -s)" in
  Linux)  os=linux ;;
  Darwin) os=darwin ;;
  *)      die "unsupported OS $(uname -s). Install gitleaks $VERSION yourself and put it on PATH." ;;
esac
case "$(uname -m)" in
  x86_64|amd64) arch=x64 ;;
  arm64|aarch64) arch=arm64 ;;
  *) die "unsupported architecture $(uname -m). Install gitleaks $VERSION yourself and put it on PATH." ;;
esac

eval "want_sha=\${SHA256_${os}_${arch}}"

# --- already have it? ------------------------------------------------------------------
# An EXACT version match, not "some gitleaks". Rule sets and flags move between releases,
# so a distro-packaged 8.18 would scan a different repo than CI does and the gate would
# stop meaning one thing. Anything else is ignored in favour of the pinned download.
version_of() { "$1" version 2>/dev/null | tr -d '[:space:]'; }

if [ -n "${GITLEAKS_BIN:-}" ]; then
  # Explicit override, for an offline machine or a distro/nix-managed install. Still
  # version-checked: an override that silently scans with different rules is worse than
  # no override, because the gate keeps reporting green.
  [ -x "$GITLEAKS_BIN" ] || die "GITLEAKS_BIN=$GITLEAKS_BIN is not executable"
  got=$(version_of "$GITLEAKS_BIN")
  [ "$got" = "$VERSION" ] || die "GITLEAKS_BIN is gitleaks ${got:-unknown}, but this repo pins $VERSION"
  printf '%s\n' "$GITLEAKS_BIN"
  exit 0
fi

cache="${XDG_CACHE_HOME:-$HOME/.cache}/kaya/gitleaks/$VERSION"
bin="$cache/gitleaks"

# The cache is under $HOME rather than inside the repo on purpose: this project works in
# parallel git worktrees (CLAUDE.md §Conventions), and one download shared across all of
# them beats one per tree plus a .gitignore entry per tree.
#
# The cache hit is a bare `-x` test with no `gitleaks version` call behind it. That is
# sound because the version is in the path and nothing is ever written to that path except
# by the atomic rename at the bottom of this script, which happens only after the digest
# check passes. It is also worth doing: this runs on every push, and the process spawn it
# avoids is a third of what this script costs.
if [ -x "$bin" ]; then
  printf '%s\n' "$bin"
  exit 0
fi

# A system gitleaks that happens to be the pinned version is fine — use it and download
# nothing.
if command -v gitleaks >/dev/null 2>&1 && [ "$(version_of "$(command -v gitleaks)")" = "$VERSION" ]; then
  command -v gitleaks
  exit 0
fi

# --- fetch -----------------------------------------------------------------------------
command -v curl >/dev/null 2>&1 || die "curl is needed to fetch gitleaks $VERSION"
command -v sha256sum >/dev/null 2>&1 || command -v shasum >/dev/null 2>&1 \
  || die "sha256sum or shasum is needed to verify the gitleaks download"

asset="gitleaks_${VERSION}_${os}_${arch}.tar.gz"
url="https://github.com/gitleaks/gitleaks/releases/download/v${VERSION}/${asset}"

# The staging dir sits beside the cache, not in /tmp, so the install below is a rename
# within one filesystem and therefore atomic. Across filesystems `mv` degrades to
# copy-then-unlink, and an interrupted copy would leave a truncated binary at a path the
# cache-hit test above trusts on sight.
mkdir -p "$(dirname "$cache")" || die "could not create $(dirname "$cache")"
tmp=$(mktemp -d "${cache}.incoming.XXXXXX") || die "could not create a staging dir"
trap 'rm -rf "$tmp"' EXIT

say "▸ fetching gitleaks $VERSION ($os/$arch) — one-off, cached in $cache"
if ! curl -fsSL --retry 2 --max-time 120 -o "$tmp/$asset" "$url"; then
  say ""
  say "  Could not download $url"
  say "  This gate needs the scanner to run; it will not pass by pretending it scanned."
  say "  Offline? Install gitleaks $VERSION by hand and re-run with:"
  say "      GITLEAKS_BIN=/path/to/gitleaks make secret-scan"
  exit 1
fi

if command -v sha256sum >/dev/null 2>&1; then
  got_sha=$(sha256sum "$tmp/$asset" | cut -d' ' -f1)
else
  got_sha=$(shasum -a 256 "$tmp/$asset" | cut -d' ' -f1)
fi
if [ "$got_sha" != "$want_sha" ]; then
  rm -f "$tmp/$asset"
  die "sha256 mismatch for $asset
    expected $want_sha
    got      $got_sha
  Refusing to run it. Either the pin in this script is stale, or the download was tampered with."
fi

tar xzf "$tmp/$asset" -C "$tmp" gitleaks || die "could not extract gitleaks from $asset"
mkdir -p "$cache" || die "could not create $cache"
# Move into place as one step, so a killed download can never leave a half-written binary
# that the next run treats as cached.
mv "$tmp/gitleaks" "$bin" || die "could not install the binary to $bin"
chmod +x "$bin"

got=$(version_of "$bin")
[ "$got" = "$VERSION" ] || die "installed binary reports version ${got:-unknown}, expected $VERSION"

say "✓ gitleaks $VERSION verified (sha256 $want_sha) and cached"
printf '%s\n' "$bin"
