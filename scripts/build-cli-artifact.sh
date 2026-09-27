#!/usr/bin/env bash
# Build the `kaya` release executable: one PyInstaller `--onefile` binary. KAN-544.
#
#   scripts/build-cli-artifact.sh [outdir]        # default: dist/
#
# A script rather than four lines inlined in the release workflow, so that the artifact the gate
# is proven against locally and the artifact CI ships are produced by the same command. ADR 0007
# §5 wants the gate proven by watching it fail; that proof is worth much less if the mutation is
# built by hand and the release is built by YAML.
#
# THE STAMP IS NOT THIS SCRIPT'S JOB, ON PURPOSE. Run `scripts/stamp-build.sh <sha>` first for a
# release build, and don't for the `[mutate]` fixture. Building unstamped has to stay a thing this
# script will cheerfully do, because "an unstamped artifact" is exactly the case the gate exists
# to reject — see kaya-client/src/kaya_client/_build_stamp.py's docstring.
#
# `--copy-metadata` is insurance rather than a requirement: it was measured on 2026-08-09 that the
# version resolves correctly without it. It stays because the failure it covers is *silent* — a
# version falling back to `0.0.0` still carries a valid sha, and would pass a sha-only gate. That
# is also why scripts/check-release-artifact.sh compares the whole line.
#
# `[project.scripts]` entries do not exist on a onefile artifact (KAN-442, ADR 0007 §4), which is
# why the entry point below is the module path and not the console script name.
#
# `--add-data` carries the packaged `kaya` skill (R18/KAN-1200) into the onefile, where it unpacks
# under `sys._MEIPASS` — mirrors pandan's own KAN-431 `--add-data "pandan_cli/skills:pandan_cli/
# skills"` line. The destination path is `kaya_cli/skills` (not `src/kaya_cli/skills`) so it matches
# what `kaya_cli.context.packaged_skill_path()` looks for under `_MEIPASS` either way this is built.
# A build without this line still installs the hook and just reports the skill as unbundled
# (`packaged_skill_path()` returns `None` rather than raising).
#
# THE SOURCE HALF IS AN ABSOLUTE PATH, NOT `src/kaya_cli/skills` RELATIVE TO THIS SCRIPT'S `cd
# kaya-cli` BELOW. PyInstaller 6.22 resolves a relative `--add-data` source against `--specpath`
# (`$work`, a `mktemp -d` outside the repo entirely), not the working directory the command runs
# from — undocumented and a behaviour change from whatever version this script was first proven
# against, since nothing here ever pinned one (`uv run --with pyinstaller` floats to latest). Measured
# directly: the exact invocation below fails with `Unable to find '$work/src/kaya_cli/skills'` when
# the source is spelled relatively, and succeeds once it is spelled as `$(pwd)/src/kaya_cli/skills`.
# An absolute path sidesteps the question of which directory PyInstaller resolves a relative one
# against, this version or the next.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

out=$(mkdir -p "${1:-dist}" && cd "${1:-dist}" && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

cd kaya-cli
uv run --with pyinstaller pyinstaller \
  --onefile \
  --name kaya \
  --distpath "$out" \
  --workpath "$work/build" \
  --specpath "$work" \
  --copy-metadata kaya-notes \
  --copy-metadata kaya-client \
  --add-data "$(pwd)/src/kaya_cli/skills:kaya_cli/skills" \
  --noconfirm \
  --clean \
  --log-level WARN \
  src/kaya_cli/__main__.py

printf '✓ built %s/kaya\n' "$out"
