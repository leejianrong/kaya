"""R18/KAN-1198: `kaya context {install,uninstall,status,print}`.

Ported the *ideas* worth porting from pandan's own `pandan-cli/tests/test_context.py` (idempotent
install, an exact uninstall, unrelated settings keys surviving both, a malformed `hooks` key
refused rather than overwritten, and a hook mode that never raises) — adapted to kaya's own
LOCAL_VERBS/VERBS split and its `main()`-level dispatch for `--hook`, not copied verbatim.

`fetch_hook_block` deliberately never goes through `kaya_client.config.open_client` (see
`kaya_cli.context`'s module docstring for why), so the `answering`/`fake_api` fixtures in
`conftest.py` — which patch `kaya_cli.verbs.open_client` — do not reach it. `hook_backend` below is
the equivalent seam for the hook's own short-lived `KayaClient`.
"""

import json
import os
import subprocess
import sys

import httpx
import pytest
from conftest import NOTES, TOKEN
from kaya_client import KayaClient

from kaya_cli import context
from kaya_cli.__main__ import main

BASE_URL = "https://kaya.example"


def _configure(monkeypatch, base_url: str = BASE_URL) -> None:
    monkeypatch.setenv("KAYA_TOKEN", TOKEN)
    monkeypatch.setenv("KAYA_API_URL", base_url)


@pytest.fixture
def settings_path(tmp_path):
    return tmp_path / "settings.json"


@pytest.fixture
def hook_backend(monkeypatch):
    """A fake backend for `context.fetch_hook_block`'s own `KayaClient` — the one construction path
    `verbs.open_client` (and therefore `answering`/`fake_api`) never reaches, by design."""
    seen: list[httpx.Request] = []

    def install(status: int, body: dict) -> list[httpx.Request]:
        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(status, json=body)

        def fake_client(base_url: str, bearer: str, *, timeout=None, client=None) -> KayaClient:
            return KayaClient(
                base_url, bearer, client=httpx.Client(transport=httpx.MockTransport(handler))
            )

        monkeypatch.setattr(context, "KayaClient", fake_client)
        return seen

    return install


# ----------------------------------------------------------------- install: the config gate


def test_install_is_a_no_op_when_unconfigured(capsys, settings_path) -> None:
    """`context install` must never touch `.claude/settings.json` when no token is configured —
    the settings file is not even opened, let alone written."""
    code = main(["context", "install", "--settings", str(settings_path)])

    assert code == 1
    assert capsys.readouterr().out.startswith("error\tno_credential\t")
    assert not settings_path.exists()


def test_install_writes_the_hook_when_configured(monkeypatch, settings_path) -> None:
    _configure(monkeypatch)
    code = main(["context", "install", "--settings", str(settings_path)])

    assert code == 0
    data = json.loads(settings_path.read_text())
    groups = data["hooks"]["SessionStart"]
    assert len(groups) == 1
    hook = groups[0]["hooks"][0]
    assert hook["type"] == "command"
    assert "matcher" not in groups[0]
    assert context.HOOK_SENTINEL in hook["command"]


# ------------------------------------------------------------------------------ idempotency


def test_install_is_idempotent(monkeypatch, settings_path) -> None:
    """A second install with the same flags is a byte-identical no-op: same content, same mtime."""
    _configure(monkeypatch)
    main(["context", "install", "--settings", str(settings_path)])
    before_text = settings_path.read_text()
    before_mtime = settings_path.stat().st_mtime_ns

    code = main(["context", "install", "--settings", str(settings_path)])

    assert code == 0
    assert settings_path.read_text() == before_text
    assert settings_path.stat().st_mtime_ns == before_mtime


def test_changed_flags_rewrite_the_single_entry_not_a_second_one(
    monkeypatch, settings_path
) -> None:
    _configure(monkeypatch)
    main(["context", "install", "--settings", str(settings_path), "--limit", "5"])
    main(["context", "install", "--settings", str(settings_path), "--limit", "10"])

    groups = json.loads(settings_path.read_text())["hooks"]["SessionStart"]
    assert len(groups) == 1
    assert len(groups[0]["hooks"]) == 1
    assert "--limit 10" in groups[0]["hooks"][0]["command"]


# ------------------------------------------------------------------ read-modify-write safety


def test_an_unrelated_hooks_block_survives_install_and_uninstall(
    monkeypatch, settings_path
) -> None:
    original = {
        "permissions": {"allow": ["Bash(git status)"]},
        "hooks": {
            "SessionStart": [{"hooks": [{"type": "command", "command": "echo unrelated"}]}],
            "PreToolUse": [{"hooks": [{"type": "command", "command": "echo pre-tool"}]}],
        },
    }
    settings_path.write_text(json.dumps(original))
    _configure(monkeypatch)

    assert main(["context", "install", "--settings", str(settings_path)]) == 0
    after_install = json.loads(settings_path.read_text())
    assert after_install["permissions"] == original["permissions"]
    assert after_install["hooks"]["PreToolUse"] == original["hooks"]["PreToolUse"]
    session_start_hooks = [
        hook for group in after_install["hooks"]["SessionStart"] for hook in group["hooks"]
    ]
    assert {"type": "command", "command": "echo unrelated"} in session_start_hooks
    assert any(context.HOOK_SENTINEL in hook.get("command", "") for hook in session_start_hooks)

    assert main(["context", "uninstall", "--settings", str(settings_path)]) == 0
    assert json.loads(settings_path.read_text()) == original


