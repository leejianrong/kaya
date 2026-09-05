---
name: kaya
description: >-
  Read, write, search, and cross-link kaya notes from an agent or the command line using the `kaya`
  CLI — the primary interface — with the `mcp__kaya__*` MCP tools as a narrower fallback (MCP ⊆ CLI,
  the opposite direction from pandan). Use whenever the task is to list, read, create, edit, move,
  delete, or search markdown notes in kaya, follow or list `[[wikilinks]]`/backlinks, or wire up
  kaya's ambient SessionStart context (`kaya context`). Kaya has no login of its own — it forwards a
  pandan personal access token (ADR 0002) — so this skill is worth reading before assuming kaya needs
  its own credential.
---

# Driving kaya with the `kaya` CLI

Kaya is API-first: every action is a plain `/api/v1` REST call, and there are two thin adapters over
it, both built on the shared `kaya-client` package so projection, truncation and the summary
aggregate exist by construction rather than by being retrofitted per adapter (ADR 0004). The **`kaya`
CLI is the primary way to drive notes** — one binary or `uv tool install`, easy to shell out to,
scriptable, works in CI. The **MCP server (`mcp__kaya__*` tools) is the narrower alternative**: it
exposes six tools (`list_notes`, `get_note`, `create_note`, `edit_note`, `search_notes`,
`get_backlinks`), each one CLI verb wearing an MCP name, and nothing more. See "Known gaps" below for
what that means in practice, and `mcp/README.md` (repo root) for the test that holds the mapping
(`mcp/tests/test_cli_parity.py`) rather than a paragraph asserting it.

Prefer `kaya`. Drop to MCP only when the CLI isn't reachable, and say why when you do.

## Authentication: kaya has no login of its own

**There is no `kaya login` and no kaya-native token format** (ADR 0002). Kaya's backend resolves a
caller by forwarding the bearer it's given, unchanged, to pandan's `GET /api/v1/me` — cached on
`sha256(token)` — so **the credential kaya wants is a pandan personal access token**
(`pandan_pat_…`), the same one that drives the `pandan` CLI. One account, one set of tokens, across
both apps.

Two independent settings resolve in this precedence, each looked up on its own (KAN-541/KAN-551):

1. **Environment** — `KAYA_API_URL` (default `http://localhost:8000`, what `make up`/`make dev`
   serve) and `KAYA_TOKEN` (no default — unset is a structured `no_credential` refusal, never a
   silent guess).
