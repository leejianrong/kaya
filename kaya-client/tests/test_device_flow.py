"""`kaya_client.device_flow`'s two standalone functions, against an `httpx.MockTransport` — no
network, no live backend (ADR 0013, KAN-1743).
"""

import httpx
import pytest

from kaya_client import ApiError, TransportError
from kaya_client.device_flow import create_device_code, poll_device_token

BASE_URL = "https://kaya.example"


def client_over(handler: object) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]


def responder(status: int, json_body: object):
    def handle(request: httpx.Request) -> httpx.Response:
        handle.seen = request  # type: ignore[attr-defined]
        return httpx.Response(status, json=json_body)

    return handle


CODE_BODY = {
    "device_code": "a-secret-the-cli-polls-with",
    "user_code": "WDJB-MJHT",
    "verification_uri": "https://kaya.example/device",
    "verification_uri_complete": "https://kaya.example/device?user_code=WDJB-MJHT",
    "expires_in": 900,
    "interval": 5,
}


# --- create_device_code --------------------------------------------------------------------------


def test_create_device_code_returns_the_body_verbatim() -> None:
    with client_over(responder(200, CODE_BODY)) as http:
        result = create_device_code(BASE_URL, client=http)

    assert result == CODE_BODY


def test_create_device_code_hits_the_device_code_path_with_no_bearer() -> None:
    handler = responder(200, CODE_BODY)
    with client_over(handler) as http:
        create_device_code(BASE_URL, client=http)

    seen = handler.seen  # type: ignore[attr-defined]
    assert seen.url.path == "/auth/device/code"
    assert "authorization" not in seen.headers


def test_create_device_code_sends_the_requested_scope() -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        seen.append(_json.loads(request.content))
        return httpx.Response(200, json=CODE_BODY)

    with client_over(handler) as http:
        create_device_code(BASE_URL, scope="read", client=http)

    assert seen == [{"scope": "read"}]


def test_create_device_code_raises_api_error_on_a_server_failure() -> None:
    body = {"error": {"code": "runtime", "message": "boom"}}
    with client_over(responder(500, body)) as http, pytest.raises(ApiError) as excinfo:
        create_device_code(BASE_URL, client=http)
    assert excinfo.value.status == 500


def test_create_device_code_raises_transport_error_when_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with client_over(handler) as http, pytest.raises(TransportError):
        create_device_code(BASE_URL, client=http)


# --- poll_device_token ----------------------------------------------------------------------------


def test_poll_device_token_returns_the_success_body() -> None:
    body = {"token": "kaya_pat_abc", "id": 1, "name": "Device flow login", "scope": "write"}
    with client_over(responder(200, body)) as http:
        result = poll_device_token(BASE_URL, "a-device-code", client=http)

    assert result == body


def test_poll_device_token_returns_the_flat_error_body_without_raising() -> None:
    """RFC 8628 §3.5's polling states are expected outcomes, not exceptions — see the module
    docstring on why this deliberately does not go through `KayaClient._request`'s always-raise
    path."""
    with client_over(responder(400, {"error": "authorization_pending"})) as http:
        result = poll_device_token(BASE_URL, "a-device-code", client=http)

    assert result == {"error": "authorization_pending"}


@pytest.mark.parametrize(
    "error", ["authorization_pending", "slow_down", "access_denied", "expired_token"]
)
def test_poll_device_token_never_raises_on_any_documented_polling_state(error: str) -> None:
    with client_over(responder(400, {"error": error})) as http:
        result = poll_device_token(BASE_URL, "a-device-code", client=http)
    assert result["error"] == error


def test_poll_device_token_hits_the_device_token_path_with_the_code() -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        seen.append(_json.loads(request.content))
        return httpx.Response(200, json={"token": "kaya_pat_x"})

    with client_over(handler) as http:
        poll_device_token(BASE_URL, "the-device-code", client=http)

    assert seen == [{"device_code": "the-device-code"}]


def test_poll_device_token_raises_transport_error_when_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with client_over(handler) as http, pytest.raises(TransportError):
        poll_device_token(BASE_URL, "a-device-code", client=http)
