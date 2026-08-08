# kaya-client

The shared core. Two in-tree adapters consume it — [`kaya-cli`](../kaya-cli/) and
[`mcp`](../mcp/) — and **neither of them is allowed to shape a payload**
([ADR 0004](../docs/adr/0004-shaping-lives-in-the-shared-client.md)).

Four things live here, and the last two are small only in line count:

- **`KayaClient`** over httpx — the only thing in the suite that speaks to `/api/v1`. Its methods
  return a `Payload`, never a response body.
- **`render(payload, *, fields=None, text_limit=500, fmt="human") -> str | dict`** — the one seam.
  Four composable steps in ADR 0004's fixed order, one module each:

  ```
  projection  →  truncation  →  aggregate attachment  →  serialization
  projection.py  truncation.py  aggregates.py           serialization.py
  ```

- **`render_error(failure, *, fmt="human") -> str | dict`** — the same layer for the other half of
  the contract, because an output layer that only shapes successes is half a layer. It produces
  ADR 0005 §contract 3's `error<TAB>code<TAB>message<TAB>arg` row, or the `{"error": {…}}` object
  with `code`/`message`/`arg` always present, over the same format vocabulary.
  `error_payload(failure)` builds that object for a caller that wants the dict rather than a
  rendering; it is `backend/app/api/errors.py`'s `error_body` mirrored on this side of the wire, so
  there is one error shape to learn across HTTP, the CLI and MCP.

  Every exception class carries a `code` — `usage`, `unreachable`, `runtime`, or the API's own
  string on an `ApiError` — so a raise site names a **meaning** and the CLI's exit table is a lookup
  rather than a judgement. The table itself is not here: an MCP tool has no process to exit, so
  `kaya-cli/src/kaya_cli/failures.py` owns it. That is ADR 0004's review question ("why isn't this
  in the client?") answered honestly in both directions.

- **`version_line(program, version)`** in `provenance.py` — ADR 0007's two `--version` forms, and
  the build stamp behind them. Small, but here for the same reason as `render`: both adapters print
  provenance and neither may own the wording.

```bash
uv sync --all-extras
uv run pytest -q
uv run ruff check .
```

## What is and is not implemented

**KAN-540 (V2a) implements the `fmt` dimension only**, per ADR 0005's sequencing rule: the
signature lands before the behaviour goes inside it.

| | Today |
|---|---|
| `fmt` | User-facing: `human`, `json`. Adapter-facing: `data`. `toon` is KAN-541's and is simply not registered yet. `_ERROR_SERIALIZERS` has the same keys as `_SERIALIZERS`, pinned by a test, so a format cannot render a note list but not a `404` |
| `fields` | Accepted, shape-validated, **no-op**. Vocabulary checking is V2b |
| `text_limit` | Accepted, shape-validated, **no-op**. `0` will mean `--full` |
| `summary` | Never attached. `Shaped` already carries the slot |
| Verbs | `list_notes()`, `get_note(ref)`. The writes arrive with V2b's full verb set |

### Two format vocabularies, because two audiences

`Format` holds only what a person may type after `--format`, which makes it a published contract in
ADR 0005's sense. `AdapterFormat` holds `data`. `_SERIALIZERS` is the full registry behind both.

```python
parser.add_argument("--format", choices=list(CLI_FORMATS), default="human")
```

`CLI_FORMATS` is `tuple(fmt.value for fmt in Format)`, so the obvious line above yields exactly
SLICES §V2a's `{human,json,toon}` and can never yield `data`. That is deliberate: had `Format` held
every registered format, publishing an adapter-only value to the CLI would be the *default* outcome
of writing the obvious thing, and an early contract cannot be cheaply withdrawn. `UnknownFormat`
lists the user-facing set only, since that message reaches a shell.

`fmt="data"` is what makes the `str | dict` return type precise: it returns the shaped dict itself
and every other format returns a string. It exists so V6's MCP adapter can hand a host
`structuredContent` without `json.loads(render(..., fmt="json"))` — a shaping decision leaking out
of this package one careless line at a time. It is an argument passed in code, never a flag value.

**KAN-541 adds `toon` to both `_SERIALIZERS` and `Format`.** `test_the_published_cli_vocabulary_is_pinned`
holds a literal, so publishing a format is a conscious edit rather than a side effect of registering
one, and the tests either side of it catch a format landing in only one of the two.

If a V2b-or-later change needs to alter `render`'s signature, that is a sequencing failure, not a
reason to push through — `src/kaya_client/render.py`'s docstring argues requirement by requirement
why each of V2b's build-plan items lands on it unmoved.

## Stamping a release build

