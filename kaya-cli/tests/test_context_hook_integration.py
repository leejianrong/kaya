"""KAN-1201 (R18/EPIC-173, the epic's last card): a real-subprocess, real-loopback-network proof of
`context print --hook`'s soft-fail contract, closing the gap CLAUDE.md's "a structural guard does
not cover a behavioural claim, even when it reads as though it does" convention names explicitly.

`test_context.py`'s `test_hook_mode_soft_fails_with_no_token`,
`test_hook_mode_soft_fails_on_an_api_refusal` and `test_hook_mode_never_lets_any_exception_escape`
already exercise `run_hook`'s *logic* — but in-process, via `main()` called directly and (for the
API-refusal case) `hook_backend`'s `httpx.MockTransport`. Neither of those is the claim that
actually matters for a real Claude Code session: that the **literal command string** `context
install` writes into `settings.json` — run as a **real subprocess**, against a **genuinely broken
network** (not a monkeypatched exception) — truly never blocks a session and never emits anything to
stdout but a valid envelope. That is exactly the "mutate the real, installed artifact" gap a
`[mutate]` guardrail card exists to close (KAN-1201's own card body cites KAN-1085 and KAN-1069 as
the precedent), and this file is what makes the manual proof permanent.

Four real-network scenarios, each driving the exact `command` string an install would write:

* an instantly-**refused** connection (nothing listening on a real loopback port) — the everyday
  "backend isn't up" case;
* a **black-holed** address (`10.255.255.1`, probed below rather than assumed) — proves the
  `HOOK_TIMEOUT_SECONDS`/connect-timeout floor actually bounds a hang, not just a fast refusal a
  much longer, broken timeout would still clear;
* a real backend that genuinely **refuses the request** (401) — same shape as
  `test_hook_mode_soft_fails_on_an_api_refusal`, but over a real socket;
* a real, reachable backend that **succeeds** — proving the soft-fail guard is not swallowing real
  data along with real failures (the "confirm the failure names the right thing" check turned
  around, per CLAUDE.md, onto a guard that is supposed to be conditional).

`context install` itself still runs in-process (via `main()`) in each test — it is the *generation*
of the command line, not a subject of this file's "must be a real subprocess" claim, which is about
what happens when that string is executed. The subsequent execution of the extracted `command` is
always a real `subprocess.run(..., shell=True)`, matching `settings.json`'s own documented shape (a
plain shell string, per `context._hook_command`'s docstring) and how a real hook harness invokes it.
"""

from __future__ import annotations

import http.server
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from conftest import NOTES, TOKEN

from kaya_cli import context
from kaya_cli.__main__ import main

API_URL_ENV = "KAYA_API_URL"
TOKEN_ENV = "KAYA_TOKEN"


@pytest.fixture(autouse=True)
def sandbox(monkeypatch, tmp_path):
    """Same autouse fixture `test_context.py` uses: confine `claude_config_dir()` to `tmp_path` so
    the in-process `context install` call below never touches a developer's real
    `~/.claude/settings.json` or `~/.claude/skills/kaya/SKILL.md`."""
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))


def _install_hook_command(monkeypatch, tmp_path: Path, *, api_url: str) -> tuple[str, float]:
    """Run `context install` in-process (real code, real settings-file I/O — just not the part
    this file exists to prove) and return `(command, harness_timeout_seconds)` exactly as
    `settings.json` stores them: the literal string the real hook harness would execute, and the
    per-hook `timeout` `install` wrote alongside it (`HOOK_TIMEOUT_SECONDS + HOOK_TIMEOUT_MARGIN`
    by default — see `context.py`'s module docstring)."""
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    monkeypatch.setenv(API_URL_ENV, api_url)
    settings_path = tmp_path / "settings.json"
    code = main(["context", "install", "--settings", str(settings_path), "--no-skill"])
    assert code == 0, "context install itself must succeed to hand this file a real command"
    data = json.loads(settings_path.read_text())
    hook = data["hooks"]["SessionStart"][0]["hooks"][0]
    return hook["command"], float(hook["timeout"])


def _run_hook_command(command: str, *, api_url: str, token: str, outer_timeout: float):
    """Execute the literal hook `command` as a real subprocess, exactly the way a `SessionStart`
    harness would (a plain shell command string — see `context._hook_command`'s docstring).

    `outer_timeout` is **this test's own** wall-clock backstop on `subprocess.run`, independent of
    (and always looser than) the hook's own internal `--timeout`/`HOOK_TIMEOUT_MARGIN` budget — so a
    real regression that makes the hook truly hang forever is caught by pytest raising
    `TimeoutExpired` (and the test failing loudly) rather than silently trusted away.
    """
    env = dict(os.environ)
    env[TOKEN_ENV] = token
    env[API_URL_ENV] = api_url
    # `KAYA_TOKEN`/`KAYA_API_URL` win over any on-disk kaya config file the environment running
    # this test might have (kaya_client.config's documented environment-first precedence), so a
    # real config on the machine running this suite cannot leak a real token into the subprocess.
    start = time.monotonic()
    result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        timeout=outer_timeout,
        env=env,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    elapsed = time.monotonic() - start
    return result, elapsed


