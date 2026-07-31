#!/usr/bin/env bash
# Honest failure for a Makefile target whose slice hasn't landed. Exits non-zero so
# a script or agent can't mistake "not built" for "passed" — an installer that exits
# 0 without installing is the "looks done, isn't" failure mode (pandan KAN-434).
set -uo pipefail
printf '✗ `make %s` is not available yet.\n' "${1:-?}"
printf '  Blocked on: %s\n' "${2:-application code}"
printf '  See docs/SLICES.md, and CLAUDE.md §Build status.\n'
exit 1
