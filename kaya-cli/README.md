# kaya-cli

The `kaya` console script. Distribution name `kaya-notes`, one entry point, nine verbs.

## Install

Download the asset from the
[latest release](https://github.com/leejianrong/kaya/releases/latest) and put it on your `PATH` as
`kaya`:

```bash
mkdir -p ~/.local/bin
curl -fsSL -o ~/.local/bin/kaya \
  https://github.com/leejianrong/kaya/releases/latest/download/kaya-linux-x86_64
chmod +x ~/.local/bin/kaya
kaya --version
```

**`kaya-linux-x86_64`, Linux x86_64, glibc 2.28 or newer.** The release asset is a PyInstaller
`--onefile` executable, which is per-platform by construction; the pipeline does one build and
claims only what that build can prove, so there is no macOS or Windows build. It is built inside a
`manylinux_2_28` container and runs on Ubuntu 20.04+, Debian 11+, RHEL/Rocky/Alma 8+ and Amazon
Linux 2023 with nothing installed. The asset is *named* for the downloads folder it lands in and the
*command* is `kaya` — a bare `kaya` in a release listing would collide with everything else in
there.

`v0.4.0` predates that container and requires `GLIBC_2.38`, so it fails to start on anything older
than Ubuntu 24.04 with `Failed to load Python shared library … version 'GLIBC_2.38' not found`
(KAN-719). If you see that line, take a later release.

Two things follow from `--onefile` that surprise people, both covered below: the executable bit does
not survive the download, hence `chmod +x`, and there are no `[project.scripts]` entry points inside
the binary, which is why the short name is a symlink.

## Working on it

```bash
uv sync --all-extras
uv run kaya            # the banner, your five most recent notes and the aggregate, exits 0
uv run kaya --version  # which build is this?
uv run kaya --nope     # usage on stderr, `error<TAB>usage<TAB>…` on stdout, exits 2
uv run pytest -q
uv run ruff check .
```

## The verbs (KAN-541, completed by KAN-551)

```console
$ export KAYA_TOKEN=…                      # a pandan PAT. KAYA_API_URL defaults to :8000
$ kaya note list
NOTE-12  Groceries       home/groceries.md
NOTE-3   A reading list

$ kaya note get NOTE-12 --format json
{"ref":"NOTE-12","id":12,"title":"Groceries",…}

$ kaya note list --format toon
notes[2]{ref,id,title,body,path,created_at,updated_at}:
  NOTE-12,12,Groceries,"milk\neggs",home/groceries.md,…
  NOTE-3,3,A reading list,"","",…
```

`note get` takes `NOTE-12`, `note-12` or bare `12`, and passes whichever you typed to the API's one
ref resolver ([ADR 0008](../docs/adr/0008-note-identity.md)) rather than normalising it here.

`note create`, `edit`, `move` and `delete` landed with KAN-551, so the set is complete. `move` is
sugar over `edit`'s `PATCH` rather than a second endpoint, because [ADR
0008](../docs/adr/0008-note-identity.md) makes moving a note a write to one column with no link
rewriting. `edit` takes an optional `--if-updated-at`, which is [ADR
0009](../docs/adr/0009-optimistic-concurrency-on-note-bodies.md)'s precondition: send the
`updated_at` you last read and a stale one is refused with both timestamps named; omit it and the
write is a plain overwrite, by specification.

### `--format {human,json,toon}`, and `--json`

[ADR 0005](../docs/adr/0005-born-agent-conformant.md) §contract 1: one serializer in `kaya-client`,
so the formats cannot drift. `--json` is a documented alias for `--format json`, and **`--format`
wins if both are given** — which is why `--format`'s argparse default is `None` rather than
`"human"`: with a default of `"human"`, "the user typed `--format human`" and "the user typed
nothing" become the same value and the alias would overrule the flag it is an alias *for*.

`toon` pays for uniform rows and not for a single object. Measured against compact JSON over 40
notes with `o200k_base` (`kaya-client/scripts/measure_toon_delta.py`): `note list` **−11.3%**,
`note get` **+1.4%**. Use it for lists; `json` is not worse for a single read.

Errors render in the requested format too, so a consumer that asked for JSON does not get a
tab-separated row on the one line it most needed to parse.

### Configuration

Resolved in `kaya-client`'s `config.py` so that V6's MCP server reads exactly the same keys
(PLAN §Config). Each key is taken from the first tier that supplies it: **environment, then the
config file**. The third tier PLAN names, the nearest `.mcp.json`, arrives with V6.

| | |
|---|---|
| `KAYA_TOKEN` | A pandan PAT. **Required** — ADR 0002 gives kaya no way to mint one. Missing → `error<TAB>no_credential<TAB>…<TAB>KAYA_TOKEN` on stdout, exit `1` |
| `KAYA_API_URL` | The deployment. Defaults to `http://localhost:8000`, which is what `make up` serves |
| `KAYA_MAX_TEXT_CHARS` | Where prose is cut. Default `500`; `0` disables, which is what `--full` resolves to. A value that is not a whole number is a usage error naming the tier it came from |

`kaya config set --api-url …` writes the same keys to `$XDG_CONFIG_HOME/kaya/config.json` (mode
`0600`), `kaya config show` reports what resolved and from which tier, and `kaya config path` says
where the file would live — and answers even when the file's *contents* cannot be resolved, because
the verb that tells you which file to fix must not be the verb that refuses.

