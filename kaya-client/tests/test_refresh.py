"""Transparent token renewal (ADR 0016, KAY-172): the retry, the file, and the lock.

Every test drives a real `KayaClient` over an `httpx.MockTransport`, so a `401` is a real `401`
travelling the real code path. The config file is a real file under `tmp_path`.
"""

import json
import threading
from pathlib import Path

import httpx
import pytest

from kaya_client import config
from kaya_client.errors import ApiError
from kaya_client.refresh import REFRESH_CLIENT_ID, refresh_access_token

API = "http://kaya.test"
NOTES = {"notes": []}


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    return {"XDG_CONFIG_HOME": str(tmp_path), "KAYA_API_URL": API}


def _write(env: dict[str, str], **keys: str) -> Path:
    path = config.config_path(env)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(keys))
    return path


def _on_disk(env: dict[str, str]) -> dict:
    return json.loads(config.config_path(env).read_text())


class Server:
    """A stand-in kaya: one live access token, one live refresh token, rotation on refresh."""

    def __init__(self, *, access: str, refresh: str) -> None:
        self.access = access
        self.refresh = refresh
        self.refresh_calls = 0
        self.seen: list[str] = []
        self._count = 0
        self._lock = threading.Lock()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/device/token":
            body = json.loads(request.content)
            with self._lock:
                self.refresh_calls += 1
                if (
                    body["grant_type"] != "refresh_token"
                    or body["client_id"] != REFRESH_CLIENT_ID
                    or body["refresh_token"] != self.refresh
                ):
                    return httpx.Response(400, json={"error": "invalid_grant"})
                self._count += 1
                self.access = f"kaya_pat_new{self._count}"
                self.refresh = f"kaya_rt_new{self._count}"
                return httpx.Response(
                    200,
                    json={
                        "access_token": self.access,
                        "token_type": "Bearer",
                        "scope": "write",
                        "expires_in": 3600,
                        "refresh_token": self.refresh,
                    },
                )
        bearer = request.headers.get("authorization", "")
        self.seen.append(bearer)
        if bearer != f"Bearer {self.access}":
            return httpx.Response(
                401, json={"error": {"code": "invalid_token", "message": "kaya did not accept"}}
            )
        return httpx.Response(200, json=NOTES)


def test_an_expired_token_is_renewed_and_the_request_replayed(env: dict[str, str]) -> None:
    server = Server(access="kaya_pat_live", refresh="kaya_rt_live")
    _write(env, token="kaya_pat_old", refresh_token="kaya_rt_live")

    with config.open_client(env, transport=httpx.MockTransport(server)) as client:
        client.list_notes()

    assert server.refresh_calls == 1
    assert server.seen[-1] == f"Bearer {server.access}"
    stored = _on_disk(env)
    assert stored["token"] == server.access
    assert stored["refresh_token"] == server.refresh


def test_the_new_token_is_used_without_another_refresh(env: dict[str, str]) -> None:
    server = Server(access="kaya_pat_live", refresh="kaya_rt_live")
    _write(env, token="kaya_pat_old", refresh_token="kaya_rt_live")

    with config.open_client(env, transport=httpx.MockTransport(server)) as client:
        client.list_notes()
        client.list_notes()

    assert server.refresh_calls == 1


def test_a_token_with_no_refresh_token_is_never_renewed(env: dict[str, str]) -> None:
    server = Server(access="kaya_pat_live", refresh="kaya_rt_live")
    _write(env, token="kaya_pat_old")

    with (
        config.open_client(env, transport=httpx.MockTransport(server)) as client,
        pytest.raises(ApiError) as caught,
    ):
        client.list_notes()

    assert caught.value.status == 401
    assert server.refresh_calls == 0


def test_an_environment_token_is_never_swapped_for_the_files(env: dict[str, str]) -> None:
    server = Server(access="kaya_pat_live", refresh="kaya_rt_live")
    _write(env, token="kaya_pat_file", refresh_token="kaya_rt_live")
    env = {**env, "KAYA_TOKEN": "kaya_pat_from_env"}

    with (
        config.open_client(env, transport=httpx.MockTransport(server)) as client,
        pytest.raises(ApiError) as caught,
    ):
        client.list_notes()

    assert caught.value.status == 401
    assert server.refresh_calls == 0


def test_a_refused_refresh_token_is_dropped_and_the_401_stands(env: dict[str, str]) -> None:
    server = Server(access="kaya_pat_live", refresh="kaya_rt_live")
    _write(env, token="kaya_pat_old", refresh_token="kaya_rt_consumed", other="kept")

    with (
        config.open_client(env, transport=httpx.MockTransport(server)) as client,
        pytest.raises(ApiError) as caught,
    ):
        client.list_notes()

    assert caught.value.status == 401
    stored = _on_disk(env)
    assert "refresh_token" not in stored
    assert stored["token"] == "kaya_pat_old"
    assert stored["other"] == "kept"


def test_missing_credentials_are_not_a_refresh_case(env: dict[str, str]) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(
            401, json={"error": {"code": "authentication_required", "message": "no"}}
        )

    _write(env, token="kaya_pat_old", refresh_token="kaya_rt_live")
    with (
        config.open_client(env, transport=httpx.MockTransport(handler)) as client,
        pytest.raises(ApiError),
    ):
        client.list_notes()

    assert "/auth/device/token" not in calls


def test_parallel_callers_rotate_once_and_all_succeed(env: dict[str, str]) -> None:
    """The reason for the lock. Eight callers share one stale token and one refresh token; the
    server accepts a refresh token once. Without the re-read under the lock, seven of them
    would spend a consumed token."""
    server = Server(access="kaya_pat_live", refresh="kaya_rt_live")
    _write(env, token="kaya_pat_old", refresh_token="kaya_rt_live")
    transport = httpx.MockTransport(server)
    results: list[str | None] = []
    start = threading.Barrier(8)

    def worker() -> None:
        http = httpx.Client(transport=transport)
        start.wait()
        results.append(
            refresh_access_token("kaya_pat_old", api_url=API, env=env, client=http)
        )

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert server.refresh_calls == 1
    assert results == [server.access] * 8


def test_save_login_without_a_refresh_token_removes_a_stale_one(env: dict[str, str]) -> None:
    _write(env, token="kaya_pat_a", refresh_token="kaya_rt_a", other="kept")

    config.save_login("kaya_pat_b", None, env)

    assert _on_disk(env) == {"token": "kaya_pat_b", "other": "kept"}


def test_logout_removes_both_credentials(env: dict[str, str]) -> None:
    _write(env, token="kaya_pat_a", refresh_token="kaya_rt_a", other="kept")

    config.unset_token(env)

    assert _on_disk(env) == {"other": "kept"}


def test_the_refresh_token_never_appears_in_config_show(env: dict[str, str]) -> None:
    from kaya_client.render import render

    _write(env, token="kaya_pat_secretsecret", refresh_token="kaya_rt_secretsecret")
    for fmt in ("human", "json", "toon"):
        shown = str(render(config.settings_payload(env), fmt=fmt))
        assert "secretsecret" not in shown
        assert "kaya_rt_" not in shown


def test_the_config_file_stays_private_after_a_refresh(env: dict[str, str]) -> None:
    server = Server(access="kaya_pat_live", refresh="kaya_rt_live")
    path = _write(env, token="kaya_pat_old", refresh_token="kaya_rt_live")

    with config.open_client(env, transport=httpx.MockTransport(server)) as client:
        client.list_notes()

    assert path.stat().st_mode & 0o777 == 0o600

