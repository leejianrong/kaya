"""`device_login.py` against an `httpx.MockTransport` (ADR 0013, KAN-1743). No network, no live
backend — the same discipline `test_client.py` uses for `/api/v1`, applied to `/auth/device`.
"""

import json

import httpx
import pytest

from kaya_client import (
    DeviceCode,
    DeviceLoginDenied,
    DeviceLoginExpired,
    KayaError,
    MintedToken,
    TransportError,
)
from kaya_client.device_login import poll_once, request_device_code

BASE_URL = "https://kaya.example"


def client_over(handler: object) -> httpx.Client:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    return httpx.Client(transport=transport)


def responder(status: int, json_body: object):
    def handle(request: httpx.Request) -> httpx.Response:
        handle.seen = request  # type: ignore[attr-defined]
        return httpx.Response(status, json=json_body)

    return handle


CODE_BODY = {
    "device_code": "a-device-secret",
    "user_code": "WDJB-MJHT",
    "verification_uri": "https://kaya.example/device",
    "verification_uri_complete": "https://kaya.example/device?user_code=WDJB-MJHT",
    "expires_in": 900,
    "interval": 5,
}


def test_request_device_code_parses_every_field() -> None:
    handler = responder(200, CODE_BODY)

    code = request_device_code(BASE_URL, "write", client=client_over(handler))

    assert code == DeviceCode(
        device_code="a-device-secret",
        user_code="WDJB-MJHT",
        verification_uri="https://kaya.example/device",
        verification_uri_complete="https://kaya.example/device?user_code=WDJB-MJHT",
        expires_in=900,
        interval=5,
    )


def test_request_device_code_sends_the_requested_scope() -> None:
    handler = responder(200, CODE_BODY)
    request_device_code(BASE_URL, "read", client=client_over(handler))

    assert json.loads(handler.seen.content) == {"scope": "read"}


def test_request_device_code_raises_transport_error_when_unreachable() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(TransportError):
        request_device_code(BASE_URL, "write", client=client_over(handle))


def test_poll_once_returns_pending_for_authorization_pending() -> None:
    handler = responder(400, {"error": "authorization_pending"})

    assert poll_once(BASE_URL, "a-device-secret", client=client_over(handler)) == "pending"


def test_poll_once_returns_slow_down() -> None:
    handler = responder(400, {"error": "slow_down"})

    assert poll_once(BASE_URL, "a-device-secret", client=client_over(handler)) == "slow_down"


def test_poll_once_raises_denied_on_access_denied() -> None:
    handler = responder(400, {"error": "access_denied"})

    with pytest.raises(DeviceLoginDenied):
        poll_once(BASE_URL, "a-device-secret", client=client_over(handler))


def test_poll_once_raises_expired_on_expired_token() -> None:
    handler = responder(400, {"error": "expired_token"})

    with pytest.raises(DeviceLoginExpired):
        poll_once(BASE_URL, "a-device-secret", client=client_over(handler))


def test_poll_once_raises_kaya_error_on_an_unrecognised_error_code() -> None:
    handler = responder(400, {"error": "something_new"})

    with pytest.raises(KayaError):
        poll_once(BASE_URL, "a-device-secret", client=client_over(handler))


def test_poll_once_returns_the_minted_token_on_success() -> None:
    handler = responder(
        200,
        {
            "id": 1,
            "name": "Device flow login",
            "token_prefix": "kaya_pat_ab12",
            "scope": "write",
            "created_at": "2026-09-26T00:00:00Z",
            "last_used_at": None,
            "expires_at": None,
            "token": "kaya_pat_the_full_raw_secret",
        },
    )

    result = poll_once(BASE_URL, "a-device-secret", client=client_over(handler))

    assert result == MintedToken(
        token="kaya_pat_the_full_raw_secret", token_prefix="kaya_pat_ab12", scope="write"
    )


def test_poll_once_sends_the_device_code_it_was_given() -> None:
    handler = responder(400, {"error": "authorization_pending"})
    poll_once(BASE_URL, "a-specific-device-code", client=client_over(handler))

    assert json.loads(handler.seen.content) == {"device_code": "a-specific-device-code"}


def test_poll_once_raises_kaya_error_on_a_malformed_success_body() -> None:
    handler = responder(200, {"nope": "no token field at all"})

    with pytest.raises(KayaError):
        poll_once(BASE_URL, "a-device-secret", client=client_over(handler))


def test_request_device_code_raises_kaya_error_on_a_body_that_is_not_json() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json at all")

    with pytest.raises(KayaError):
        request_device_code(BASE_URL, "write", client=client_over(handle))
