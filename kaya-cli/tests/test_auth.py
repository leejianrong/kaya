"""`kaya auth {login,logout,me}` (ADR 0013, KAN-1743) — RFC 8628 device-flow login, and the two
ordinary verbs beside it.

`auth me`/`auth logout` go through the same `answering`/`fake_api`/local-verb machinery every
other verb in this package does — nothing here is special-cased for them. `auth login` is: it never
opens a `KayaClient` at all (both device-flow calls are unauthenticated by RFC 8628's own design),
so its own tests patch `kaya_cli.auth.create_device_code`/`poll_device_token` directly, plus
`time.sleep` (no test should actually wait) and `webbrowser.open` (no test should actually try to
open one).

`me` rather than the more obvious `status` — see `kaya_cli.verbs.ME`'s own docstring: `status` is
already an `add_parser` word under `context`, and `mcp/tests/test_cli_parity.py`'s reader refuses
two verbs sharing a bare word.
"""

import time
import webbrowser

import pytest
from kaya_client import config

from kaya_cli import auth
from kaya_cli.__main__ import main

ME_BODY = {"id": "abc-123", "email": "alice@example.com"}


# --- auth me -------------------------------------------------------------------------------------


def test_auth_me_calls_the_me_endpoint(capsys, answering) -> None:
    seen = answering(200, ME_BODY)
    code = main(["auth", "me"])

    assert code == 0
    assert [(r.method, r.url.path) for r in seen] == [("GET", "/api/v1/me")]
    assert "abc-123" in capsys.readouterr().out


def test_auth_me_with_no_token_is_exit_1(capsys) -> None:
    """`no_credential` is exit `1`, not `3` — nothing was refused because nothing was asked, the
    same distinction every other verb in this package draws."""
    code = main(["auth", "me"])

    assert code == 1
    assert "no_credential" in capsys.readouterr().out


def test_auth_me_with_a_bad_token_is_exit_3(answering) -> None:
    answering(401, {"error": {"code": "invalid_token", "message": "kaya did not accept this"}})
    code = main(["auth", "me"])

    assert code == 3


# --- auth logout ---------------------------------------------------------------------------------


def test_auth_logout_clears_the_stored_token(tmp_path) -> None:
    config.write_settings({config.TOKEN_ENV: "kaya_pat_something"})
    assert "token" in config.read_settings_file()

    code = main(["auth", "logout"])

    assert code == 0
    assert "token" not in config.read_settings_file()


def test_auth_logout_reports_logged_out(capsys) -> None:
    config.write_settings({config.TOKEN_ENV: "kaya_pat_something"})

    main(["auth", "logout"])

    assert "logged_out" in capsys.readouterr().out


def test_auth_logout_with_nothing_stored_is_still_exit_0(capsys) -> None:
    code = main(["auth", "logout"])

    assert code == 0
    assert "logged_out  false" in capsys.readouterr().out


def test_auth_logout_makes_no_api_call(fake_api) -> None:
    seen = fake_api(lambda request: (_ for _ in ()).throw(AssertionError("no call expected")))
    config.write_settings({config.TOKEN_ENV: "kaya_pat_something"})

    main(["auth", "logout"])

    assert seen == []


# --- auth login ------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def no_real_sleep_or_browser(monkeypatch):
    """Every `auth login` test in this file patches these three regardless of outcome — a test
    that forgot would sleep for real (`interval` seconds) or try to spawn a browser."""
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(webbrowser, "open", lambda _url: False)


CODE_RESPONSE = {
    "device_code": "a-device-secret",
    "user_code": "WDJB-MJHT",
    "verification_uri": "https://kaya.example/device",
    "verification_uri_complete": "https://kaya.example/device?user_code=WDJB-MJHT",
    "expires_in": 900,
    "interval": 5,
}


def test_login_prints_the_code_and_link(capsys, monkeypatch) -> None:
    monkeypatch.setattr(auth, "create_device_code", lambda *a, **k: CODE_RESPONSE)
    monkeypatch.setattr(auth, "poll_device_token", lambda *a, **k: {"token": "kaya_pat_x"})

    main(["auth", "login"])

    out = capsys.readouterr().out
    assert "WDJB-MJHT" in out
    assert "https://kaya.example/device" in out


