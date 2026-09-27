"""`app/identity/oauth_authorize.py`'s pure primitives — no database, no FastAPI (ADR 0014,
KAN-1744)."""

import base64
import hashlib

from starlette.requests import Request

from app.identity.oauth_authorize import (
    canonical_mcp_resource,
    generate_authorization_code,
    verify_pkce,
)


def _request(base_url: str) -> Request:
    scheme, rest = base_url.split("://", 1)
    host, _, path = rest.partition("/")
    host_part, _, port_part = host.partition(":")
    scope = {
        "type": "http",
        "scheme": scheme,
        "server": (host_part, int(port_part) if port_part else (443 if scheme == "https" else 80)),
        "path": f"/{path}",
        "headers": [],
        "query_string": b"",
        "root_path": "",
    }
    return Request(scope)


def test_generate_authorization_code_is_url_safe_and_high_entropy() -> None:
    code = generate_authorization_code()

    assert len(code) >= 32
    import re

    assert re.fullmatch(r"[A-Za-z0-9_-]+", code)


def test_two_authorization_codes_are_never_the_same() -> None:
    assert generate_authorization_code() != generate_authorization_code()


def _s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def test_verify_pkce_accepts_a_correctly_derived_challenge() -> None:
    verifier = "a-fixed-verifier-for-this-test-0123456789"

    assert verify_pkce(verifier, _s256(verifier)) is True


def test_verify_pkce_rejects_a_mismatched_verifier() -> None:
    challenge = _s256("the-real-verifier")

    assert verify_pkce("a-wrong-verifier", challenge) is False


def test_verify_pkce_rejects_an_empty_challenge() -> None:
    """The device-flow-row default for `code_challenge` (never set on that kind of row) must never
    accidentally verify against anything."""
    assert verify_pkce("anything", "") is False


def test_canonical_mcp_resource_derives_from_the_request_origin() -> None:
    request = _request("https://kaya.example/auth/authorize")

    assert canonical_mcp_resource(request) == "https://kaya.example/mcp"


def test_canonical_mcp_resource_preserves_a_nonstandard_port() -> None:
    request = _request("http://localhost:8000/auth/authorize")

    assert canonical_mcp_resource(request) == "http://localhost:8000/mcp"
