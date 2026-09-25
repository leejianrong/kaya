"""R18/KAN-1198: `kaya context {install,uninstall,status,print}`. KAN-1200 adds the packaged skill.

Ported the *ideas* worth porting from pandan's own `pandan-cli/tests/test_context.py` (idempotent
install, an exact uninstall, unrelated settings keys surviving both, a malformed `hooks` key
refused rather than overwritten, a hook mode that never raises, and — for KAN-1200 — the packaged
skill's own idempotent install/uninstall and its KAN-505-style stamp/compare provenance tests) —
adapted to kaya's own LOCAL_VERBS/VERBS split, its `main()`-level dispatch for `--hook`, and its
`Payload`-record shape (extra dict fields folded into the hook's record, rather than pandan's own
list of printed lines), not copied verbatim.

`fetch_hook_block` deliberately never goes through `kaya_client.config.open_client` (see
`kaya_cli.context`'s module docstring for why), so the `answering`/`fake_api` fixtures in
`conftest.py` — which patch `kaya_cli.verbs.open_client` — do not reach it. `hook_backend` below is
the equivalent seam for the hook's own short-lived `KayaClient`.

**Every test in this file runs against a `CLAUDE_CONFIG_DIR` inside `tmp_path`** (the `sandbox`
autouse fixture below) — mirroring pandan's own autouse fixture of the same name. This became load
-bearing the moment `_install_skill`/`_uninstall_skill` started doing real filesystem work:
`context.skill_target_path()` is derived from `claude_config_dir()` directly, independent of
whatever `--settings PATH` a test passes for the *hook* half, so without this fixture every
`context install`/`uninstall` test below would read and write the developer's real
`~/.claude/skills/kaya/SKILL.md`.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

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


@pytest.fixture(autouse=True)
def sandbox(monkeypatch, tmp_path):
    """Confine every `claude_config_dir()`-relative read/write (the packaged skill's target path)
    to `tmp_path` — without this, `_install_skill`/`_uninstall_skill` would touch a developer's real
    `~/.claude/skills/kaya/SKILL.md` the moment any test in this file calls `context install` or
    `context uninstall`."""
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))


@pytest.fixture
def settings_path(tmp_path):
    return tmp_path / "settings.json"


@pytest.fixture
def packaged_skill(tmp_path, monkeypatch):
    """Point `context.packaged_skill_path()` at a small, known-content fixture file rather than this
    repo's real `SKILL.md` — the provenance tests below are about the stamp/compare mechanism, not
    about this skill's prose, and a fixture file makes every assertion about "the packaged body"
    independent of that prose ever changing."""
    source = tmp_path / "packaged-skill.md"
    source.write_text("---\nname: kaya\ndescription: test fixture\n---\n\n# kaya skill (fixture)\n")
    monkeypatch.setattr(context, "packaged_skill_path", lambda: source)
    return source


@pytest.fixture
def our_build(monkeypatch):
    """Freeze `context.__version__` / `context.build_sha()` so `compare_skill`'s provenance
    behaviour can be driven at any build skew without a real stamped binary — the same
    monkeypatch-the-module-attribute pattern `hook_backend` already uses for `context.KayaClient`.
    `sha=""` means a source checkout (`build_sha()` returns `None`, matching the real function's
    contract)."""

    def set_build(version: str, sha: str = "") -> None:
        monkeypatch.setattr(context, "__version__", version)
        monkeypatch.setattr(context, "build_sha", lambda: sha or None)

    return set_build


def _stamp_text(version: str, sha: str = "") -> str:
    """A stamp line for an arbitrary `(version, sha)`, independent of the current build — used to
    plant a skill on disk as though some *other* build had installed it."""
    detail = sha or context.SOURCE_CHECKOUT
    return f"{context.SKILL_STAMP_PREFIX}{version} ({detail}){context.SKILL_STAMP_SUFFIX}"


def _install_stamped(target: Path, body: str, version: str, sha: str = "") -> Path:
    """Put a skill on disk stamped as if a build `version` had laid it down."""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body.rstrip("\n") + "\n" + _stamp_text(version, sha) + "\n", encoding="utf-8")
    return target


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


# =================================================================== KAN-1200: the packaged skill


def test_the_skill_is_packaged_in_the_repo() -> None:
    """KAN-434's trap: a card looks done in-repo while its out-of-repo half is unshipped. The repo
    carries the real skill (not the `packaged_skill` fixture's stand-in), so the installer has
    something to distribute."""
    packaged = context.packaged_skill_path()
    assert packaged is not None and packaged.is_file()
    text = packaged.read_text(encoding="utf-8")
    assert text.startswith("---\nname: kaya\n")
    assert "kaya" in text


def test_install_lays_down_the_skill_at_the_right_path(
    monkeypatch, settings_path, packaged_skill
) -> None:
    """The skill lands under `$CLAUDE_CONFIG_DIR/skills/kaya/SKILL.md` — the kaya-shaped equivalent
    of pandan's own `Path("skills") / "pandan" / "SKILL.md"` install target."""
    _configure(monkeypatch)
    target = context.skill_target_path()
    assert target == context.claude_config_dir() / "skills" / "kaya" / "SKILL.md"

    code = main(["context", "install", "--settings", str(settings_path), "--format", "json"])

    assert code == 0
    assert target.is_file()
    packaged = packaged_skill.read_bytes()
    # Since KAN-1200's stamp, the installed copy carries a trailing build stamp, so it is
    # deliberately *not* byte-identical to the packaged one — but its body is, which is the
    # comparison everything else is made on.
    assert target.read_bytes() != packaged
    assert context.strip_stamp(target.read_bytes()) == context.strip_stamp(packaged)
    assert context.parse_stamp(target.read_text())[0] == context.__version__


def test_install_and_uninstall_the_skill_is_a_round_trip(
    monkeypatch, settings_path, packaged_skill
) -> None:
    _configure(monkeypatch)
    target = context.skill_target_path()

    assert main(["context", "install", "--settings", str(settings_path)]) == 0
    assert target.is_file()

    # Uninstall removes exactly the file this tool installed, and nothing it didn't: the
    # `--settings`-addressed hook file is untouched by the skill's own removal.
    assert main(["context", "uninstall", "--settings", str(settings_path)]) == 0
    assert not target.exists()
    # And it did not touch the settings file's own directory beyond the hook keys.
    assert settings_path.exists()


def test_install_is_idempotent_for_the_skill_too(
    monkeypatch, capsys, settings_path, packaged_skill
) -> None:
    _configure(monkeypatch)
    main(["context", "install", "--settings", str(settings_path)])
    target = context.skill_target_path()
    before = target.read_bytes()
    before_mtime = target.stat().st_mtime_ns
    capsys.readouterr()

    code = main(["context", "install", "--settings", str(settings_path), "--format", "json"])
    printed = json.loads(capsys.readouterr().out)

    assert code == 0
    assert target.read_bytes() == before
    assert target.stat().st_mtime_ns == before_mtime
    assert printed["skill"] == "up to date"


def test_install_does_not_clobber_an_unstamped_skill_but_does_not_call_it_edited(
    monkeypatch, capsys, settings_path, packaged_skill
) -> None:
    """An unstamped copy predates this mechanism (or is hand-written). It is never clobbered
    without `--force-skill`, but the *reason* given is honest: with no stamp, local edits and a
    different build are indistinguishable."""
    _configure(monkeypatch)
    target = context.skill_target_path()
    target.parent.mkdir(parents=True)
    target.write_text("my own notes")

    code = main(["context", "install", "--settings", str(settings_path), "--format", "json"])
    printed = json.loads(capsys.readouterr().out)

    assert code == 0
    assert target.read_text() == "my own notes"
    assert "differs from this build; no build stamp" in printed["skill"]
    assert "locally modified)" not in printed["skill"]
    assert "pass --force-skill" in printed["skill"]

    code = main(
        [
            "context",
            "install",
            "--settings",
            str(settings_path),
            "--force-skill",
            "--format",
            "json",
        ]
    )
    assert code == 0
    assert context.strip_stamp(target.read_bytes()) == context.strip_stamp(
        packaged_skill.read_bytes()
    )


def test_uninstall_never_deletes_a_locally_edited_skill(
    monkeypatch, settings_path, packaged_skill, capsys
) -> None:
    target = context.skill_target_path()
    target.parent.mkdir(parents=True)
    target.write_text("my own notes")

    code = main(["context", "uninstall", "--settings", str(settings_path), "--format", "json"])
    printed = json.loads(capsys.readouterr().out)

    assert code == 0
    assert target.read_text() == "my own notes"
    assert "kept (locally modified" in printed["skill"]


def test_no_skill_and_keep_skill_opt_out(
    monkeypatch, settings_path, packaged_skill, capsys
) -> None:
    _configure(monkeypatch)
    target = context.skill_target_path()

    code = main(
        ["context", "install", "--settings", str(settings_path), "--no-skill", "--format", "json"]
    )
    printed = json.loads(capsys.readouterr().out)
    assert code == 0
    assert not target.exists()
    assert printed["skill"] == "skipped (--no-skill)"

    main(["context", "install", "--settings", str(settings_path)])
    capsys.readouterr()
    code = main(
        [
            "context",
            "uninstall",
            "--settings",
            str(settings_path),
            "--keep-skill",
            "--format",
            "json",
        ]
    )
    printed = json.loads(capsys.readouterr().out)
    assert code == 0
    assert target.is_file()
    assert printed["skill"] == "kept (--keep-skill)"


def test_context_status_reports_the_skill_state(
    monkeypatch, settings_path, packaged_skill, capsys
) -> None:
    code = main(["context", "status", "--settings", str(settings_path), "--format", "json"])
    printed = json.loads(capsys.readouterr().out)
    assert code == 0
    assert printed["skill"] == "not installed"

    _configure(monkeypatch)
    main(["context", "install", "--settings", str(settings_path)])
    capsys.readouterr()

    code = main(["context", "status", "--settings", str(settings_path), "--format", "json"])
    printed = json.loads(capsys.readouterr().out)
    assert code == 0
    assert printed["skill"] == "installed (matches this build)"
    assert printed["skill_path"] == str(context.skill_target_path())


# --- skill provenance: stale-vs-current detection (mirrors pandan's own KAN-505 mechanism) -------
#
# The bug this mechanism exists to kill: comparing an installed skill against *the build you
# invoked it with* and calling any difference "locally modified". A user one release behind would
# be told they have edits they never made — and "locally modified" is the state that points at
# `--force-skill`, which would DOWNGRADE their skill. So the tests below come in pairs: every
# assertion that a new state *fires* is matched by one that it does **not** fire in the neighbouring
# state.


def test_status_reports_a_stale_binary_and_never_invites_the_downgrade(
    settings_path, packaged_skill, capsys
) -> None:
    _install_stamped(context.skill_target_path(), "# not this build's copy", "99.0.0")

    code = main(["context", "status", "--settings", str(settings_path), "--format", "json"])
    printed = json.loads(capsys.readouterr().out)

    assert code == 0
    assert "installed copy is NEWER than this build" in printed["skill"]
    assert "your binary is stale" in printed["skill"]
    # "do NOT pass --force-skill" itself contains the substring "pass --force-skill", so the
    # negative assertion has to name the fuller, only-ever-safe-to-offer phrase.
    assert "pass --force-skill to overwrite it with this build's copy" not in printed["skill"]
    assert "do NOT pass --force-skill" in printed["skill"]
    assert "installed (locally modified)" not in printed["skill"]


def test_status_reports_a_genuinely_edited_skill_as_locally_modified(
    our_build, settings_path, packaged_skill, capsys
) -> None:
    """The pairing for the test above: when the stamp names *this exact* build, a differing body
    really is a hand edit, and the confident wording (plus the --force-skill invitation) is
    correct."""
    our_build("1.2.3", "aaaaaaa")
    _install_stamped(context.skill_target_path(), "# I edited this myself", "1.2.3", "aaaaaaa")

    code = main(["context", "status", "--settings", str(settings_path), "--format", "json"])
    printed = json.loads(capsys.readouterr().out)

    assert code == 0
    assert printed["skill"] == (
        "installed (locally modified) — pass --force-skill to overwrite it with this build's copy"
    )
    assert "NEWER than this build" not in printed["skill"]


def test_status_reports_an_older_build_copy_as_stale_not_as_local_edits(
    settings_path, packaged_skill, capsys
) -> None:
    _install_stamped(context.skill_target_path(), "# an older build's copy", "0.0.1")

    code = main(["context", "status", "--settings", str(settings_path), "--format", "json"])
    printed = json.loads(capsys.readouterr().out)

    assert code == 0
    assert "installed (from an older build 0.0.1, or locally modified)" in printed["skill"]
    assert "--force-skill" in printed["skill"]
    assert "your binary is stale" not in printed["skill"]


def test_status_degrades_honestly_with_no_stamp_at_all(
    settings_path, packaged_skill, capsys
) -> None:
    """The migration case, and the one that can never be fixed retroactively: a copy installed
    before this mechanism existed has no stamp, so the direction is genuinely unknowable. It must
    say so rather than pick a side."""
    target = context.skill_target_path()
    target.parent.mkdir(parents=True)
    target.write_text("# laid down by some build, no stamp\n")

    code = main(["context", "status", "--settings", str(settings_path), "--format", "json"])
    printed = json.loads(capsys.readouterr().out)

    assert code == 0
    assert "no build stamp" in printed["skill"]
    assert "indistinguishable" in printed["skill"]
    assert "installed (locally modified)" not in printed["skill"]
    assert "NEWER than this build" not in printed["skill"]
    assert "older build" not in printed["skill"]


def test_install_refuses_to_downgrade_a_newer_skill_without_offering_force_skill(
    monkeypatch, settings_path, packaged_skill, capsys
) -> None:
    _configure(monkeypatch)
    target = _install_stamped(context.skill_target_path(), "# from a newer build", "99.0.0")
    before = target.read_bytes()

    code = main(["context", "install", "--settings", str(settings_path), "--format", "json"])
    printed = json.loads(capsys.readouterr().out)

    assert code == 0
    assert target.read_bytes() == before  # untouched
    assert "left alone — installed copy is NEWER than this build" in printed["skill"]
    assert "laid down by 99.0.0" in printed["skill"]
    assert "pass --force-skill" not in printed["skill"]
    assert "re-download the release" in printed["skill"]


def test_force_skill_labels_a_downgrade_instead_of_doing_it_silently(
    monkeypatch, settings_path, packaged_skill, capsys
) -> None:
    """`--force-skill` stays an escape hatch — refusing it outright would leave no way back to an
    older skill — but the downgrade is now announced, never silent."""
    _configure(monkeypatch)
    target = _install_stamped(context.skill_target_path(), "# from a newer build", "99.0.0")

    code = main(
        [
            "context",
            "install",
            "--settings",
            str(settings_path),
            "--force-skill",
            "--format",
            "json",
        ]
    )
    printed = json.loads(capsys.readouterr().out)

    assert code == 0
    assert context.strip_stamp(target.read_bytes()) == context.strip_stamp(
        packaged_skill.read_bytes()
    )
    assert "WARNING: this DOWNGRADED the skill" in printed["skill"]


def test_uninstall_removes_a_stamped_but_unmodified_copy_yet_keeps_an_edited_one(
    monkeypatch, settings_path, packaged_skill, capsys
) -> None:
    _configure(monkeypatch)
    main(["context", "install", "--settings", str(settings_path)])
    capsys.readouterr()

    code = main(["context", "uninstall", "--settings", str(settings_path), "--format", "json"])
    printed = json.loads(capsys.readouterr().out)
    assert code == 0
    assert not context.skill_target_path().exists()
    assert printed["skill"] == "removed"

    target = _install_stamped(
        context.skill_target_path(), "# I edited this myself", context.__version__
    )
    code = main(["context", "uninstall", "--settings", str(settings_path), "--format", "json"])
    printed = json.loads(capsys.readouterr().out)
    assert code == 0
    assert target.is_file()
    assert "kept (locally modified or unknown build)" in printed["skill"]


# --- the stamp itself ------------------------------------------------------------------------


def test_the_stamp_is_an_inert_trailing_comment_not_frontmatter(packaged_skill) -> None:
    """A SKILL.md is consumed as agent instructions, so the stamp must not change how it reads. It
    is an HTML comment (inert in Markdown, carries no imperative) on the **last** line — never a
    frontmatter key, since the frontmatter is the harness's own metadata contract."""
    packaged = context.packaged_skill_path().read_bytes()
    stamped = context._stamped(packaged)
    text = stamped.decode("utf-8")

    assert text.startswith("---\nname: kaya\n")
    assert context.strip_stamp(stamped) == packaged

    last = text.rstrip("\n").rsplit("\n", 1)[-1]
    assert last.startswith("<!--") and last.endswith("-->")
    assert "\n" not in last
    assert context.parse_stamp(packaged.decode("utf-8")) is None
    assert text.count(context.SKILL_STAMP_PREFIX) == 1
    assert context._stamped(stamped) == stamped


def test_stamp_round_trips_and_ignores_version_shaped_prose() -> None:
    """The skill's own body documents `--version` output, so it genuinely contains version-shaped
    text. Only the last line may be read as provenance."""
    body = "# skill\n`kaya --version` prints `kaya 0.7.0 (bd28cf0)`.\n"
    assert context.parse_stamp(body) is None
    assert context.strip_stamp(body.encode()) == body.encode()

    stamped = body + _stamp_text("1.2.3", "deadbee") + "\n"
    assert context.parse_stamp(stamped) == ("1.2.3", "deadbee")
    assert context.strip_stamp(stamped.encode()).decode() == body

    source = body + _stamp_text("1.2.3", "") + "\n"
    assert context.parse_stamp(source) == ("1.2.3", "")


@pytest.mark.parametrize(
    "installed_version,installed_sha,ours,our_sha,expected",
    [
        # Same version AND same commit: a differing body can only be a hand edit.
        ("1.2.3", "aaaaaaa", "1.2.3", "aaaaaaa", context.SKILL_MODIFIED),
        # Same version, different commit: direction unknowable, must not read as an edit.
        ("1.2.3", "aaaaaaa", "1.2.3", "bbbbbbb", context.SKILL_UNKNOWN),
        ("1.3.0", "aaaaaaa", "1.2.3", "aaaaaaa", context.SKILL_NEWER),
        ("1.2.3", "aaaaaaa", "1.3.0", "aaaaaaa", context.SKILL_OLDER),
        ("2.0.0", "", "1.9.9", "", context.SKILL_NEWER),
        # An unparseable version is never given an invented ordering.
        ("1.2.3rc1", "aaaaaaa", "1.2.3", "aaaaaaa", context.SKILL_UNKNOWN),
    ],
)
def test_compare_skill_only_claims_a_direction_it_can_prove(
    our_build, installed_version, installed_sha, ours, our_sha, expected
) -> None:
    our_build(ours, our_sha)
    installed = (
        b"# installed body\n" + _stamp_text(installed_version, installed_sha).encode() + b"\n"
    )

    state, detail = context.compare_skill(installed, b"# a different body\n")

    assert state == expected
    assert detail == installed_version


def test_compare_skill_handles_absent_and_unbundled_and_undecodable_copies() -> None:
    packaged = b"# body\n"
    assert context.compare_skill(None, packaged)[0] == context.SKILL_ABSENT
    assert context.compare_skill(packaged, None)[0] == context.SKILL_NO_PACKAGED
    # A mangled file must be a comparison result, never a traceback out of `status`.
    assert context.compare_skill(b"\xff\xfe not utf-8", packaged)[0] == context.SKILL_UNKNOWN