**`config show` never prints the token**, only `set` or `not set`. A truncated token is still a
token (Q41/Q42), so there is no prefix, no suffix and no length — the tests sweep every
four-character fragment of a fake credential out of all three formats.

A missing token is exit `1`, not `3`: nothing was refused, because nothing was asked, and a script
reacting to `3` would mint a PAT to fix a missing line of configuration. No verb ever prompts —
there is no `input()` and no tty branch anywhere in this package (ADR 0005 §contract 9), so an
unconfigured invocation behind a pipe answers instead of hanging.

## Is my build stale?

Ask it. `--version` names the commit the binary was built from, and a build that wasn't built by
the release pipeline says so rather than staying quiet:

```console
$ kaya --version
kaya 0.9.0 (a1b2c3d)                                 # a release asset, built from a1b2c3d

$ kaya --version
kaya 0.9.0 (source checkout, not a released build)   # whatever is in your working tree
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

## The failure contract (KAN-542)

Two modules, and the split between them is ADR 0004's review question answered twice.

| | Where | Why there |
|---|---|---|
| The error object and its rendering | `kaya-client` | V6's MCP adapter must report a refusal in the same shape, and would otherwise rebuild it |
| Code → exit number | `kaya-cli/src/kaya_cli/failures.py` | An MCP tool returns content to a host. It has no process to exit |

- **`failures.py`** holds [ADR 0005](../docs/adr/0005-born-agent-conformant.md) §contract 4's table —
  `0` ok · `1` runtime · `2` usage · `3` 401 · `4` 403 · `5` 404 · `6` 409 — plus `EXIT_FOR_CODE`, keyed on
  the `code` string every `KayaError` subclass carries. A raise site picks a **class**, and the class
  is the meaning; nothing in this repository writes an exit number at a raise site. The table is
  **add-only**: adding a row is free, renumbering one is breaking a published contract, and
  `tests/test_exit_codes.py` pins every shipped row by literal value so the difference is a red test.
- **`2` is the caller's input being rejected — by argparse, or by the API.** `EXIT_FOR_STATUS` maps
  `400 → 2` beside `401`/`403`/`404`, because [ADR 0008](../docs/adr/0008-note-identity.md) makes
  `kaya note get '#NOTE-12'` a `400` *by design* and the unmapped default was reporting the caller's
  own typo as exit `1`, a runtime failure a script would plausibly retry. KAN-718 added the row and
  amended ADR 0005's wording; no number moved. `invalid_note_ref` is deliberately not a row in
  `EXIT_FOR_CODE` — the status is what carries the meaning, so the next `400` code needs no edit —
  and everything the tables have no row for still exits `1`.
- **`6` is `409`: the note moved under a guarded write.** KAN-724's addition, and the first number
  this repository chose rather than inherited from pandan.
  [ADR 0009](../docs/adr/0009-optimistic-concurrency-on-note-bodies.md) puts `attempted` and `stored`
  on that refusal as two whole notes so a caller can merge and retry, and exit `1` made that
  unreachable — a script has to read `1` as "kaya failed", so it re-sends the same stale precondition
  forever or abandons a conflict it was handed everything to resolve. Not `2` either: the precondition
  was correct when it was read. `note_conflict` is not a row in `EXIT_FOR_CODE`, so the next `409`
  code needs no edit, and `422` deliberately kept the `1` default. Pandan's CLI still maps its own
  `409`s to `1`; its matching row is tracked as KAN-831.
- **`parsing.py`** intercepts `ArgumentParser.error()` and `.exit()`. argparse's default prints usage
  to stderr and calls `sys.exit(2)`, which emits nothing a program can read and takes the process
  with it. `StructuredParser` writes argparse's stderr text verbatim and then raises, so `main()`
  emits *both* halves of contract 3 — usage for a human on stderr, `error<TAB>code<TAB>message<TAB>arg`
  for a program on **stdout** — and returns a number instead of exiting from inside a parser.

The row is on stdout so an agent never has to merge two streams to find out what happened, and it
always has four tab-separated fields even when `arg` is empty: fixed arity is a positional format's
version of "all keys always present".

`--version` (KAN-543) takes the same interception: it is a plain `store_true` flag handled in
`main`, never argparse's `action="version"`, so its exit `0` is a value `main` returns rather than a
`SystemExit` raised from inside a parser.

KAN-541 hung its subparsers off `build_parser()` and passes `--format`'s resolved value into
`failures.report(..., fmt=…)`, so a `404` under `--format json` is the client's error object
unedited. The format is resolved *after* the parse and *before* the verb: a failure from the verb is
reported in the format the user asked for, and a failure from the parse is reported in `human`,
because argv never got far enough to name one.

`tests/test_failure_classes.py` proves SLICES §V2a's classes end to end — unknown flag (2), invalid
enum (2), missing token (1), 400 (2), 404 (5), 401 (3), 403 (4), 409 (6) — each asserting stream,
shape and exit code together, against an `httpx.MockTransport`. KAN-542 could only assert them at the
seam, because it had no verbs to produce one. Eight, not the six SLICES planned: the `400` is
KAN-718's and the `409` is KAN-724's. The `409`'s argv is the only one that had to be a *particular*
command — `note edit … --if-updated-at` — because it is the only refusal reachable solely through a
verb that sends a precondition.
