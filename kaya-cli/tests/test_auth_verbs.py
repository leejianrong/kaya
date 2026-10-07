"""`auth {login,logout,status}` end to end (ADR 0013, KAN-1743).

Unlike `test_config_verbs.py`'s subject, `auth login` talks to the network — but not through
`KayaClient`/`open_client` (there is no token yet to build one with). The seam under test is
`kaya_client.request_device_code`/`poll_once`, imported into `kaya_cli.verbs` by name, so this file
patches them there — the same `monkeypatch.setattr(verbs, "open_client", …)` shape
`conftest.py`'s own docstring documents for the note verbs, applied to a different pair of names.
`verbs.webbrowser.open` is patched in every test that reaches `login`, so no test ever launches a
real browser; `verbs.time.sleep` is patched to a no-op recorder so no test really waits.
"""

import json
import os
from pathlib import Path

import pytest
from kaya_client import DeviceCode, DeviceLoginDenied, DeviceLoginExpired, MintedToken, config

from kaya_cli import verbs
from kaya_cli.__main__ import main

CODE = DeviceCode(
    device_code="a-device-secret",
    user_code="WDJB-MJHT",
    verification_uri="https://kaya.example/device",
    verification_uri_complete="https://kaya.example/device?user_code=WDJB-MJHT",
    expires_in=900,
    interval=5,
)


def config_file() -> Path:
    return config.config_path(os.environ)