def _unused_port() -> int:
    """A real, currently-unused loopback port — bind then immediately close, so connecting to it
    gets a genuine `ECONNREFUSED` from the OS rather than anything mocked."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _probe_blackholes(host: str, port: int, probe_timeout: float = 1.5) -> bool:
    """Whether `(host, port)` genuinely hangs on connect rather than refusing/unreaching instantly.

    Different network environments route an unassigned address very differently — a laptop's
    default route may silently drop every packet (a true black hole), while a CI runner's docker
    bridge may reply with an immediate "network unreachable". Only the former proves anything about
    a *timeout*; asserting a timing floor against the latter would just be re-testing the instant-
    refusal path under a fancier name. So the blackhole test below probes first (mirroring the raw
    check this card's own investigation ran by hand) and skips its timeout-specific assertions,
    rather than risk becoming flaky, when this environment doesn't cooperate.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(probe_timeout)
    start = time.monotonic()
    try:
        sock.connect((host, port))
    except OSError:
        elapsed = time.monotonic() - start
        return elapsed >= probe_timeout * 0.9
    else:
        return False
    finally:
        sock.close()


# --------------------------------------------------------------------- a real fake backend


class _JSONHandler(http.server.BaseHTTPRequestHandler):
    """Real HTTP over a real loopback socket — not `httpx.MockTransport` (that fixture,
    `hook_backend` in `test_context.py`, patches `context.KayaClient` in-process and therefore never
    reaches a subprocess). Subclassed per test via `type()` so each server can answer with its own
    fixed status/body without a shared mutable handler."""

    status_code = 200
    body: dict = {}

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's naming
        payload = json.dumps(self.body).encode()
        self.send_response(self.status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib's signature
        pass  # keep the test's own stderr clean


@pytest.fixture
def fake_backend():
    """A factory fixture: `fake_backend(status, body)` starts a real HTTP server on an ephemeral
    loopback port in a background thread and returns its base URL. Torn down at test end."""
    servers: list[http.server.HTTPServer] = []

    def start(status: int, body: dict) -> str:
        handler_cls = type("_Handler", (_JSONHandler,), {"status_code": status, "body": body})
        server = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
        servers.append(server)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        port = server.server_address[1]
        return f"http://127.0.0.1:{port}"

    yield start

    for server in servers:
        server.shutdown()
        server.server_close()


# ------------------------------------------------------------------------- the four scenarios


def test_hook_subprocess_soft_fails_fast_on_a_refused_connection(monkeypatch, tmp_path) -> None:
    """The everyday case: nothing is listening. A real OS-level `ECONNREFUSED`, not a mocked
    exception, through a real subprocess running the exact command `install` wrote."""
    port = _unused_port()
    command, harness_timeout = _install_hook_command(
        monkeypatch, tmp_path, api_url=f"http://127.0.0.1:{port}"
    )

    result, elapsed = _run_hook_command(
        command, api_url=f"http://127.0.0.1:{port}", token=TOKEN, outer_timeout=harness_timeout + 20
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert "no ambient note context" in result.stderr
    assert "Traceback" not in result.stderr
    assert TOKEN not in result.stdout
    assert TOKEN not in result.stderr
    # A refused connection is a near-instant OS-level failure — bounding it well under the hook's
    # own declared harness timeout distinguishes "failed fast" from "happened to finish before our
    # backstop fired".
    assert elapsed < harness_timeout


def test_hook_subprocess_is_bounded_by_its_connect_timeout_on_a_blackholed_address(
    monkeypatch, tmp_path
) -> None:
    """The sharper case KAN-1201's own investigation called out by name: an address that silently
    drops every packet, so the OS never says "refused" — only a real connect *timeout* saves this
    from hanging. Proves `HOOK_TIMEOUT_SECONDS`'s connect cap (`min(2.0, timeout)`,
    `context.fetch_hook_block`), not just the refusal path `test_hook_subprocess_soft_fails_fast_on_
    a_refused_connection` above already covers.
    """
    blackhole_host, blackhole_port = "10.255.255.1", 65530
    if not _probe_blackholes(blackhole_host, blackhole_port):
        pytest.skip(
            f"{blackhole_host}:{blackhole_port} does not black-hole in this network environment "
            "(it refused/unreached instantly instead) -- this test needs a genuine hang to prove "
            "the connect-timeout floor; the instant-refusal path is already covered by "
            "test_hook_subprocess_soft_fails_fast_on_a_refused_connection"
        )

    command, harness_timeout = _install_hook_command(
        monkeypatch, tmp_path, api_url=f"http://{blackhole_host}:{blackhole_port}"
    )

    # `outer_timeout` is a generous backstop far above the harness's own declared timeout: if the
    # hook were to genuinely hang, `subprocess.run` raises `TimeoutExpired` here and this test fails
    # loudly, rather than the suite quietly waiting out a real regression.
    result, elapsed = _run_hook_command(
        command,
        api_url=f"http://{blackhole_host}:{blackhole_port}",
        token=TOKEN,
        outer_timeout=harness_timeout + 20,
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert "no ambient note context" in result.stderr
    assert "Traceback" not in result.stderr
    assert TOKEN not in result.stdout
    assert TOKEN not in result.stderr
    # Bounded near the hook's own budget (connect-timeout capped well under HOOK_TIMEOUT_SECONDS),
    # not merely "eventually, before our backstop" -- a few seconds of slack absorbs CI jitter
    # without weakening the proof that this is a real, enforced cap rather than an unbounded hang.
    assert elapsed <= harness_timeout + 3
    # And genuinely slow, not suspiciously instant -- confirms this run actually took the
    # connect-timeout path (the probe already established the address hangs; this is the same
    # check against the real hook subprocess rather than a bare socket).
    assert elapsed >= 1.0


def test_hook_subprocess_soft_fails_on_a_real_api_refusal(
    monkeypatch, tmp_path, fake_backend
) -> None:
    """A real, reachable backend that refuses the request (401) -- same shape as `test_context.py`'s
    `test_hook_mode_soft_fails_on_an_api_refusal`, but over a genuine socket connection to a genuine
    HTTP server, through a genuine subprocess."""
    base_url = fake_backend(401, {"error": {"code": "invalid_token", "message": "no"}})
    command, harness_timeout = _install_hook_command(monkeypatch, tmp_path, api_url=base_url)

    result, elapsed = _run_hook_command(
        command, api_url=base_url, token=TOKEN, outer_timeout=harness_timeout + 20
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert "invalid_token" in result.stderr
    assert "Traceback" not in result.stderr
    assert TOKEN not in result.stdout
    assert TOKEN not in result.stderr
    assert elapsed < harness_timeout


def test_hook_subprocess_positive_path_produces_a_real_envelope_with_real_note_data(
    monkeypatch, tmp_path, fake_backend
) -> None:
    """The other half of the proof: a genuinely reachable, correctly configured backend produces a
    real envelope with real note data -- not empty, not swallowed by the soft-fail path. A guard
    that appears to work but actually discards every real success too would be exactly the kind of
    guard CLAUDE.md's "confirm the failure names the right thing" convention exists to catch, turned
    around onto a conditional guard's *positive* side."""
    base_url = fake_backend(200, NOTES)
    command, harness_timeout = _install_hook_command(monkeypatch, tmp_path, api_url=base_url)

    result, elapsed = _run_hook_command(
        command, api_url=base_url, token=TOKEN, outer_timeout=harness_timeout + 20
    )

    assert result.returncode == 0
    assert result.stderr == ""
    lines = result.stdout.strip("\n").splitlines()
    assert len(lines) == 1, "stdout must be exactly one line -- one JSON envelope, nothing else"
    envelope = json.loads(lines[0])
    assert envelope["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    additional_context = envelope["hookSpecificOutput"]["additionalContext"]
    assert additional_context  # not empty -- the guard must not be swallowing real successes too
    assert "NOTE-12" in additional_context
    assert "Groceries" in additional_context
    assert TOKEN not in result.stdout
    assert elapsed < harness_timeout


# ------------------------------------------------------------------------------- sanity on setup


def test_hook_command_is_a_real_kaya_cli_invocation(monkeypatch, tmp_path) -> None:
    """A cheap guard on this file's own fixtures: the extracted `command` really does name this
    checkout's `kaya_cli`, so a future refactor of `_self_argv`/`_hook_command` that broke the
    generated command line in some way every other assertion here happens not to probe would still
    be caught."""
    command, _ = _install_hook_command(
        monkeypatch, tmp_path, api_url="http://127.0.0.1:1"
    )
    assert context.HOOK_SENTINEL in command
    assert sys.executable.split("/")[-1] in command or "kaya_cli" in command
