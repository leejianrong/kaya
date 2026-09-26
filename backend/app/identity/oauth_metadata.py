"""RFC 9728 OAuth 2.0 Protected Resource Metadata for the hosted MCP endpoint (ADR 0013, KAN-1744).

A cold client (Claude.ai, ChatGPT, Cursor) connecting to `/mcp` needs to discover, with no
out-of-band configuration, which authorization server protects it and where. RFC 9728 answers that
with a metadata document at a well-known location derived from the resource's own URL; RFC 6750
answers "how does a client find that document" with a `resource_metadata` parameter on the
`WWW-Authenticate` header of the `401` the resource itself returns — wired in
`app/identity/mcp_host.py`'s `_unauthorized` (this module owns only the metadata document itself;
the two share `METADATA_PATH` so they can't drift apart).

**Why this hand-writes the route instead of calling the SDK's own protected-resource route
helper**: that helper bakes a *fixed* `resource_url`/`authorization_servers` into the route at
*import* time. Kaya's backend is one image deployed to more than one origin —
`http://localhost:8000` in dev, `https://kaya-jian.fly.dev` today, whatever a self-hosted operator's
own reverse proxy terminates TLS at — with no build-time URL to bake in. So this route recomputes
the origin **per request** from `request.base_url`, the exact mechanism
`app/identity/device_auth.py`'s `verification_uri` already uses.

What *is* reused from the SDK is the shape that actually matters: `mcp.shared.auth.
ProtectedResourceMetadata`, the RFC 9728-correct Pydantic model, so the field names/types can't
drift from what a real client's parser expects even though the route construction itself is
hand-rolled.

**Self-issued, on purpose.** `authorization_servers` names this same origin: kaya's backend is both
the resource server (this endpoint protects `/mcp`) and the authorization server (the RFC 8628
device flow, ADR 0013; the `authorization_code`+PKCE grant, ADR 0014) — there is no separate AS to
point at.
"""

from fastapi import APIRouter, Request
from mcp.shared.auth import ProtectedResourceMetadata

# RFC 9728 §3.1: for a resource at `<origin>/mcp`, the metadata document lives at
# `<origin>/.well-known/oauth-protected-resource/mcp` — the well-known prefix with the resource's
# own path appended. Hardcoded to `/mcp` since that's kaya's only protected resource today; if a
# second one is ever added, generalize this alongside `app/identity/mcp_host.py`'s use of it.
METADATA_PATH = "/.well-known/oauth-protected-resource/mcp"

router = APIRouter(tags=["identity"])


@router.get(METADATA_PATH, include_in_schema=False)
def protected_resource_metadata(request: Request) -> ProtectedResourceMetadata:
    """RFC 9728 discovery document for the hosted MCP endpoint (`/mcp`)."""
    origin = str(request.base_url).rstrip("/")
    return ProtectedResourceMetadata(resource=f"{origin}/mcp", authorization_servers=[origin])
