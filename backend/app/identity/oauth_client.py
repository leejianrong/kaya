"""OAuth client identification: RFC 7591 Dynamic Client Registration and Client ID Metadata
Documents (CIMD) (ADR 0014, KAN-1744).

The MCP authorization spec names three ways an MCP client and this backend (as authorization
server) can establish a shared client identity, in the client's own priority order:
pre-registration (n/a — kaya has no partner-integration allowlist), **Client ID Metadata
Documents** ("SHOULD support... most common"), and **Dynamic Client Registration** ("MAY support...
for backwards compatibility"). This module implements both, mirroring pandan's own build exactly
(ADR 0013's "whichever pandan settles on" — pandan built both simultaneously rather than choosing
one), so `GET /auth/authorize` and `POST /auth/device/token` (extended for
`grant_type=authorization_code`) don't need to know which produced the client they're looking at —
both funnel through `resolve_client`.

**Why both, when the spec now favors CIMD.** Claude's own connector docs spell out the operational
reason DCR alone doesn't scale for a public, "add by URL" listing: "DCR causes Claude to register a
new client on every fresh connection, which can result in very large numbers of registered clients
on your authorization server." Every other current MCP client (ChatGPT, Cursor, at time of writing)
is DCR-only, so DCR stays the required baseline; CIMD is free to add on top (no persistent storage,
no registration endpoint call) and sheds exactly the row-per-connection growth DCR would otherwise
leave behind.

**DCR clients are public clients, no secret.** `POST /auth/register` never issues a
`client_secret` — matching ADR 0014's PKCE-public-client model for every MCP/CLI client kaya has
ever registered a credential for. A confidential-client registration mode is unimplemented until
something actually asks for one.
"""

import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

import httpx
from sqlalchemy import BigInteger, DateTime, String, func, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.models.base import Base

CLIENT_ID_PREFIX = "kaya_client_"
MAX_REDIRECT_URIS = 10
MAX_CLIENT_NAME_LEN = 200

# CIMD fetch hardening (spec: "authorization servers fetching metadata documents SHOULD consider
# SSRF risks" — a deliberately modest MVP mitigation, not exhaustive allowlisting/DNS-rebinding
# protection).
_CIMD_CONNECT_TIMEOUT = 3.0
_CIMD_READ_TIMEOUT = 5.0
_CIMD_MAX_BYTES = 64 * 1024  # a client metadata document is a handful of fields
_CIMD_DEFAULT_CACHE_SECONDS = 300