def test_login_success_saves_the_token(monkeypatch) -> None:
    monkeypatch.setattr(auth, "create_device_code", lambda *a, **k: CODE_RESPONSE)
    monkeypatch.setattr(auth, "poll_device_token", lambda *a, **k: {"token": "kaya_pat_minted"})

    code = main(["auth", "login"])

    assert code == 0
    assert config.read_settings_file()["token"] == "kaya_pat_minted"


def test_login_polls_until_pending_resolves(monkeypatch) -> None:
    responses = iter(
        [
            {"error": "authorization_pending"},
            {"error": "authorization_pending"},
            {"token": "kaya_pat_eventually"},
        ]
    )
    monkeypatch.setattr(auth, "create_device_code", lambda *a, **k: CODE_RESPONSE)
    monkeypatch.setattr(auth, "poll_device_token", lambda *a, **k: next(responses))

    code = main(["auth", "login"])

    assert code == 0
    assert config.read_settings_file()["token"] == "kaya_pat_eventually"


def test_login_backs_off_on_slow_down(monkeypatch) -> None:
    responses = iter([{"error": "slow_down"}, {"token": "kaya_pat_x"}])
    monkeypatch.setattr(auth, "create_device_code", lambda *a, **k: CODE_RESPONSE)
    monkeypatch.setattr(auth, "poll_device_token", lambda *a, **k: next(responses))

    code = main(["auth", "login"])

    assert code == 0


def test_login_denied_is_a_structured_failure_not_a_traceback(capsys, monkeypatch) -> None:
    monkeypatch.setattr(auth, "create_device_code", lambda *a, **k: CODE_RESPONSE)
    monkeypatch.setattr(auth, "poll_device_token", lambda *a, **k: {"error": "access_denied"})

    code = main(["auth", "login"])

    assert code == 1
    assert "access_denied" in capsys.readouterr().out
    assert "token" not in config.read_settings_file()


def test_login_expired_is_a_structured_failure(capsys, monkeypatch) -> None:
    monkeypatch.setattr(auth, "create_device_code", lambda *a, **k: CODE_RESPONSE)
    monkeypatch.setattr(auth, "poll_device_token", lambda *a, **k: {"error": "expired_token"})

    code = main(["auth", "login"])

    assert code == 1
    assert "expired_token" in capsys.readouterr().out


def test_login_timing_out_without_ever_resolving_is_expired(monkeypatch) -> None:
    """`expires_in: 0` means the polling loop's own `while` never runs even once — the deadline
    check happens before the first `time.sleep`."""
    monkeypatch.setattr(
        auth, "create_device_code", lambda *a, **k: {**CODE_RESPONSE, "expires_in": 0}
    )
    monkeypatch.setattr(
        auth, "poll_device_token", lambda *a, **k: {"error": "authorization_pending"}
    )

    code = main(["auth", "login"])

    assert code == 1


def test_login_sends_the_requested_scope(monkeypatch) -> None:
    seen = []
    monkeypatch.setattr(
        auth,
        "create_device_code",
        lambda base_url, *, scope="write", **k: (seen.append(scope), CODE_RESPONSE)[1],
    )
    monkeypatch.setattr(auth, "poll_device_token", lambda *a, **k: {"token": "kaya_pat_x"})

    main(["auth", "login", "--scope", "read"])

    assert seen == ["read"]


def test_login_defaults_to_write_scope(monkeypatch) -> None:
    seen = []
    monkeypatch.setattr(
        auth,
        "create_device_code",
        lambda base_url, *, scope="write", **k: (seen.append(scope), CODE_RESPONSE)[1],
    )
    monkeypatch.setattr(auth, "poll_device_token", lambda *a, **k: {"token": "kaya_pat_x"})

    main(["auth", "login"])

    assert seen == ["write"]