`--version` has to name a commit from inside a PyInstaller `--onefile` executable that has no
`.git` and no package index behind it, so the sha is embedded **at package time** rather than read
at runtime. The whole mechanism is one constant:

```python
# src/kaya_client/_build_stamp.py — always empty in the repository
COMMIT = ""
```

There is one stamp for the suite, not one per package, because the sha is a fact about the
repository every package is built from. It lives here because `kaya-cli` and `mcp` both depend on
this package and neither depends on the other.

A release job rewrites that constant in the checkout, immediately before packaging. Hatchling and
PyInstaller then pick the module up like any other module under `src/kaya_client/` — nothing needs
declaring as package data, and nothing needs `--add-data`:

```bash
scripts/stamp-build.sh "$GITHUB_SHA"     # rewrites COMMIT; refuses anything that isn't a sha
cd kaya-client && uv build               # or pyinstaller, for the release asset
```

**KAN-544's release gate** (ADR 0007 §2) then executes what it built and compares the **whole
line**, not just the sha:

```bash
got=$("$ARTIFACT" --version)
want="kaya ${VERSION} (${GITHUB_SHA:0:7})"
[ "$got" = "$want" ] || { echo "artifact cannot identify itself: $got"; exit 1; }
```

Comparing the whole line matters because a wrong-version-right-sha artifact is the **only** way this
mechanism can fail quietly. Every other failure prints the source-checkout wording, which any
comparison catches; a sha-only gate would wave that one through.

Three more things worth knowing before writing that workflow:

- **Stamp after the tests, before the build.** `tests/test_provenance.py::test_the_committed_stamp_is_empty`
  asserts the repository's stamp is empty, which is what stops a real sha ever being committed — a
  committed sha would make every source checkout claim to be a release of one old commit. CI
  already tested the commit; a release job does not need to test it again.
- **`[project.scripts]` entries don't exist on a `--onefile` artifact** — that is `KAN-442`, and the
  reason there is one console script and the short alias is a documented symlink.
- **A bad stamp fails safe, in both directions.** `scripts/stamp-build.sh` refuses an unexpanded
  `${GITHUB_SHA}`, a sentinel word, a non-hex string, anything under seven characters and git's
  null sha; `build_sha()` applies the same rule on the way out and resolves anything that isn't
  unmistakably a sha to `None`. The artifact then prints `(source checkout, not a released build)`
  and the gate above goes red. It never prints an empty `()` or an invented sha, because the only
  unsafe failure here is a binary claiming provenance it does not have.

### What the onefile path actually does

Measured, not reasoned. Three real PyInstaller `--onefile` binaries were built from this branch on
2026-08-09 with `HEAD` at `575e6d9` and executed. All three exited `0`:

| build | `--version` |
|---|---|
| stamped, **with** `--copy-metadata` | `kaya 0.2.0 (575e6d9)` |
| stamped, **without** `--copy-metadata` | `kaya 0.2.0 (575e6d9)` |
| **unstamped**, without | `kaya 0.2.0 (source checkout, not a released build)` |

The stamp survives the onefile path intact, and an unstamped onefile degrades to the source-checkout
form. **That third row is KAN-544's `[mutate]` fixture.** ADR 0007 §5 wants the release gate proven
by watching it fail on an artifact that cannot identify itself, and building without first running
`scripts/stamp-build.sh` produces exactly that artifact — the case does not need inventing.

An earlier draft of this section claimed PyInstaller drops the dist-info, so a build without
`--copy-metadata` would report version `0.0.0`. **That does not reproduce**: the middle row resolved
the real version. Pass `--copy-metadata kaya-notes --copy-metadata kaya-client` anyway. It costs
nothing, and the failure it insures against is *silent* — a version falling back to `0.0.0` would
still carry a valid sha and would pass a sha-only gate. That, rather than a dist-info claim that
doesn't hold, is the reason to keep the flag and the reason to compare the whole line.

## Why this package exists at all

Pandan put shaping in its CLI, so its MCP adapter inherited none of it: one `list_cards` call costs
44,902 tokens there against 2,689 for the equivalent CLI read. Kaya puts the shaping one layer down
so both adapters get it by construction. A projection or truncation rule appearing in `kaya-cli/`
or `mcp/` is a bug, not a local optimisation.

The rule has a mechanical edge here rather than a cultural one: `render` raises `TypeError` on a
raw `dict`, and `KayaClient` has no method that returns one. An adapter that wanted to shape a
payload locally would first have to unpack a `Payload` to get at the records, which is a visible
thing to do in review — unlike calling `.json()` on a response, which is not.

See also [ADR 0005](../docs/adr/0005-born-agent-conformant.md) for why the signature lands a slice
before the behaviour.
