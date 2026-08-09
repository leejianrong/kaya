# kaya-cli

The `kaya` console script. Distribution name `kaya-notes`, one entry point, two read verbs.

```bash
uv sync --all-extras
uv run kaya            # prints what it is and what hasn't landed, exits 0
uv run kaya --version  # which build is this?
uv run kaya --nope     # usage on stderr, `error<TAB>usage<TAB>…` on stdout, exits 2
uv run pytest -q
uv run ruff check .
```

## The verbs (KAN-541)

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

Reads only. `note create`, `edit`, `move` and `delete` are V2b's, and until they land they are usage
errors — a CLI that quietly accepted a verb it does not have would report success for work it never
did.

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

Two environment variables, resolved in `kaya-client`'s `config.py` so that V6's MCP server reads
exactly the same two (PLAN §Config):

| | |
|---|---|
| `KAYA_TOKEN` | A pandan PAT. **Required** — ADR 0002 gives kaya no way to mint one. Missing → `error<TAB>no_credential<TAB>…<TAB>KAYA_TOKEN` on stdout, exit `1` |
| `KAYA_API_URL` | The deployment. Defaults to `http://localhost:8000`, which is what `make up` serves |

A missing token is exit `1`, not `3`: nothing was refused, because nothing was asked, and a script
reacting to `3` would mint a PAT to fix a missing line of configuration. No verb ever prompts —
there is no `input()` and no tty branch anywhere in this package (ADR 0005 §contract 9), so an
unconfigured invocation behind a pipe answers instead of hanging.

## Is my build stale?

Ask it. `--version` names the commit the binary was built from, and a build that wasn't built by
the release pipeline says so rather than staying quiet:

```console
$ kaya --version
kaya 0.3.0 (a1b2c3d)                                 # a release asset, built from a1b2c3d

$ kaya --version
kaya 0.3.0 (source checkout, not a released build)   # whatever is in your working tree
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
  `0` ok · `1` runtime · `2` usage · `3` 401 · `4` 403 · `5` 404 — plus `EXIT_FOR_CODE`, keyed on
  the `code` string every `KayaError` subclass carries. A raise site picks a **class**, and the class
  is the meaning; nothing in this repository writes an exit number at a raise site. The table is
  **add-only**: adding a row is free, renumbering one is breaking a published contract, and
  `tests/test_exit_codes.py` pins every shipped row by literal value so the difference is a red test.
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

`tests/test_failure_classes.py` proves all six of SLICES §V2a's classes end to end — unknown flag
(2), invalid enum (2), missing token (1), 404 (5), 401 (3), 403 (4) — each asserting stream, shape
and exit code together, against an `httpx.MockTransport`. KAN-542 could only assert them at the
seam, because it had no verbs to produce one.
