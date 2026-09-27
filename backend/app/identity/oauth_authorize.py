"""OAuth 2.1 authorization_code + PKCE grant primitives (ADR 0014, KAN-1744).

The redirect-based half ADR 0013 left unspecified: device flow (`app/identity/device_flow.py`) has
no redirect target and cannot be what a browser-embedded client (Claude.ai, ChatGPT, Cursor's
remote-MCP mode) completes. This module holds the pure, DB-free primitives;
`app/identity/oauth_authorize_router.py` and the extended `POST /auth/device/token` in
`app/identity/device_auth.py` are the endpoints that use them.

**The authorization code is a bearer secret, generated and hashed exactly like a device code**
(`generate_device_code`'s own reasoning applies unchanged): high entropy, never displayed to a
human, so there's no length/typo tradeoff — a browser redirect carries it in a query parameter, not
a person's eyes. Store only the hash (`app.identity.pat.hash_token`).

**No refresh token here — see ADR 0014's own "deliberate simplification" section.** A token minted
by this grant is an ordinary, long-lived `kaya_pat_…`, identical to what device flow already mints;
there is nothing to rotate.
"""

import base64
import hashlib
import hmac
import secrets

from starlette.requests import Request

AUTHORIZATION_CODE_TTL_SECONDS = 60
"""≤60s, per ADR 0014 (mirroring pandan ADR 0026's identical number) — long enough for the redirect
round trip through a browser, short enough that a leaked code in a referrer header or a proxy log is
worthless within a minute."""

SUPPORTED_CODE_CHALLENGE_METHOD = "S256"
"""The only PKCE method OAuth 2.1 permits — `plain` is dropped entirely, no fallback."""

_MCP_RESOURCE_PATH = "/mcp"
"""The one resource this authorization server protects today. A suffix constant, not a fixed
origin, so it composes with the per-request origin the same way `app/identity/oauth_metadata.py`/
`app/identity/device_auth.py` already derive theirs."""


def generate_authorization_code() -> str:
    """A high-entropy bearer secret, exchanged at most once. Store only its hash."""
    return secrets.token_urlsafe(32)


def verify_pkce(code_verifier: str, code_challenge: str) -> bool:
    """RFC 7636 §4.6: `code_challenge == BASE64URL-ENCODE(SHA256(code_verifier))` (the `S256`
    method — the only one this server accepts). Constant-time compare: a timing side-channel here
    would leak the challenge one byte at a time."""
    digest = hashlib.sha256(code_verifier.encode()).digest()
    computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return hmac.compare_digest(computed, code_challenge)


def canonical_mcp_resource(request: Request) -> str:
    """This server's one RFC 8707 resource identifier: the hosted MCP endpoint's own canonical URI.
    Derived from `request.base_url` per request, not a fixed string baked in at import time — the
    same reason `app/identity/oauth_metadata.py`'s docstring gives (one image, more than one
    possible origin across dev/Fly/self-hosted)."""
    origin = str(request.base_url).rstrip("/")
    return f"{origin}{_MCP_RESOURCE_PATH}"