def test_a_malformed_hooks_key_is_refused_not_overwritten(monkeypatch, settings_path) -> None:
    settings_path.write_text(json.dumps({"hooks": "not an object"}))
    _configure(monkeypatch)

    code = main(["context", "install", "--settings", str(settings_path)])

    assert code == 2
    assert json.loads(settings_path.read_text()) == {"hooks": "not an object"}


def test_uninstall_removes_exactly_the_matching_entries(monkeypatch, settings_path) -> None:
    _configure(monkeypatch)
    main(["context", "install", "--settings", str(settings_path)])

    code = main(["context", "uninstall", "--settings", str(settings_path)])

    assert code == 0
    data = json.loads(settings_path.read_text())
    assert "hooks" not in data


def test_uninstall_with_nothing_installed_does_not_create_the_file(settings_path) -> None:
    code = main(["context", "uninstall", "--settings", str(settings_path)])

    assert code == 0
    assert not settings_path.exists()


def test_uninstall_needs_no_configuration(settings_path) -> None:
    """Deliberately no `_configure` — undoing an install must keep working with no token set, the
    same "you must always be able to undo this" reasoning pandan's own `cmd_uninstall` states."""
    code = main(["context", "uninstall", "--settings", str(settings_path)])

    assert code == 0


def test_status_needs_no_configuration(capsys, settings_path) -> None:
    code = main(["context", "status", "--settings", str(settings_path), "--format", "json"])

    assert code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["hook"] == "not installed"
    assert printed["token"] == "not set"


def test_status_reports_an_installed_hook_and_a_set_token(
    monkeypatch, capsys, settings_path
) -> None:
    _configure(monkeypatch)
    main(["context", "install", "--settings", str(settings_path)])
    capsys.readouterr()  # discard install's own output

    code = main(["context", "status", "--settings", str(settings_path), "--format", "json"])
    printed = json.loads(capsys.readouterr().out)

    assert code == 0
    assert printed["hook"] == "installed"
    assert printed["token"] == "set"
    assert context.HOOK_SENTINEL in printed["command"]


# --------------------------------------------------------------------------------- hook mode


def test_hook_mode_prints_a_valid_envelope_and_exits_zero(
    monkeypatch, capsys, hook_backend
) -> None:
    _configure(monkeypatch)
    hook_backend(200, NOTES)

    code = main(["context", "print", "--hook"])
    out = capsys.readouterr().out

    assert code == 0
    envelope = json.loads(out)
    assert envelope["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "NOTE-12" in envelope["hookSpecificOutput"]["additionalContext"]


def test_hook_mode_soft_fails_with_no_token(capsys) -> None:
    """No `_configure` at all — the unconfigured case, and the most likely real-world failure."""
    code = main(["context", "print", "--hook"])
    captured = capsys.readouterr()

    assert code == 0
    assert captured.out == ""
    assert "no ambient note context" in captured.err
    assert TOKEN not in captured.err


def test_hook_mode_soft_fails_on_an_api_refusal(monkeypatch, capsys, hook_backend) -> None:
    _configure(monkeypatch)
    hook_backend(401, {"error": {"code": "invalid_token", "message": "no"}})

    code = main(["context", "print", "--hook"])
    captured = capsys.readouterr()

    assert code == 0
    assert captured.out == ""
    assert "invalid_token" in captured.err


def test_hook_mode_never_lets_any_exception_escape(monkeypatch, capsys) -> None:
    """`run_hook` catches `BaseException`, not just `Exception` — so even a class that is not a
    `KayaError` at all still exits 0 with nothing on stdout. `--hook` mode's whole contract is that
    stdout is either one valid envelope or completely silent, never a traceback."""

    def boom(*, limit, timeout):
        raise RuntimeError("boom")

    monkeypatch.setattr(context, "fetch_hook_block", boom)

    code = main(["context", "print", "--hook"])
    captured = capsys.readouterr()

    assert code == 0
    assert captured.out == ""
    assert "boom" in captured.err


def test_plain_print_goes_through_the_normal_render_pipeline(capsys, answering) -> None:
    """Without `--hook`, `context print` gets `--format`/`--fields`/`--full` like every other verb —
    the contract `--hook` mode cannot have, since its output must be exactly one JSON envelope."""
    answering(200, NOTES)

    code = main(["context", "print", "--fields", "ref", "--format", "json"])
    printed = json.loads(capsys.readouterr().out)

    assert code == 0
    assert printed["notes"] == [{"ref": "NOTE-12"}, {"ref": "NOTE-3"}]


# ------------------------------------------------------------------- never prompts, never hangs


@pytest.mark.parametrize(
    "argv",
    [
        ["context", "install"],
        ["context", "uninstall"],
        ["context", "status"],
        ["context", "print"],
        ["context", "print", "--hook"],
    ],
)
def test_context_verbs_answer_with_stdin_closed(argv: list[str], tmp_path) -> None:
    """The same structural guard `tests/test_no_prompting.py` runs for every other verb, extended to
    the four new ones. `CLAUDE_CONFIG_DIR` is redirected to a tmp dir so a bare `context
    uninstall`/`status` — which take no `--settings` here — cannot reach a developer's real
    `~/.claude/settings.json`."""
    env = dict(os.environ)
    env["CLAUDE_CONFIG_DIR"] = str(tmp_path)
    env.pop("KAYA_TOKEN", None)
    env.pop("KAYA_API_URL", None)

    result = subprocess.run(
        [sys.executable, "-m", "kaya_cli", *argv],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=15,
        env=env,
        check=False,
    )

    assert result.returncode in (0, 1, 2)