class OAuthClient(Base):
    """An OAuth client registered via RFC 7591 Dynamic Client Registration — `POST /auth/register`.

    **DCR-registered clients only.** A client identifying itself via a Client ID Metadata Document
    (CIMD, the other mechanism this module adds) is never a row here: its "registration" is just a
    URL it already hosts, fetched fresh (with a short in-memory cache) each time a request needs it
    — see `resolve_client`, the one function both mechanisms funnel through.

    **Public clients only, on purpose.** There is no secret-hash column — matching ADR 0014's model
    of MCP/CLI clients as PKCE public clients, exactly like device-flow PAT issuance already is. A
    confidential-client registration mode is out of scope until a real use case asks for one.

    `client_id` is the opaque, DCR-minted identifier a client presents on every subsequent
    `GET /auth/authorize`/`POST /auth/device/token` call — random, not guessable, but **not itself a
    secret** (public clients have none): the security boundary is PKCE + exact `redirect_uri`
    matching, not the client_id's obscurity.
    """

    __tablename__ = "oauth_client"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    client_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    client_name: Mapped[str | None] = mapped_column(String(MAX_CLIENT_NAME_LEN), nullable=True)
    redirect_uris: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)
    """RFC 7591 requires at least one; the MCP spec requires each be either localhost or HTTPS
    (`validate_redirect_uris` enforces this at registration time, not here — a CHECK can't express
    "every array element")."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class InvalidClientMetadata(ValueError):
    """A registration request or a fetched CIMD document failed validation — callers turn this into
    the RFC 7591 `invalid_client_metadata`/`invalid_redirect_uri` error shape."""


@dataclass(frozen=True, slots=True)
class ResolvedClient:
    """What the authorize/token endpoints need, regardless of whether it came from a DCR row or a
    live CIMD fetch."""

    client_id: str
    client_name: str | None
    redirect_uris: tuple[str, ...]


def _is_valid_redirect_uri(uri: str) -> bool:
    """MCP spec (Communication Security): every redirect URI MUST be either HTTPS or a loopback
    address — never a bare `http://` to a real host."""
    try:
        parsed = urlparse(uri)
    except ValueError:
        return False
    if parsed.scheme == "https":
        return bool(parsed.netloc)
    if parsed.scheme == "http":
        # RFC 8252 §7.3 loopback forms; hostname compared case-insensitively, port ignored (a
        # local CLI/desktop client's own ephemeral-port loopback redirect needs exactly this).
        return (parsed.hostname or "").lower() in {"localhost", "127.0.0.1", "::1"}
    return False


def validate_redirect_uris(redirect_uris: list[str]) -> None:
    if not redirect_uris:
        raise InvalidClientMetadata("redirect_uris must contain at least one URI")
    if len(redirect_uris) > MAX_REDIRECT_URIS:
        raise InvalidClientMetadata(f"redirect_uris must not exceed {MAX_REDIRECT_URIS} entries")
    for uri in redirect_uris:
        if not _is_valid_redirect_uri(uri):
            raise InvalidClientMetadata(
                f"redirect_uri {uri!r} must be HTTPS or a localhost/127.0.0.1/::1 loopback"
            )


def register_client(
    db: Session, *, redirect_uris: list[str], client_name: str | None
) -> OAuthClient:
    """RFC 7591 Dynamic Client Registration: validate, mint an opaque `client_id`, persist, return
    the row. Raises `InvalidClientMetadata` on a bad request — the router turns that into a
    `400`."""
    validate_redirect_uris(redirect_uris)
    if client_name is not None and len(client_name) > MAX_CLIENT_NAME_LEN:
        raise InvalidClientMetadata(f"client_name must not exceed {MAX_CLIENT_NAME_LEN} characters")

    client = OAuthClient(
        client_id=CLIENT_ID_PREFIX + secrets.token_urlsafe(24),
        client_name=client_name,
        redirect_uris=redirect_uris,
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


# --- Client ID Metadata Documents (CIMD) ---------------------------------------------------------

# url -> (monotonic expiry, resolved client). In-memory, resets on cold-start — the same accepted
# tradeoff `app/identity/device_flow.py`'s own poll-cadence tracker takes, and appropriate here for
# the same reason: a wrong/stale entry self-heals within one cache window rather than needing a
# migration.
_cimd_cache: dict[str, tuple[float, ResolvedClient]] = {}

_MAX_AGE_RE = re.compile(r"max-age=(\d+)")


def _is_cimd_client_id(client_id: str) -> bool:
    """A CIMD `client_id` is an HTTPS URL with a path component (spec: "MUST use the 'https' scheme
    and contain a path component") — that shape never collides with a DCR-minted
    `CLIENT_ID_PREFIX` opaque string."""
    if not client_id.startswith("https://"):
        return False
    parsed = urlparse(client_id)
    return bool(parsed.path) and parsed.path != "/"


def _cache_ttl_seconds(response: httpx.Response) -> float:
    """Respect `Cache-Control: max-age` when the document sends one (spec: "SHOULD cache metadata
    respecting HTTP cache headers"); otherwise fall back to a fixed default, deliberately short so
    a client that rotates its own metadata (new redirect_uris, a name change) isn't stuck behind a
    stale cache for long."""
    header = response.headers.get("cache-control", "")
    match = _MAX_AGE_RE.search(header)
    if match:
        return float(match.group(1))
    return _CIMD_DEFAULT_CACHE_SECONDS


def _fetch_cimd_document(client_id_url: str) -> ResolvedClient:
    """Fetch + validate a Client ID Metadata Document. Raises `InvalidClientMetadata` for every way
    the spec says an authorization server MUST reject one (wrong scheme/path, fetch failure,
    invalid JSON, missing required fields, or a `client_id` in the document that doesn't match the
    URL it was fetched from)."""
    if not _is_cimd_client_id(client_id_url):
        raise InvalidClientMetadata("CIMD client_id must be an https:// URL with a path component")

    try:
        # follow_redirects=False: a redirect chain on an attacker-supplied URL is exactly the SSRF
        # shape the spec's security-considerations section warns about; refusing it outright is
        # cheaper than validating each hop.
        response = httpx.get(
            client_id_url,
            timeout=httpx.Timeout(_CIMD_READ_TIMEOUT, connect=_CIMD_CONNECT_TIMEOUT),
            follow_redirects=False,
        )
    except httpx.HTTPError as exc:
        raise InvalidClientMetadata(f"could not fetch client metadata document: {exc}") from exc

    if response.status_code != 200:
        raise InvalidClientMetadata(
            f"client metadata document fetch returned {response.status_code}"
        )
    if len(response.content) > _CIMD_MAX_BYTES:
        raise InvalidClientMetadata("client metadata document exceeds the size limit")

    try:
        document = response.json()
    except ValueError as exc:
        raise InvalidClientMetadata("client metadata document is not valid JSON") from exc
    if not isinstance(document, dict):
        raise InvalidClientMetadata("client metadata document must be a JSON object")

    # Spec: "MUST validate that the fetched document's client_id matches the URL exactly" — the
    # self-referential check that makes an HTTPS URL usable as an identity at all.
    if document.get("client_id") != client_id_url:
        raise InvalidClientMetadata("client metadata document's client_id does not match its URL")

    redirect_uris = document.get("redirect_uris")
    if not isinstance(redirect_uris, list) or not all(isinstance(u, str) for u in redirect_uris):
        raise InvalidClientMetadata("client metadata document is missing redirect_uris")
    validate_redirect_uris(redirect_uris)

    client_name = document.get("client_name")
    if client_name is not None and not isinstance(client_name, str):
        raise InvalidClientMetadata("client metadata document's client_name must be a string")

    resolved = ResolvedClient(
        client_id=client_id_url, client_name=client_name, redirect_uris=tuple(redirect_uris)
    )
    _cimd_cache[client_id_url] = (time.monotonic() + _cache_ttl_seconds(response), resolved)
    return resolved


def resolve_client(db: Session, client_id: str) -> ResolvedClient | None:
    """The one function the authorize/token endpoints call: resolves a `client_id` regardless of
    which mechanism produced it.

    - Looks like a CIMD URL (`https://…/…`) → fetch (or serve from cache) the metadata document at
      that URL.
    - Otherwise → look up a DCR-registered row by `client_id`.

    Returns `None` for an unknown/invalid client_id (the caller's `invalid_client`); raises
    `InvalidClientMetadata` only for a CIMD document that fetched but failed validation, since
    that's a more specific error worth surfacing than a bare "not found".
    """
    if _is_cimd_client_id(client_id):
        cached = _cimd_cache.get(client_id)
        if cached is not None and cached[0] > time.monotonic():
            return cached[1]
        return _fetch_cimd_document(client_id)

    row = db.scalars(select(OAuthClient).where(OAuthClient.client_id == client_id)).first()
    if row is None:
        return None
    return ResolvedClient(
        client_id=row.client_id, client_name=row.client_name, redirect_uris=tuple(row.redirect_uris)
    )