2. **User config file** — `$XDG_CONFIG_HOME/kaya/config.json` (falling back to
   `~/.config/kaya/config.json`), written by `kaya config set --token … --api-url …` at mode `0600`
   and read-modify-write (a key you set by hand and `config set` doesn't know about survives).

Unlike pandan's `.mcp.json` tier, **kaya does not yet read `.mcp.json` on its own** — that third tier
is deliberately unbuilt until an MCP server key exists to read (see `kaya_client/config.py`'s module
docstring). If a project's `.mcp.json` exports `KAYA_TOKEN`/`KAYA_API_URL` into the MCP server's own
`env` block, an MCP host typically inherits that into the shell too, which is what makes the common
case work anyway — but don't assume the CLI reads the file directly the way `pandan` does.

**Treat the token as a credential you handle blind** — never `cat`/`echo`/paste the literal
`pandan_pat_…` value into a command you write. Set it once and never touch it again:

```bash
kaya config set --token "$(cat /path/to/pat)" --api-url https://your-kaya-deployment
kaya config show                      # confirms; the token prints as "set", never a value or fragment
kaya config path                      # where the file is, whether or not it exists yet
```

`kaya config set` also accepts `--token`/`--api-url` on argv, which is offered anyway (visible
briefly in `ps` and shell history) because the alternative — hand-editing JSON — is worse; `KAYA_TOKEN`
in the environment always wins over the file regardless.

Confirm the CLI works: `kaya --version` (ADR 0007 — `kaya X.Y.Z (sha)` for a release, or an explicit
`kaya X.Y.Z (source checkout, not a released build)` for a working tree; check this first if
behaviour doesn't match what you expect, per `docs/ENGINEERING_NOTES.md`'s account of the sibling
project's two false bug reports from a stale binary). Then bare `kaya` — no subcommand — prints the
build, where it's installed, and your five most recently updated notes: the fastest "does this work"
check there is.

## Reading notes

```bash
kaya note list                                  # every note you own, newest first
kaya note list --q "some search term"           # full-text over title + body, ranked (ts_rank DESC)
kaya note get NOTE-12                           # one note; note-12 and bare 12 also work (ADR 0008)
kaya note list --fields ref,title,path          # narrow columns on a list; unknown name is a clean error
kaya note get NOTE-12 --format json             # {human, json, toon}; --json is a documented alias
kaya note get NOTE-12 --full                    # no 500-char prose cut (KAYA_MAX_TEXT_CHARS overrides the default)
```

`--q` is a *search parameter*, not a client-side filter — it's forwarded verbatim to
`GET /api/v1/notes?q=…`, ranked by Postgres full-text search (`ts_rank DESC, note.id DESC` — the
`id` tie-break is load-bearing, not decoration). A present-but-blank `--q ""` is a `400
empty_search_query`, exit `2`. There is no separate "search" request shape: `note list --q TERM` and
plain `note list` return the same `NoteList` envelope, which is also why the MCP server's
`search_notes` and `list_notes` share one `KayaClient.list_notes(q)` call underneath (see "Known
gaps").

The default human row is `ref  title  path`; `--fields` widens or narrows it uniformly across every
format, and prose (`body`) is cut to 500 characters by default on any format unless `--full` is
passed or `KAYA_MAX_TEXT_CHARS` says otherwise — the cut always carries a hint naming the true total,
so nothing is silently lost from view.

## Writing notes

```bash
kaya note create "Runbook: deploy" --body "..." --path ops/deploy.md
kaya note create "Runbook: deploy" --body-file ./draft.md      # --body and --body-file are mutually exclusive
kaya note edit NOTE-12 --title "New title"
kaya note edit NOTE-12 --body "..." --if-updated-at "2026-09-01T12:00:00Z"
kaya note move NOTE-12 archive/2026/old-runbook.md
kaya note delete NOTE-12
```

**`--if-updated-at` is ADR 0009's optimistic-concurrency guard, and it is opt-in.** Read a note,
capture its `updated_at`, and echo it back on the write; if the stored value has since changed the
`PATCH` is refused with a `409` (exit `6`) carrying **both** the note you attempted to write and the
note as currently stored, so a caller can diff and retry rather than guessing what changed. Omit the
flag and the write is a plain last-write-wins overwrite — that's the documented behaviour, not a gap.
**The guard applies only when the request carries `body`** — a title/path-only edit (including `note
move`, which is sugar over `edit --path`) is unguarded LWW even with a stale precondition supplied,
because a rename doesn't conflict with anything ADR 0009 is about. There is no `--force`: an unguarded
write is simply a write with no precondition attached, not a second flag pretending to override one.

`note delete` has no `--yes` and no confirmation prompt of any kind (ADR 0005 §contract 9) — every
verb in this CLI answers with stdin closed, so treat the ref you pass as final. A note's `ref` is
never reused after deletion; a later read of it is a `404` forever.

## Wikilinks and backlinks

Kaya parses `[[…]]` out of a note's body on save into a `note_link` edge table — one row per link,
recording what kind of target it names and whether it resolved:

- **`[[Some Note Title]]`** resolves against another note you own, by title, matched at save time (or
  reconciled later if the target didn't exist yet — creating the target note afterward links it up
  without editing the source again).
- **`[[KAN-123]]` / `[[EPIC-45]]`** resolves against a **pandan** card or epic, using your own token,
  by a bounded list sweep over the board rather than a per-ref round trip (spike 0001 found there's no
  pandan endpoint that would accept a ticket ref directly, so this scales with board size, not with
  how many `[[KAN-n]]` refs a note has).
- **A link that can't be resolved renders as unresolved, never as an error** (ADR 0003) — pandan being
  down, a card that doesn't exist, or a note title with no match all degrade the same way. Kaya never
  blocks a note save, render, or search on pandan being reachable; this is the one place that
  tolerance is visible from the CLI.
- **A backlink is found by the resolved id, never by title-matching a string** — rename the target
  note and existing links to it keep working, because the edge stores `resolved_id`, not the string
  that was typed.

```bash
kaya links NOTE-12       # this note's outbound [[wikilinks]], resolved where possible
kaya backlinks NOTE-12   # every note whose body links to this one
```

`links` returns edge records (what's targeted, and — for NOTE-kind targets — the resolved ref/title;
`null`s for anything unresolved). `backlinks` is worth knowing as a shortcut rather than a separate
concept: it answers with the exact same note-list shape `note list` does (so `--fields`, `--full`,
and the trailing count aggregate all apply to it for free), and — unlike `links`, which may cross to
pandan — **`backlinks` never leaves kaya's own database**, so it answers correctly even with pandan
stopped cold.

## Ambient session context (`kaya context`)

This skill is itself one half of R18 (`EPIC-173`): the other half is a Claude Code `SessionStart`
hook that gives a fresh agent session your recent notes before it has to ask.

```bash
kaya context install     # idempotent: wires the hook into ~/.claude/settings.json (or --settings PATH)
kaya context status      # is the hook installed? is a token configured? is this skill up to date?
kaya context uninstall   # removes exactly the hook entries (and skill copy) this tool installed
kaya context print       # what the hook shows, through the normal --format/--fields/--full pipeline
```

`install` refuses to touch `settings.json` at all when `KAYA_TOKEN` isn't configured — set your
token first (see Authentication above), then install. The hook itself (`kaya context print --hook`)
runs on every session start/resume/clear/compact/fork, has its own short timeout independent of the
client's normal cold-start-tolerant budget, and **never blocks a session and never prints anything but
one valid JSON envelope** — a failure is a line on stderr the harness discards, never a fabricated
"you have no notes" reaching the model's context. If `kaya context status` reports the installed
skill copy as stale or locally modified, re-run `kaya context install --force-skill` to refresh it (or
pass `--no-skill`/`--keep-skill` to opt a single install/uninstall out of touching the skill file at
all).

## Errors and exit codes

Failures print a structured row on stdout, never stderr prose: `error<TAB>code<TAB>message<TAB>arg`
under `human`, or `{"error": {"code","message","arg","status","exit_code"}}` under `json`/`toon`.
Branch on `code`, never on message text.

| Exit | Meaning |
|---|---|
| `0` | ok |
| `1` | runtime — kaya failed, or an unmapped status (retrying blindly is not obviously safe) |
| `2` | usage — a bad flag, or the API rejected the request shape (`400`, `422`) |
| `3` | `401` — the token is missing, malformed, or rejected |
| `4` | `403` — the token is fine, the answer is still no |
| `5` | `404` — nothing there, whatever spelling of the ref you used |
| `6` | `409` — ADR 0009's stale-precondition refusal; re-read, merge, retry |

Rows are added, never renumbered — a script that branches on `$?` keeps working across releases.

## Known gaps (MCP ⊆ CLI — the opposite direction from pandan)

**Do not write "full parity" about this relationship — it's the wrong shape entirely, and
`mcp/README.md` (repo root) is the one canonical place that states it.** Kaya's MCP surface is
*frozen narrow by design* (ADR 0006): six tools, one per read/write verb that has no CLI-only side
effect, and the direction is deliberately CLI ⊇ MCP so the MCP server stays a thing that can be
deleted without losing capability elsewhere. This is the inverse of pandan, whose `MCP ⊇ CLI` grew
four MCP-only capabilities that made the surface hard to retire.

What that means for an agent picking a tool:

- **CLI-only, no MCP tool at all:** `note move`, `note delete`, `kaya links` (the outbound,
  possibly-pandan-crossing read — only `get_backlinks`/`kaya backlinks` has an MCP twin),
  `note export`/`note import`/`export-all`/`import-all`, everything under `kaya config`, and all of
  `kaya context`. An MCP-driven agent cannot move or delete a note, or install its own ambient
  context — those need a shell.
- **One MCP tool for two CLI spellings:** `search_notes` and `list_notes` are the same
  `KayaClient.list_notes(q)` call; there is no separate "search" tool because there is no separate
  search request on the wire (see "Reading notes" above).
- **The MCP schemas are compacted** (ADR 0006 §3 — stripped generated `title` annotations, collapsed
  nullable unions), which changes what a host is *told* about a tool's shape, never what the tool
  *accepts* — that's asserted by `mcp/tests/test_schema_compaction.py`, not by this bullet.

If the CLI isn't installed or errors for an environment reason (not a 4xx), fall back to
`mcp__kaya__*`. If a CLI verb is genuinely missing an MCP twin you need, that's not a bug to route
around silently — say so, the way this section does, rather than reaching for a raw HTTP call.

## Example workflow

```bash
kaya note list --q "deploy runbook"
kaya note get NOTE-41
kaya note edit NOTE-41 --body "$(cat updated.md)" --if-updated-at "2026-09-01T09:00:00Z"
kaya backlinks NOTE-41     # who else references this note, before you rename or delete it
```
