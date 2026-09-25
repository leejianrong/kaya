"""RFC 8628 Device Authorization Grant — the CLI's unauthenticated half of `kaya auth login`
(ADR 0013, KAN-1743).

**Standalone functions, not `KayaClient` methods.** Both calls are credential-less by construction
— RFC 8628's whole point is that a CLI with no bearer yet needs a way to get one — and
`KayaClient.__init__` requires a real `token: str` it always attaches (`_request`'s own
``Authorization: Bearer {self._token}``). Bolting an "unauthenticated mode" onto that class would
put a conditional in the one place this codebase has kept deliberately unconditional; two small
functions that build their own `httpx` call are cheaper than that conditional and match the
established pattern for a call with genuinely different mechanics from every other one here
(``app/integrations/pandan_link.py``'s `PandanHttpVerifier` on the backend side is the identical
call, for the identical reason).

**`poll_device_token` returns the raw body on every "expected" outcome rather than raising.** RFC
8628 §3.5's `authorization_pending`/`slow_down`/`access_denied`/`expired_token` are normal results
of one poll in a loop, not exceptional failures — raising and immediately catching an exception for
each one would just be control flow wearing a costume, and it is the reason this device-flow
response is deliberately *not* run through `KayaClient._request`'s always-raise-on-4xx path: that
path assumes kaya's own `{"error": {"code", "message", ...}}` shape, and
`app/identity/device_auth_router.py`'s own module docstring explains why `/auth/device/token`
answers with a flat `{"error": "<code>"}` instead, per RFC 8628 §3.5 verbatim. A genuine transport
failure (network down, DNS) still raises `TransportError`, and a genuine server error (5xx) still
raises `ApiError` — those really are exceptional.

Injectable `client`, the same seam `KayaClient` itself offers: a test drives this against an
`httpx.MockTransport`, no network, no live backend.
"""

from typing import Any

import httpx

from kaya_client.client import DEFAULT_TIMEOUT
from kaya_client.errors import ApiError, TransportError

DEVICE_CODE_PATH = "/auth/device/code"
DEVICE_TOKEN_PATH = "/auth/device/token"


def _error_payload(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        body = {}
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        return body
    return {"error": {"code": "http_error", "message": f"the API answered {response.status_code}"}}


def create_device_code(
    api_url: str,
    *,
    scope: str = "write",
    client: httpx.Client | None = None,
    timeout: httpx.Timeout | float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """``POST /auth/device/code`` — start a device-flow login. A genuine failure here (network,
    5xx) is exceptional and raises, unlike `poll_device_token`'s expected polling states."""
    owns_client = client is None
    http = client if client is not None else httpx.Client(timeout=timeout)
    try:
        try:
            response = http.post(
                api_url.rstrip("/") + DEVICE_CODE_PATH,
                json={"scope": scope},
            )
        except httpx.HTTPError as exc:
            raise TransportError(f"{api_url} is unreachable") from exc
        if response.status_code >= 400:
            raise ApiError(response.status_code, _error_payload(response))
        return response.json()
    finally:
        if owns_client:
            http.close()


def poll_device_token(
    api_url: str,
    device_code: str,
    *,
    client: httpx.Client | None = None,
    timeout: httpx.Timeout | float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """``POST /auth/device/token`` — poll once. Returns the parsed JSON body **regardless of
    status code**, except for a genuine transport failure — see the module docstring."""
    owns_client = client is None
    http = client if client is not None else httpx.Client(timeout=timeout)
    try:
        try:
            response = http.post(
                api_url.rstrip("/") + DEVICE_TOKEN_PATH,
                json={"device_code": device_code},
            )
        except httpx.HTTPError as exc:
            raise TransportError(f"{api_url} is unreachable") from exc
        return response.json()
    finally:
        if owns_client:
            http.close()
