# ADR 0007 — `--version` identifies the build, and a release refuses to ship an artifact that can't

- **Status:** Accepted
- **Date:** 2026-08-01
- **Deciders:** Jian (inherited conclusions, made binding)
- **Context source:** pandan V50 / `KAN-435`, pandan `KAN-442`, pandan open bug `KAN-484`.

## Context

Pandan shipped a CLI whose `--version` printed a bare number. A binary built from version `0.3.0` kept
reporting `0.3.0` after two user-visible fixes landed without a bump, so a stale binary on `$PATH` was
indistinguishable from current source. **It caused two false bug reports**, and retrofitting the fix was a
whole slice — which then had to be sequenced *first* in its wave, because every guarantee the other slices
added was unverifiable in the field while "which build am I running?" had no answer.

Two related facts from the same history:

- **The version-bump guard has a bug that is cheaper to avoid than to inherit.** Pandan's diffs against the
  **remote tip** rather than the base ref, so it false-positives on merge commits. Open as `KAN-484`.
- **A console-script alias is an install-method-dependent feature.** Pandan declared `pdn` as a second
  `[project.scripts]` entry, which a packaging installer generates — but the release is a PyInstaller
  `--onefile` build producing exactly one executable, so `pdn` existed for `uv tool install` users and
  never for anyone who downloaded the release asset. It was withdrawn (`KAN-442`). The generalised lesson:
  **verify a packaging feature on the install path your docs lead with, not the one your tests use.**

## Decision

### 1. `--version` prints provenance, from the first release

- A released artifact prints `kaya <version> (<short-sha>)` — the commit it was built from, embedded at
  package time.
- A source checkout prints `kaya <version> (source checkout, not a released build)`, explicitly. Silence
  here is what made pandan's staleness undetectable.
- The same reasoning applies to the MCP container image: provenance labels, and **pinned base image
  digests**. Pandan's image build floats on `uv:latest` and `python:3.12-slim`, which undermines the
  provenance labels it added (`KAN-475`). Kaya pins from the first image.

### 2. The release gate

**A release job fails if the artifact cannot identify itself.** After building, the workflow executes the
built artifact, reads `--version`, and asserts it reports a real commit sha matching `HEAD` — not the
source-checkout string, not an empty value. An artifact that can't say what it is does not ship.

This is the part that makes the guarantee structural rather than aspirational. `--version` printing the
right thing on a developer's machine proves nothing about what the release pipeline produced.

### 3. Version-bump-on-behavioural-change, diffed against the base ref

A change touching a shipped package's behaviour bumps that package's version **in the same PR**, enforced
by a pre-push hook and a CI job.

**The guard diffs against the merge-base with `main`** (`git merge-base HEAD origin/main`), not the remote
tip and not the previous push. This is pandan's `KAN-484` avoided rather than inherited: diffing against the
remote tip makes a merge commit look like it touched everything the branch touched, so the guard
false-positives and gets ignored, and a guard that gets ignored protects nothing.

Scope is per-package (`kaya-client`, `kaya-cli`, `mcp`), and the guard distinguishes behavioural paths from
docs and tests so a README fix doesn't demand a release.

### 4. One console script

The console script is `kaya`. **There is no short alias**, per `KAN-442`'s lesson: a promised command that
half the install paths don't provide is worse than no promise. The README documents
`ln -sf ~/.local/bin/kaya ~/.local/bin/ky` for anyone who wants one, which works identically on both install
paths — as the alias never did.

### 5. Mutation-test both guards

The release gate and the version-bump guard are "this can't regress" guards, so per PLAN §Testing they are
proven by watching them fail: build an artifact with the sha stripped and confirm the release job goes red
naming the right thing; craft a behavioural diff with no version change and confirm the guard fires; craft a
merge commit and confirm it **doesn't**. Restore non-destructively (`git apply -R`), never `git checkout --`,
which overwrites from the index and silently discards uncommitted work.

The third case is the one that matters most, because it's the assertion pandan's guard would fail today and
it's the reason to write the test before trusting the guard.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Bare semantic version, add provenance if confusion arises | Confusion already arose, twice, in the sibling project. The cost of the retrofit was a full slice plus two wasted debugging sessions. |
| Rely on the git tag alone | A tag identifies a commit, not the binary someone actually has on `$PATH`. That gap *is* the bug. |
| Trust the bump-on-change convention without a guard | Pandan's convention held until the day it didn't, and the day it didn't produced the false bug reports. |
| Diff the guard against the previous push | What pandan does, and the source of `KAN-484`. Merge commits break it. |
| Ship a short alias via a second `[project.scripts]` entry | Verified not to work on the `--onefile` release path (`KAN-442`). A symlink is honest and works everywhere. |

## Consequences

- **Positive:** "is my `kaya` stale?" is answerable in one command from the first release, and a release
  that can't answer it doesn't happen. The two known guard bugs in the sibling (`KAN-484` merge-commit
  false-positives, `KAN-475` floating image bases) are avoided rather than inherited, at a cost of reading
  this ADR.
- **Neutral:** a small amount of build plumbing (sha embedding, a post-build assertion) in the first release
  slice rather than the fifth.
- **Negative / deferred:** the bump guard adds friction to every behavioural PR, and some judgement about
  what counts as behavioural. Pandan's answer — a checklist line plus a cheap automated check, not a perfect
  classifier — is good enough and is adopted. Expect to tune the path patterns once.
- **A note for the docs:** the CLI README carries an "is my build stale?" section from the first release,
  because the diagnostic only helps if the person confused by a symptom knows to run it.