def stored() -> dict:
    return json.loads(config_file().read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def no_real_browser_or_sleep(monkeypatch):
    """Every test in this file reaches `login`'s interactive loop, so both side effects are patched
    unconditionally rather than per-test — the failure mode of forgetting one is a real browser tab
    or a real multi-second wait in CI, not a wrong assertion."""
    monkeypatch.setattr(verbs.webbrowser, "open", lambda url: True)
    monkeypatch.setattr(verbs.time, "sleep", lambda seconds: None)


def poll_sequence(monkeypatch, *results):
    """Patch `poll_once` to return each of `results` in order, one per call."""
    remaining = list(results)

    def fake(api_url, device_code):
        return remaining.pop(0)

    monkeypatch.setattr(verbs, "poll_once", fake)


def minted(scope: str = "write", token: str = "kaya_pat_secret") -> MintedToken:
    return MintedToken(token=token, token_prefix="kaya_pat_ab12", scope=scope)


def patch_request_device_code(monkeypatch, code: DeviceCode = CODE):
    seen: list[tuple[str, str]] = []

    def fake(api_url, scope):
        seen.append((api_url, scope))
        return code

    monkeypatch.setattr(verbs, "request_device_code", fake)
    return seen


def test_login_prints_the_link_and_code(monkeypatch, capsys) -> None:
    patch_request_device_code(monkeypatch)
    poll_sequence(monkeypatch, minted())

    status = main(["auth", "login"])

    out = capsys.readouterr().out
    assert status == 0
    assert CODE.verification_uri_complete in out
    assert CODE.user_code in out


def test_login_opens_a_browser_with_the_full_link(monkeypatch, capsys) -> None:
    opened: list[str] = []
    monkeypatch.setattr(verbs.webbrowser, "open", lambda url: opened.append(url) or True)
    patch_request_device_code(monkeypatch)
    poll_sequence(monkeypatch, minted())

    main(["auth", "login"])

    assert opened == [CODE.verification_uri_complete]


def test_login_stores_the_minted_token_in_the_config_file(monkeypatch, capsys) -> None:
    patch_request_device_code(monkeypatch)
    poll_sequence(monkeypatch, minted(token="kaya_pat_the_secret"))

    main(["auth", "login"])

    assert stored()["token"] == "kaya_pat_the_secret"


def test_login_never_prints_the_raw_minted_token(monkeypatch, capsys) -> None:
    patch_request_device_code(monkeypatch)
    poll_sequence(monkeypatch, minted(token="kaya_pat_super_secret_value"))

    main(["auth", "login"])

    out = capsys.readouterr().out
    assert "kaya_pat_super_secret_value" not in out
    assert "set" in out, "config set's own token row: `set`, never a fragment"


def test_login_keeps_polling_through_pending_before_success(monkeypatch, capsys) -> None:
    patch_request_device_code(monkeypatch)
    poll_sequence(monkeypatch, "pending", "pending", minted())

    status = main(["auth", "login"])

    assert status == 0
    assert stored()["token"] == "kaya_pat_secret"


def test_login_widens_the_interval_on_slow_down(monkeypatch, capsys) -> None:
    patch_request_device_code(monkeypatch)
    poll_sequence(monkeypatch, "slow_down", minted())
    slept: list[float] = []
    monkeypatch.setattr(verbs.time, "sleep", lambda seconds: slept.append(seconds))

    main(["auth", "login"])

    assert slept == [CODE.interval, CODE.interval + 5], (
        "RFC 8628: a slow_down must widen every subsequent poll's interval, not just the next one"
    )


def test_login_denied_is_a_runtime_failure_not_a_written_token(monkeypatch, capsys) -> None:
    patch_request_device_code(monkeypatch)

    def fake(api_url, device_code):
        raise DeviceLoginDenied("the device-flow login was denied")

    monkeypatch.setattr(verbs, "poll_once", fake)

    status = main(["auth", "login"])

    assert status == 1
    assert "error\tdevice_login_denied\t" in capsys.readouterr().out
    assert not config_file().exists(), "a denied login must not write a config file at all"


def test_login_expired_is_a_runtime_failure(monkeypatch, capsys) -> None:
    patch_request_device_code(monkeypatch)

    def fake(api_url, device_code):
        raise DeviceLoginExpired("the device-flow login code expired")

    monkeypatch.setattr(verbs, "poll_once", fake)

    status = main(["auth", "login"])

    assert status == 1
    assert "error\tdevice_login_expired\t" in capsys.readouterr().out


def test_login_requests_the_scope_flag_was_given(monkeypatch, capsys) -> None:
    seen = patch_request_device_code(monkeypatch)
    poll_sequence(monkeypatch, minted(scope="read"))

    main(["auth", "login", "--scope", "read"])

    assert seen[0][1] == "read"


def test_login_defaults_to_write_scope(monkeypatch, capsys) -> None:
    seen = patch_request_device_code(monkeypatch)
    poll_sequence(monkeypatch, minted())

    main(["auth", "login"])

    assert seen[0][1] == "write"


def test_login_needs_no_token_configured_to_start(monkeypatch, capsys) -> None:
    """The chicken-and-egg case `login` exists to solve: it must run with nothing configured at
    all, unlike every `VERBS` row which would raise `MissingCredential` first."""
    assert config.TOKEN_ENV not in os.environ
    patch_request_device_code(monkeypatch)
    poll_sequence(monkeypatch, minted())

    status = main(["auth", "login"])

    assert status == 0


def test_logout_removes_a_stored_token(capsys) -> None:
    config.write_settings({config.TOKEN_ENV: "kaya_pat_something"})

    status = main(["auth", "logout"])

    assert status == 0
    assert "token" not in stored()


def test_logout_when_never_logged_in_is_not_an_error(capsys) -> None:
    assert not config_file().exists()

    status = main(["auth", "logout"])

    assert status == 0


def test_status_reports_not_set_with_nothing_configured(capsys) -> None:
    status = main(["auth", "check", "--json"])

    assert status == 0
    body = json.loads(capsys.readouterr().out)
    assert body == {"key": "token", "value": "not set", "source": "unset"}


def test_status_reports_set_after_a_token_is_stored(capsys) -> None:
    config.write_settings({config.TOKEN_ENV: "kaya_pat_something"})

    status = main(["auth", "check", "--json"])

    assert status == 0
    body = json.loads(capsys.readouterr().out)
    assert body["value"] == "set"
    assert body["source"] == "file"
