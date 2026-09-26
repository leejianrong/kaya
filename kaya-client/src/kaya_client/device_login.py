"""RFC 8628 device-flow login: the two HTTP calls `kaya auth login` needs (ADR 0013, KAN-1743).

**What lives here and what does not.** This module knows the shape of `POST /auth/device/code` and
`POST /auth/device/token` — the same "what does the API return" knowledge `client.py` centralizes
for `/api/v1`, applied to `/auth/device` instead — because a second parsing of these two responses,
written inside `kaya-cli`, is exactly the drift ADR 0004 forbids. **What does not live here is the
polling loop itself**: sleeping between polls, printing the code, and best-effort-opening a browser
are `kaya_cli`'s own interactive concerns, the same way `kaya_cli.context`'s hook mechanism owns its
own orchestration. Unlike every other `kaya_client` module, there is no "would V6's MCP adapter have
to reimplement this?" pressure to weigh that against: ADR 0013 gives kaya's future hosted MCP server
(KAN-1744) a wholly different grant type (a redirect + PKCE flow), so nothing else in the suite will
ever drive this loop.

Two calls, unauthenticated — the device code itself is the only credential either one needs, which
is the whole point of the grant (a CLI with no `KAYA_TOKEN` yet is precisely who calls these):

- `request_device_code` — one request, returns a `DeviceCode`.
- `poll_once` — one request, returns `"pending"`/`"slow_down"` (the caller should sleep and ask
  again — RFC 8628's own two "not yet" answers, kept distinguishable because a `slow_down` must
  widen the caller's own poll interval, and a plain `"pending"` must not) or a `MintedToken` on
  success. Raises `DeviceLoginDenied`/`DeviceLoginExpired` for the two terminal failures, the same
  "a raise site picks a meaning" discipline every other `KayaError` in this package follows.
"""

from dataclasses import dataclass
from typing import Literal

import httpx

from kaya_client.errors import DeviceLoginDenied, DeviceLoginExpired, KayaError, TransportError

DEVICE_CODE_PATH = "/auth/device/code"
DEVICE_TOKEN_PATH = "/auth/device/token"

DEFAULT_TIMEOUT = 10.0
"""Both calls are small, unauthenticated, single-purpose requests against kaya's own origin — not
the note-CRUD path `client.py`'s `DEFAULT_READ_TIMEOUT` (40s) is sized for, which is dominated by a
cold identity round trip these routes never make. A short, fixed timeout is the honest budget for
"is kaya's own front door answering at all"."""


@dataclass(frozen=True, slots=True)
class DeviceCode:
    """`POST /auth/device/code`'s response — RFC 8628 §3.2's field names, since that is the wire
    contract, not `kaya_client`'s own vocabulary to rename."""

    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int


@dataclass(frozen=True, slots=True)
class MintedToken:
    """A device-flow login's successful outcome — the raw secret, once, and its display prefix.
    Trimmed to what `kaya auth login` needs from `TokenCreated`'s full shape on the wire."""

    token: str
    token_prefix: str
    scope: str


PollResult = MintedToken | Literal["pending", "slow_down"]


def _post(api_url: str, path: str, json: dict[str, object], client: httpx.Client | None) -> dict:
    url = api_url.rstrip("/") + path
    owns_client = client is None
    http = client if client is not None else httpx.Client(timeout=DEFAULT_TIMEOUT)
    try:
        try:
            response = http.post(url, json=json)
        except httpx.HTTPError as exc:
            raise TransportError(f"{url} is unreachable") from exc
    finally:
        if owns_client:
            http.close()

    try:
        body = response.json()
    except ValueError as exc:
        raise KayaError(f"{url} returned a body kaya-client could not read") from exc
    if not isinstance(body, dict):
        raise KayaError(f"{url} returned a body kaya-client could not read")
    return body


def request_device_code(
    api_url: str, scope: str, *, client: httpx.Client | None = None
) -> DeviceCode:
    """Start a device-flow login. No credential — this is the entry point for a CLI that has none
    yet."""
    body = _post(api_url, DEVICE_CODE_PATH, {"scope": scope}, client)
    return DeviceCode(
        device_code=str(body["device_code"]),
        user_code=str(body["user_code"]),
        verification_uri=str(body["verification_uri"]),
        verification_uri_complete=str(body["verification_uri_complete"]),
        expires_in=int(body["expires_in"]),
        interval=int(body["interval"]),
    )


def poll_once(
    api_url: str, device_code: str, *, client: httpx.Client | None = None
) -> PollResult:
    """One poll. See the module docstring for the four possible outcomes."""
    body = _post(api_url, DEVICE_TOKEN_PATH, {"device_code": device_code}, client)

    error = body.get("error")
    if error == "authorization_pending":
        return "pending"
    if error == "slow_down":
        return "slow_down"
    if error == "access_denied":
        raise DeviceLoginDenied("the device-flow login was denied")
    if error == "expired_token":
        raise DeviceLoginExpired("the device-flow login code expired before it was approved")
    if error is not None:
        raise KayaError(f"the device-flow token endpoint answered an unknown error: {error!r}")

    try:
        return MintedToken(
            token=str(body["token"]),
            token_prefix=str(body["token_prefix"]),
            scope=str(body["scope"]),
        )
    except KeyError as exc:
        raise KayaError(
            "the device-flow token endpoint's success response was missing a field"
        ) from exc
