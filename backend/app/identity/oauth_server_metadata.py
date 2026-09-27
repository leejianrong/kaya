"""RFC 8414 OAuth 2.0 Authorization Server Metadata (ADR 0013/0014, KAN-1744).

The MCP authorization spec requires an authorization server to publish this document ("MCP
authorization servers MUST provide at least one of: OAuth 2.0 Authorization Server Metadata
(RFC 8414) or OpenID Connect Discovery 1.0") — without it, a client that has already found *which*
AS protects `/mcp` (via RFC 9728's `authorization_servers` field, `app/identity/oauth_metadata.py`)
still has no way to learn *where* that AS's `/register`/`/authorize`/`/token` endpoints actually
live, or which capabilities it supports (PKCE S256, CIMD). This is the connective document between
"here's your AS" and "here's how to use it" — served at this AS's own well-known discovery path,
not the resource's.

Built the same way `app/identity/oauth_metadata.py`'s RFC 9728 document is: derived **per request**
from `request.base_url` rather than a fixed string baked in at import time, for the identical
reason (one image, more than one possible origin across dev/Fly/self-hosted) — see that module's
docstring for the full reasoning, which applies unchanged here.
"""

from fastapi import APIRouter, Request

router = APIRouter(tags=["identity"])

METADATA_PATH = "/.well-known/oauth-authorization-server"


@router.get(METADATA_PATH, include_in_schema=False)
def authorization_server_metadata(request: Request) -> dict[str, object]:
    origin = str(request.base_url).rstrip("/")
    return {
        "issuer": origin,
        "authorization_endpoint": f"{origin}/auth/authorize",
        "token_endpoint": f"{origin}/auth/device/token",
        "registration_endpoint": f"{origin}/auth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": [
            "authorization_code",
            "urn:ietf:params:oauth:grant-type:device_code",
        ],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "client_id_metadata_document_supported": True,
        "scopes_supported": ["read", "write"],
    }
