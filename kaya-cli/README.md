# kaya-cli

The `kaya` console script. Distribution name `kaya-notes`, one entry point, no verbs yet.

```bash
uv sync --all-extras
uv run kaya            # prints what it is and what hasn't landed, exits 0
uv run kaya --version  # which build is this?
uv run pytest -q
uv run ruff check .
```

## Is my build stale?

Ask it. `--version` names the commit the binary was built from, and a build that wasn't built by
the release pipeline says so rather than staying quiet:

```console
$ kaya --version
kaya 0.2.0 (a1b2c3d)                                 # a release asset, built from a1b2c3d

$ kaya --version
kaya 0.2.0 (source checkout, not a released build)   # whatever is in your working tree
```

The second line is the point. Pandan's CLI printed a bare `0.3.0`, two user-visible fixes shipped
without a version bump, and a stale binary on `$PATH` became indistinguishable from current source —
which cost two false bug reports before anyone suspected the binary
([ADR 0007](../docs/adr/0007-release-provenance-from-the-first-release.md)). If you are about to
report a bug, paste this line into it.

An unstamped or badly stamped build always falls back to the source-checkout wording. It will never
print an empty `()` or an invented sha, because "I am not a release" is the only safe thing to say
when the answer is unknown. The mechanism is in
[`kaya-client`](../kaya-client/README.md#stamping-a-release-build).

## Want a shorter name?

Symlink it:

```bash
ln -sf ~/.local/bin/kaya ~/.local/bin/ky
```

There is deliberately no second console script. Pandan shipped `pdn` as a second
`[project.scripts]` entry and had to withdraw it (`KAN-442`): a packaging installer generates that
alias, but the release asset is a PyInstaller `--onefile` executable with no entry points in it at
all, so `pdn` existed for `uv tool install` users and never for anyone who downloaded the release.
A symlink works identically on both install paths, which is the whole reason it is the documented
answer (ADR 0007 §4).

## What lives here and what doesn't

An adapter's whole job is turning argv into a `kaya-client` call and printing what comes back
([ADR 0004](../docs/adr/0004-shaping-lives-in-the-shared-client.md)). Projection, truncation,
aggregates and serialization all live in `kaya-client`'s `render()`; the two `--version` forms above
come from `kaya-client`'s `version_line()`, for the same reason and one more — V6's MCP server
reports its provenance through that same function. If a formatting rule starts growing in this
package, that is the bug ADR 0004 exists to prevent.

Verbs, `--format {human,json,toon}` and the named exit-code table arrive with the rest of V2a. Until
then this is `--version`, `--help`, and a banner saying so.
