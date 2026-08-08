"""The one value a release build rewrites. **In the repository it is always empty.**

This module is data, not logic. It exists so that `provenance.py` can ask "which commit was I
built from?" without a `.git` directory, because the release artifact is a PyInstaller `--onefile`
executable that has neither a repository nor a package index behind it (ADR 0007 §1).

### How a build populates it

The release workflow rewrites this file *in the checkout* immediately before packaging, and the
build backend (hatchling for the wheel, PyInstaller for the executable) picks up the rewritten
module the same way it picks up every other module in `src/kaya_client/`. Nothing needs to be
declared as package data, and nothing needs `--add-data`.

    scripts/stamp-build.sh "$GITHUB_SHA"      # rewrites this file in place
    cd kaya-client && uv build                 # or: pyinstaller --onefile ...

`scripts/stamp-build.sh` is the only supported way to write this value. It validates its argument
against the same rule `provenance.py` applies on the way out, so a workflow cannot stamp
`${GITHUB_SHA}` unexpanded, `unknown`, or the empty string and discover it at `--version` time.

**Order matters, and only in one place:** stamp *after* the test suite and *before* the build.
`tests/test_provenance.py::test_the_committed_stamp_is_empty` asserts this file is unstamped, which
is what keeps a real sha from ever being committed — a committed sha would make every source
checkout claim provenance it does not have, which is the exact failure ADR 0007 §1 is about. CI
tests a clean checkout, so that assertion is only reachable in a release job that runs tests after
stamping. Don't; the commit was already tested by CI.

### What KAN-544's gate must assert

After building, execute the artifact and read `--version` (ADR 0007 §2). The release form is

    kaya <version> (<first 7 of the sha>)

so the check is a suffix match against a locally computed short sha:

    got=$("$ARTIFACT" --version)
    want="kaya ${VERSION} (${GITHUB_SHA:0:7})"
    [ "$got" = "$want" ] || { echo "artifact cannot identify itself: $got"; exit 1; }

An unstamped or badly stamped build prints `(source checkout, not a released build)` instead and
fails that comparison, which is the whole point: the failure direction is "I am not a release",
never a plausible-looking sha.

**Compare the whole line, not just the sha.** A sha-only gate passes an artifact that carries the
right commit beside the wrong version, and that is the only way this mechanism can fail quietly —
every other failure prints the source-checkout wording, which any comparison catches.

### The `--onefile` path, as measured

Three real onefile binaries were built from this branch on 2026-08-09 (`HEAD` was `575e6d9`) and
executed. All three exited `0`:

    stamped, with --copy-metadata       kaya 0.2.0 (575e6d9)
    stamped, without --copy-metadata    kaya 0.2.0 (575e6d9)
    unstamped, without --copy-metadata  kaya 0.2.0 (source checkout, not a released build)

Two things follow, and one earlier guess is retracted.

- **The stamp survives onefile.** The sha reaches the binary, and an unstamped onefile degrades to
  the source-checkout form rather than to anything that reads as provenance.
- **The third row is the fixture for KAN-544's `[mutate]` case.** ADR 0007 §5 wants the release job
  proven by watching it fail on an artifact with the sha stripped; that artifact is producible by
  building without running `scripts/stamp-build.sh` first, and the line above is exactly what the
  gate must reject. It does not need inventing.
- **Retracted:** an earlier draft of this docstring asserted that PyInstaller drops the dist-info,
  so that a build without `--copy-metadata` would report version `0.0.0`. It does not reproduce —
  `importlib.metadata` resolved the real version in the middle row above. Keep
  `--copy-metadata kaya-notes --copy-metadata kaya-client` in the build anyway: it costs nothing,
  and the failure it insures against is *silent* rather than loud. A version that fell back to
  `0.0.0` would still carry a valid sha and would sail through a sha-only gate. That is the honest
  argument for it, and for comparing the whole line.

One trap that is not a guess: **`[project.scripts]` entries do not exist on a onefile artifact at
all** (`KAN-442`, ADR 0007 §4). That is why there is one console script and the short alias is a
documented symlink.
"""

# A 40-character lowercase hex sha on a release build; empty everywhere else. `provenance.py`
# validates it rather than trusting it, so an unexpanded template or a sentinel word degrades to
# the source-checkout form instead of being printed as if it were provenance.
COMMIT = ""
