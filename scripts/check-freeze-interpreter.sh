#!/usr/bin/env bash
# The interpreter about to be frozen decides who can run the release asset. KAN-719.
#
#   scripts/check-freeze-interpreter.sh [python] [max-glibc-minor]
#
# PyInstaller does not compile an interpreter; it copies the one it is pointed at, `libpython` and
# all, into the onefile. So the glibc floor of `kaya-linux-x86_64` is the glibc floor of this
# `libpython` and nothing else. v0.4.0 shipped requiring `GLIBC_2.38` and died on Ubuntu 22.04,
# Debian 12, RHEL 9 and Amazon Linux 2023 because the build ran on `ubuntu-latest`, where uv found
# the runner's preinstalled CPython 3.12 and used it — Ubuntu 24.04's `libpython3.12.so` needs
# `GLIBC_2.38`. Measured 2026-08-09, both interpreters, `readelf -V`:
#
#   Ubuntu 24.04 system CPython 3.12 ... requires up to GLIBC_2.38
#   uv-managed CPython 3.12          ... requires up to GLIBC_2.17   (python-build-standalone)
#
# This runs BEFORE the freeze, so a wrong interpreter costs a second rather than a whole build, and
# it fails with the reason rather than with a portability failure on a stranger's laptop.
#
# TWO FAILURES, AND THEY ARE DIFFERENT PROBLEMS.
#
# 1. NO SHARED LIBPYTHON AT ALL. manylinux's preinstalled CPython at /opt/python/cp312-cp312 is
#    built static (`Py_ENABLE_SHARED = 0`), and it is what uv picks in that container unless told
#    otherwise — `/usr/bin/python3` there is a symlink into it. PyInstaller's own words for this are
#    "Python was built without a shared library, which is required by PyInstaller", several minutes
#    later and without saying which interpreter it meant.
#
# 2. A SHARED LIBPYTHON WITH TOO NEW A FLOOR. That is the v0.4.0 defect itself.
#
# WHAT THIS IS NOT. It is not the portability *proof*. It looks at `libpython` and at nothing else
# the freeze pulls in. The proof is that scripts/check-release-artifact.sh runs the finished binary,
# and the release workflow runs it inside a glibc-2.28 container, so an asset that would not start
# on Ubuntu 22.04 cannot answer `--version` there.
#
# WHY NOT `strings dist/kaya | grep GLIBC_`. Because it is inert, measured rather than assumed. The
# published v0.4.0 asset — the one that dies with `GLIBC_2.38 not found` — reports a maximum of
# `GLIBC_2.14`, exactly like a good build does. PyInstaller ships a *prebuilt* bootloader in its
# wheel, compiled against an old glibc, so the visible symbols do not vary with the build host at
# all. A guard that returns the same answer for the broken artifact and the fixed one is not a
# guard, and it is worse than nothing because it looks like one.
set -uo pipefail

python=${1:-kaya-cli/.venv/bin/python}
# AlmaLinux 8, the manylinux_2_28 userland the release builds in: Ubuntu 20.04+, Debian 11+, RHEL 8+.
max_minor=${2:-28}

if [ ! -x "$python" ]; then
  printf '✗ %s is not an executable interpreter\n' "$python" >&2
  exit 1
fi

libpython=$("$python" - <<'PY'
import glob, os, sysconfig

if not sysconfig.get_config_var("Py_ENABLE_SHARED"):
    print("STATIC")
    raise SystemExit(0)

# Match by the filename THIS interpreter's build declares, never by `libpython3.*.so*`. A tree can
# hold more than one: manylinux's /usr has libpython3.6m.so.1.0 sitting beside the 3.12 it ships,
# and a glob picked that one up and cheerfully reported the wrong library's glibc floor.
names = [n for n in (sysconfig.get_config_var("INSTSONAME"),
                     sysconfig.get_config_var("LDLIBRARY")) if n]
names.append("libpython%s*.so*" % sysconfig.get_python_version())

seen = []
for var in ("LIBDIR", "LIBPL", "installed_base"):
    root = sysconfig.get_config_var(var)
    if not root:
        continue
    for name in names:
        seen += [p for p in glob.glob(os.path.join(root, "**", name), recursive=True)
                 if ".so" in os.path.basename(p)]
print(sorted(seen, key=len)[0] if seen else "")
PY
)

if [ "$libpython" = "STATIC" ]; then
  printf '✗ %s has no shared libpython (Py_ENABLE_SHARED = 0); PyInstaller cannot freeze it.\n' \
    "$python" >&2
  printf '    In the manylinux container this is the preinstalled /opt/python/cp312-cp312.\n' >&2
  printf '    Install uv managed CPython and set UV_PYTHON_PREFERENCE=only-managed.\n' >&2
  exit 1
fi

if [ -z "$libpython" ]; then
  printf '✗ could not locate a shared libpython for %s\n' "$python" >&2
  exit 1
fi

if ! command -v readelf >/dev/null 2>&1; then
  printf '! readelf is not installed; cannot read the glibc floor of %s\n' "$libpython" >&2
  exit 1
fi

symbols=$(readelf -V "$libpython" 2>/dev/null | grep -oE 'GLIBC_2\.[0-9]+' | sort -V | uniq)
if [ -z "$symbols" ]; then
  printf '✗ %s declares no GLIBC version requirements at all; refusing to guess\n' "$libpython" >&2
  exit 1
fi

highest=$(printf '%s\n' "$symbols" | tail -1)
minor=${highest#GLIBC_2.}

if [ "$minor" -gt "$max_minor" ]; then
  printf '✗ %s requires %s, above the GLIBC_2.%s floor this release promises.\n' \
    "$libpython" "$highest" "$max_minor" >&2
  printf '    Freezing it produces an asset that will not start on Ubuntu 22.04, Debian 12,\n' >&2
  printf '    RHEL 9 or Amazon Linux 2023 — KAN-719, exactly as shipped in v0.4.0.\n' >&2
  printf '    The release build runs in quay.io/pypa/manylinux_2_28_x86_64 with\n' >&2
  printf '    UV_PYTHON_PREFERENCE=only-managed for this reason.\n' >&2
  exit 1
fi

printf '✓ %s requires at most %s (floor GLIBC_2.%s)\n' "$(basename "$libpython")" "$highest" "$max_minor"
