"""R18/KAN-1198: ambient session context — a Claude Code `SessionStart` hook that gives an agent
session the caller's recent notes before it has to ask for them, mirroring pandan V48/KAN-431's own
`pandan_cli/context.py` (1084 lines, read in full before this was written) and adapted to kaya's
shapes rather than copied.

`kaya context install` wires the hook into a `settings.json`; `kaya context print --hook` is what
that hook actually runs.

Verified hook contract (docs + the shipped schema, not inferred — the same verification pandan's own
module docstring did, re-read here rather than re-derived)
--------------------------------------------------------------------------------------------------
* Event name is **``SessionStart``**, in the ``hooks`` propertyNames enum of
  ``claude-code-settings.schema.json`` and documented at https://code.claude.com/docs/en/hooks as
  "When a session begins or resumes".
* Config shape is ``{"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": …,
  "timeout": …}]}]}}``. Only ``type`` + ``command`` are required on a hook entry and ``timeout`` is
  a number of seconds; ``matcher`` is optional and we omit it — a freshly compacted session needs
  the ambient block at least as much as a new one, so the hook fires on every source (``startup`` /
  ``resume`` / ``clear`` / ``compact`` / ``fork``).
* **stdout on exit 0 reaches the model**, as ``{"hookSpecificOutput": {"hookEventName":
  "SessionStart", "additionalContext": …}}`` — the docs are explicit that this is parsed and added
  as context Claude can see and act on.
* A ``SessionStart`` hook cannot block the session but it *is* awaited, so it can delay one, and the
  default command-hook timeout is 600 seconds.

Why the soft-fail path is the design, and why kaya's timeout tension is sharper than pandan's
--------------------------------------------------------------------------------------------------
Pandan's own reason is a free-tier board API that scales to zero. Kaya's is a **documented, load-
bearing invariant of its own client**: ``kaya_client.client.DEFAULT_READ_TIMEOUT`` is 40 seconds,
deliberately generous enough to outlast the backend's own ~35 s cold-start authentication budget
(KAN-716, `backend/tests/unit/test_client_deadline_outlasts_auth.py`). That number is *right* for an
interactive command a person is willing to wait on once. It is exactly wrong for a `SessionStart`
hook, which runs on every session and must never make a human wait through a cold pandan
introspection just to see five notes. So this module never opens a session through
`kaya_client.config.open_client` (which always applies that 40 s budget) — `print --hook` builds
its own short-lived `KayaClient` with a small, hook-specific timeout (`HOOK_TIMEOUT_SECONDS`,
below), and:

* it never exits non-zero and never prints anything to stdout but a valid envelope. A failure is one
  line on stderr, discarded by the hook harness's exit 0 — an error row on stdout would otherwise be
  injected into the model's context as fake ambient state, which is worse than no context at all;
* `install` writes an explicit ``timeout`` into the hook entry, a small margin above the budget this
  module itself enforces, so a wedged process is capped by the harness in seconds rather than the
  600 s default.

Everything below that returns a ``Payload`` (`cmd_install`, `cmd_uninstall`, `cmd_status`,
`cmd_print`) goes through `kaya_cli.verbs`' ordinary dispatch tables and is rendered by
`kaya_cli.__main__.main`'s one `render()` call, same as every other verb (ADR 0005 §contract 1:
every verb gets `--format`/`--fields`/`--full`). `run_hook` is the one function that does not — it
is called directly from `main`, before `verbs.run`, exactly where `--version` already is, precisely
so `context print --hook` can opt out of the CLI's normal "structured error on stdout" contract the
way pandan's own `show --hook` opts out of its `_emit`. See that function's docstring.

Naming: `context print`, not `context show` (the card's own guess, and pandan's actual spelling)
--------------------------------------------------------------------------------------------------
`mcp/tests/test_cli_parity.py`'s `declared_flags` reader keys every `add_parser` call in
`kaya_cli/__main__.py` on its bare word alone, and asserts that word is used exactly once in the
whole file — a guard pandan has no equivalent of. Kaya already has `config show`, so a second
subcommand spelled `show` (this card's own instruction, mirroring pandan's `context show`) would
trip that assertion the moment any MCP parity test parses the parser. `print` is the next word in
this codebase's own vocabulary for "put this on stdout" (`--version`'s help already reads "print
this build's version") and carries the same meaning with no collision.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import tempfile
from pathlib import Path
from typing import Any

import httpx
from kaya_client import RECENT_NOTES, KayaClient, MissingCredential, Payload, UsageError
from kaya_client.config import TOKEN_SET, TOKEN_UNSET, api_url, token

PROG = "kaya"
"""The one console script (ADR 0007 §4, Q39) — spelled again here rather than imported from
`kaya_cli.__main__`, which would import this module in turn (`__main__` dispatches `--hook` here
directly). Two literal constants naming one fixed thing is cheaper than a cycle."""

HOOK_EVENT = "SessionStart"
"""Verified against the shipped settings schema's `hooks` propertyNames enum — a typo here would
silently never fire."""

HOOK_TIMEOUT_SECONDS = 5.0
"""The wall-clock budget for the hook's **own** API call — independent of, and far below,
`kaya_client.client.DEFAULT_READ_TIMEOUT` (40 s). See this module's docstring for why that number is
right for an interactive command and wrong for a `SessionStart` hook: a hook trades completeness for
never making a human wait, so a cold kaya backend simply yields no ambient block that session rather
than hanging one. Five seconds is generous against the warm path (kaya's own measured round trip is
low hundreds of milliseconds, per `kaya_client.client`'s own docstring) and short against a person's
patience at the start of a session."""

HOOK_TIMEOUT_MARGIN = 2.0
"""Extra seconds handed to the harness-level `timeout` on top of `HOOK_TIMEOUT_SECONDS`, so the two
caps cannot race: this module's own budget should always fire first, and the harness's is the
backstop for a process that is wedged rather than merely slow."""

DEFAULT_NOTE_LIMIT = RECENT_NOTES
"""How many notes the ambient block carries by default — the same `RECENT_NOTES` bare `kaya` already
uses (KAN-549's "orientation, not a listing" argument applies here unchanged), so a fresh session's
hook and a fresh session's first bare invocation show the same slice for the same reason."""

HOOK_SENTINEL = "context print --hook"
"""The substring that identifies a hook entry as **ours**, in any settings file. `_hook_command`
always appends these three tokens verbatim (`shlex.quote` is a no-op on bare tokens), so matching a
fragment of our own command line is what makes `install` idempotent and `uninstall` exact — a custom
marker key is not used because the settings schema requires only `type`/`command`, and a marker key
is not guaranteed to survive a hand round-trip of the file the way this text is."""


# --- paths -------------------------------------------------------------------------------------


def claude_config_dir() -> Path:
    """The Claude Code config directory: `$CLAUDE_CONFIG_DIR` if set, else `~/.claude`. Honouring
    the env var is what lets a test point every read/write at a tmp dir instead of a developer's
    real config."""
    base = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    return Path(base) if base else Path.home() / ".claude"


def settings_path() -> Path:
    """The user-level settings file the hook is installed into by default."""
    return claude_config_dir() / "settings.json"


def _settings_arg(args: argparse.Namespace) -> Path:
    raw = getattr(args, "settings", None)
    return Path(raw).expanduser() if raw else settings_path()


# --- settings file I/O ---------------------------------------------------------------------------
#
# Named `read_claude_settings`/`write_claude_settings` rather than `read_settings`/`write_settings`,
# deliberately: `kaya_client.config` already owns those two names for kaya's *own* config.json, and
# this module's settings file is Claude Code's, a completely different document with a completely
# different shape. A shared name across two unrelated files in the same process is the kind of
# collision that reads fine in a diff and confuses the next person stepping through it.


def read_claude_settings(path: Path) -> dict[str, Any]:
    """Parse a settings file, or `{}` when it doesn't exist.

    A file that exists but doesn't parse is a hard refusal, never an implicit `{}`: writing over it
    would silently destroy every unrelated setting (other hooks, permissions, MCP servers) the user
    has. That is the one irreversible thing an installer could do, so it is the one thing this
    function does not do quietly.
    """
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise UsageError(f"cannot read {path}: {exc}", arg=str(path)) from exc
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise UsageError(
            f"{path} is not valid JSON ({exc}) — fix or move it first; refusing to overwrite a "
            "settings file kaya cannot parse",
            arg=str(path),
        ) from exc
    if not isinstance(data, dict):
        raise UsageError(
            f"{path} does not contain a JSON object — refusing to overwrite it", arg=str(path)
        )
    return data


def write_claude_settings(path: Path, data: dict[str, Any]) -> None:
    """Write `data` as pretty JSON, atomically, preserving the file's mode.

    Atomic because a half-written `settings.json` is a broken Claude Code: the temp file is created
    in the *same* directory (so `os.replace` is a rename within one filesystem) and swapped in one
    step.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else None
    payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".settings-", suffix=".json")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        if mode is not None:
            tmp.chmod(mode)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _session_start_groups(settings: dict[str, Any]) -> list[Any]:
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return []
    groups = hooks.get(HOOK_EVENT)
    return groups if isinstance(groups, list) else []


def _is_ours(hook: Any) -> bool:
    """Whether a hook object in a settings file was installed by us."""
    return (
        isinstance(hook, dict)
        and isinstance(hook.get("command"), str)
        and HOOK_SENTINEL in hook["command"]
    )


def find_installed(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """Every hook object in `settings` that we installed (usually 0 or 1; more if a hand edit
    duplicated it, which `cmd_install` then collapses)."""
    found: list[dict[str, Any]] = []
    for group in _session_start_groups(settings):
        if not isinstance(group, dict):
            continue
        for hook in group.get("hooks") or []:
            if _is_ours(hook):
                found.append(hook)
    return found


def _strip_ours(settings: dict[str, Any]) -> int:
    """Remove our hook objects in place, pruning containers we emptied but **only** those we
    emptied. Returns how many were removed.

    This is what makes uninstall *clean*: a settings file that had nothing but our hook comes back
    byte-identical to one that never had it, so install → uninstall is a true round trip.
    """
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return 0
    groups = hooks.get(HOOK_EVENT)
    if not isinstance(groups, list):
        return 0

    removed = 0
    surviving_groups: list[Any] = []
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
            surviving_groups.append(group)
            continue
        kept = [hook for hook in group["hooks"] if not _is_ours(hook)]
        removed += len(group["hooks"]) - len(kept)
        if not kept:
            # The group existed only to hold our hook — drop it. A group that had other hooks keeps
            # them (and its matcher).
            continue
        group["hooks"] = kept
        surviving_groups.append(group)

    if surviving_groups:
        hooks[HOOK_EVENT] = surviving_groups
    else:
        hooks.pop(HOOK_EVENT, None)
    if not hooks:
        settings.pop("hooks", None)
    return removed


# --- the hook entry ------------------------------------------------------------------------------


def _self_argv() -> list[str]:
    """How to re-invoke *this* kaya, as an argv prefix.

    A frozen onefile (PyInstaller, KAN-544, ADR 0007) is its own executable; a source/venv/`uv run`
    invocation is `<python> -m kaya_cli`. This never reaches for a bare `kaya` on `$PATH` — "the
    hook runs the same kaya you installed it with" is both the honest promise and the debuggable
    one. `--exec` overrides it for anyone who wants otherwise.
    """
    if getattr(sys, "frozen", False):  # pragma: no cover - only true inside a PyInstaller build
        return [sys.executable]
    return [sys.executable, "-m", "kaya_cli"]


def _fmt_seconds(value: float) -> str:
    """`5.0` -> `"5"`, `2.5` -> `"2.5"` — so the generated command line reads like something a
    person would have typed."""
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def _hook_command(argv_prefix: list[str], *, timeout: float, limit: int) -> str:
    """The shell command string the hook entry runs.

    A plain `command` string, not the schema's newer `args` exec-form: every Claude Code version
    understands the string form, and `shlex.quote` already makes a path with spaces safe. The three
    sentinel tokens land verbatim (quoting a bare token is a no-op), which is what `_is_ours` relies
    on.
    """
    parts = [
        *argv_prefix,
        "context",
        "print",
        "--hook",
        "--timeout",
        _fmt_seconds(timeout),
        "--limit",
        str(limit),
    ]
    return " ".join(shlex.quote(part) for part in parts)


def hook_entry(*, command: str, timeout: float) -> dict[str, Any]:
    """One `SessionStart` hook object. `matcher` is omitted (fires for every session source) and
    the harness `timeout` is our own budget plus a margin, so our bound trips first and the 600 s
    default never applies."""
    return {
        "type": "command",
        "command": command,
        "timeout": round(timeout + HOOK_TIMEOUT_MARGIN, 3),
    }


# --- config resolution ---------------------------------------------------------------------------


def _resolved_config() -> tuple[str, str]:
    """`(api_url, token)`, or `MissingCredential` naming what to set.

    Only the token can be genuinely unset — `kaya_client.config.api_url` always has a local default
    (`make up`'s `:8000`), so unlike pandan's board+token pair, kaya's "is anything configured?"
    question is one check. `cmd_install` calls this *before* `_settings_arg`/`read_claude_settings`,
    so an unconfigured caller's `.claude/settings.json` is never opened, let alone written.
    """
    return api_url(), token()


def _has_token() -> bool:
    try:
        token()
    except MissingCredential:
        return False
    return True


# --- the ambient block ----------------------------------------------------------------------------


def render_hook_block(payload: Payload, *, limit: int) -> str:
    """The hook's plain-text ambient block, from the same `recent_notes` `Payload` bare `kaya`
    renders.

    A **separate renderer** from `kaya_client.overview`/`render` — this text has to become one
    `additionalContext` string with no reliance on `render()` at all (see this module's docstring on
    why `run_hook` bypasses it), so it does its own small formatting rather than reusing the
    four-step pipeline. Mirrors pandan's own `render_block` (`pandan_cli/context.py`) being a
    separate function from its CLI's `_emit`, for the identical reason.

    Plain text, not JSON: it is read by a model, and a short tab-separated row per note is the
    cheapest shape this repo already uses for a list (ADR 0005 §contract 2's default row).
    """
    records = payload.records
    lines = [f"{PROG} — recent notes (from `{PROG} context print`):"]
    if not records:
        lines.append("no notes yet")
    else:
        lines.append(f"{len(records)} most recently updated, newest first (ref / title / path):")
        for record in records:
            ref = record.get("ref")
            title = str(record.get("title") or "").replace("\n", " ").strip()
            path = str(record.get("path") or "")
            row = f"{ref}\t{title}"
            if path:
                row += f"\t{path}"
            lines.append(row)
    lines.append(
        f"showing up to {limit} notes — `{PROG} note list` shows all of them. This is a "
        "point-in-time snapshot, not a live view — re-read before acting on it."
    )
    return "\n".join(lines)


def fetch_hook_block(*, limit: int, timeout: float) -> str:
    """Resolve config and make **one** bounded API call, then render the block.

    Builds its own `KayaClient` rather than going through `kaya_client.config.open_client` — that
    seam always applies `DEFAULT_TIMEOUT` (40 s), the number this module's docstring explains is
    wrong for a session hook. `connect` is capped separately and tighter than `timeout` itself
    (mirroring `kaya_client.client.DEFAULT_CONNECT_TIMEOUT`'s own reasoning): a blackholed host
    should fail fast rather than spend the whole hook budget finding out nothing is listening.
    `KayaClient` makes no retries (`client.py`'s own docstring: "nothing retries today"), so there
    is no second request to budget for the way pandan's halved timeout accounts for
    `PandanClient`'s one retry.
    """
    base_url, bearer = _resolved_config()
    budget = httpx.Timeout(timeout, connect=min(2.0, timeout))
    with KayaClient(base_url, bearer, timeout=budget) as client:
        payload = client.recent_notes(limit)
    return render_hook_block(payload, limit=limit)


def hook_envelope(text: str) -> dict[str, Any]:
    """The verified `SessionStart` JSON output form. `additionalContext` is the field the docs name
    for adding context on this event."""
    return {"hookSpecificOutput": {"hookEventName": HOOK_EVENT, "additionalContext": text}}


# --- command handlers -------------------------------------------------------------------------


def run_hook(args: argparse.Namespace) -> int:
    """`kaya context print --hook` — what the installed `SessionStart` hook actually runs.

    **This is the one function in `kaya-cli` that does not go through `render()`/`failures.report`,
    and it never raises past this point.** Every other verb's failure is a structured
    `error<TAB>code<TAB>message<TAB>arg` row on stdout and a looked-up exit code — exactly the
    contract a hook must not use: `SessionStart`'s stdout on exit 0 is parsed and injected into the
    model's context, so a `no_credential` row there would read as fabricated ambient state, which is
    strictly worse than no ambient block at all. So a failure here is one line on stderr (discarded
    by the harness on exit 0) and **nothing at all on stdout** — not even an empty envelope,
    matching pandan's own `cmd_show`'s hook-mode branch exactly.

    `main` calls this directly, before `verbs.run`, the same place `--version` is handled — never
    through the `VERBS`/`LOCAL_VERBS` tables, because those feed `render()` and `report()`, both of
    which this verb must bypass entirely.
    """
    try:
        text = fetch_hook_block(limit=args.limit, timeout=args.timeout)
    except BaseException as exc:  # noqa: BLE001 - the whole point is to never let one escape
        # `str(exc)` is safe to print: every `KayaError` this can raise (`MissingCredential`,
        # `TransportError`, `ApiError`, `UsageError`) is built under the same no-bearer-in-a-message
        # rule `kaya_client.errors` documents, so there is nothing here for stderr to leak.
        print(
            f"kaya: no ambient note context this session ({type(exc).__name__}: {exc})",
            file=sys.stderr,
        )
        return 0
    print(json.dumps(hook_envelope(text), ensure_ascii=False))
    return 0


def cmd_print(client: KayaClient, args: argparse.Namespace) -> Payload:
    """`kaya context print` (no `--hook`) — the recent-notes payload, through the normal pipeline.

    Returns `client.recent_notes(args.limit)`: the exact call bare `kaya` already makes, so this
    adds no second query shape (BREADBOARD.md's own fit-check) — the only difference from a bare
    invocation is that this one prints without the banner and, unlike `--hook`, gets the full
    `--format`/`--fields`/`--full` contract every other verb has (ADR 0005 §contract 1), which
    `--hook` mode deliberately cannot: its output has to be exactly one JSON envelope, whatever
    `--format` says.
    """
    return client.recent_notes(args.limit)


_HOOK_COLUMNS = (
    "status",
    "settings",
    "event",
    "budget_seconds",
    "hook_timeout_seconds",
    "command",
)


def cmd_install(args: argparse.Namespace) -> Payload:
    """`kaya context install` — add (or update) the `SessionStart` hook. Idempotent by construction:
    the entry is built deterministically from the flags, so a second run with the same flags finds a
    byte-identical entry and writes nothing at all. Changed flags rewrite the single entry (and
    collapse any duplicate a hand edit left behind) rather than appending another.

    **Config is resolved before the settings file is touched.** `_resolved_config()` raises
    `MissingCredential` for an unset `KAYA_TOKEN`, and that propagates straight out to `main`'s
    normal `KayaError` funnel — so an unconfigured `kaya context install` is provably a no-op: the
    settings file is never opened, let alone written, exactly as pandan's own `cmd_install` calls
    `_resolved_board()` before `_settings_arg`/`read_settings`.
    """
    _resolved_config()

    path = _settings_arg(args)
    argv_prefix = [args.exec] if getattr(args, "exec", None) else _self_argv()
    command = _hook_command(argv_prefix, timeout=args.timeout, limit=args.limit)
    desired = hook_entry(command=command, timeout=args.timeout)

    settings = read_claude_settings(path)
    existing = find_installed(settings)
    already = len(existing) == 1 and existing[0] == desired

    if already:
        status = "already installed"
    else:
        _strip_ours(settings)
        hooks = settings.setdefault("hooks", {})
        if not isinstance(hooks, dict):
            raise UsageError(
                f'{path} has a non-object "hooks" key — refusing to overwrite it', arg=str(path)
            )
        groups = hooks.setdefault(HOOK_EVENT, [])
        if not isinstance(groups, list):
            raise UsageError(
                f'{path} has a non-array "hooks.{HOOK_EVENT}" key — refusing to overwrite it',
                arg=str(path),
            )
        groups.append({"hooks": [desired]})
        write_claude_settings(path, settings)
        status = "updated" if existing else "installed"

    record: dict[str, Any] = {
        "status": status,
        "settings": str(path),
        "event": HOOK_EVENT,
        "command": command,
        "budget_seconds": args.timeout,
        "hook_timeout_seconds": desired["timeout"],
    }
    record.update(_install_skill(args))
    return Payload.entity(noun="hook", envelope_key="hook", record=record, columns=_HOOK_COLUMNS)


def cmd_uninstall(args: argparse.Namespace) -> Payload:
    """`kaya context uninstall` — remove the hook. Idempotent: with nothing of ours present, the
    settings file is not written at all (so it isn't even created, and its mtime doesn't move).

    **Deliberately does not require kaya to be configured** — no call to `_resolved_config()` here.
    Pandan's own `cmd_uninstall` makes the identical choice for the identical reason ("you must
    always be able to undo this"): a token can be revoked or removed between `install` and
    `uninstall`, and the one command that undoes an install must keep working when the thing it is
    undoing no longer has a credential behind it. (The card's own sketch described install,
    uninstall and status as uniformly gated on configuration; this is a deliberate correction, noted
    in this PR's description, once pandan's own reasoning here was read closely.)
    """
    path = _settings_arg(args)
    settings = read_claude_settings(path)
    removed = _strip_ours(settings)
    if removed:
        write_claude_settings(path, settings)

    record: dict[str, Any] = {"removed": removed, "settings": str(path)}
    record.update(_uninstall_skill(args))
    return Payload.entity(
        noun="hook", envelope_key="hook", record=record, columns=("removed", "settings")
    )


def cmd_status(args: argparse.Namespace) -> Payload:
    """`kaya context status` — read-only: is the hook installed, and would it have anything to say?
    The affordance that makes an idempotent installer checkable without running it. Needs no
    configuration either, for the same reason `cmd_uninstall` doesn't: reporting "token: not set" is
    exactly the case this verb exists to answer honestly.
    """
    path = _settings_arg(args)
    installed = find_installed(read_claude_settings(path))
    hook = installed[0] if installed else None

    record = {
        "settings": str(path),
        "hook": "installed" if installed else "not installed",
        "command": hook.get("command") if hook else None,
        "timeout": hook.get("timeout") if hook else None,
        "token": TOKEN_SET if _has_token() else TOKEN_UNSET,
        "api_url": api_url(),
    }
    return Payload.entity(
        noun="hook",
        envelope_key="hook",
        record=record,
        columns=("settings", "hook", "command", "timeout", "token", "api_url"),
    )


# --- extension point for KAN-1200 (packaged skill) ---------------------------------------------
#
# Pandan's own `cmd_install`/`cmd_uninstall` call `_install_skill`/`_uninstall_skill` as one more
# step after the hook write, laying down `pandan_cli/skills/pandan/SKILL.md` beside it. Kaya ships
# no skill file yet — `kaya-cli/skills/kaya/SKILL.md` is KAN-1200, a separate card — so these are
# deliberately empty for now. They exist so KAN-1200 only has to fill them in, exactly where
# pandan's equivalent calls already sit in its own `cmd_install`/`cmd_uninstall`, rather than
# re-wiring either command.


def _install_skill(args: argparse.Namespace) -> dict[str, Any]:
    """Extra record fields `cmd_install` folds in after laying down (or refusing to touch) a
    packaged skill. Returns `{}` until KAN-1200 gives this something to do."""
    return {}


def _uninstall_skill(args: argparse.Namespace) -> dict[str, Any]:
    """`_install_skill`'s uninstall-side counterpart. Returns `{}` until KAN-1200."""
    return {}


# --- argument validation, shared with __main__'s parser wiring ------------------------------------


def positive_seconds(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected a number of seconds, got {raw!r}") from exc
    if not 0 < value <= 60:
        raise argparse.ArgumentTypeError(
            f"--timeout must be > 0 and <= 60 seconds (a session hook is awaited), got {raw!r}"
        )
    return value


def positive_limit(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected an integer, got {raw!r}") from exc
    if not 0 < value <= 200:
        raise argparse.ArgumentTypeError(f"--limit must be between 1 and 200, got {raw!r}")
    return value
