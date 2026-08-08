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

### Two traps on the `--onefile` path

- `importlib.metadata.version(...)` needs the dist-info to be bundled. PyInstaller does not copy it
  by default, so a onefile build without `--copy-metadata kaya-notes --copy-metadata kaya-client`
  reports version `0.0.0` while carrying a perfectly good sha. The gate above catches it *only*
  because it compares the version too — compare the whole line, not just the sha.
- `[project.scripts]` entries do not exist on a onefile artifact at all (`KAN-442`, ADR 0007 §4).
  That is why there is one console script and the short alias is a documented symlink.
"""

# A 40-character lowercase hex sha on a release build; empty everywhere else. `provenance.py`
# validates it rather than trusting it, so an unexpanded template or a sentinel word degrades to
# the source-checkout form instead of being printed as if it were provenance.
COMMIT = ""
