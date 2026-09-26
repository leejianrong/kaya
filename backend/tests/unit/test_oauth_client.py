"""`app/identity/oauth_client.py`'s pure validation and CIMD resolution (ADR 0014, KAN-1744) — no
database (`register_client`/`resolve_client`'s DCR branch are DB-backed and covered by
`tests/integration/test_oauth_register_api.py` and `test_oauth_authorize_api.py`)."""

import httpx
import pytest

from app.identity.oauth_client import (
    InvalidClientMetadata,
    ResolvedClient,
    _fetch_cimd_document,
    _is_cimd_client_id,
    validate_redirect_uris,
)


def test_validate_redirect_uris_requires_at_least_one() -> None:
    with pytest.raises(InvalidClientMetadata, match="at least one"):
        validate_redirect_uris([])


def test_validate_redirect_uris_accepts_https() -> None:
    validate_redirect_uris(["https://claude.ai/callback"])  # must not raise


def test_validate_redirect_uris_accepts_loopback_http() -> None:
    validate_redirect_uris(["http://127.0.0.1:51234/callback", "http://localhost/callback"])


def test_validate_redirect_uris_rejects_a_bare_http_to_a_real_host() -> None:
    """The MCP spec's loopback-or-HTTPS rule — a plain `http://` redirect to a real host would let
    the authorization code travel in the clear to an on-path attacker."""
    with pytest.raises(InvalidClientMetadata, match="HTTPS or a localhost"):
        validate_redirect_uris(["http://example.com/callback"])


def test_validate_redirect_uris_rejects_too_many() -> None:
    uris = [f"https://example.com/{i}" for i in range(11)]
    with pytest.raises(InvalidClientMetadata, match="10 entries"):
        validate_redirect_uris(uris)


def test_is_cimd_client_id_requires_https_and_a_path() -> None:
    assert _is_cimd_client_id("https://claude.ai/.well-known/oauth-client") is True
    assert _is_cimd_client_id("https://claude.ai") is False
    assert _is_cimd_client_id("https://claude.ai/") is False
    assert _is_cimd_client_id("http://claude.ai/client") is False
    assert _is_cimd_client_id("kaya_client_abc123") is False


def _cimd_response(status: int, body: object = None) -> httpx.Response:
    return httpx.Response(status, json=body)


def test_fetch_cimd_document_parses_a_valid_document(monkeypatch) -> None:
    url = "https://claude.ai/.well-known/oauth-client"

    def fake_get(request_url, *, timeout, follow_redirects):
        assert follow_redirects is False
        return _cimd_response(
            200,
            {
                "client_id": url,
                "redirect_uris": ["https://claude.ai/callback"],
                "client_name": "Claude",
            },
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    resolved = _fetch_cimd_document(url)

    assert resolved == ResolvedClient(
        client_id=url, client_name="Claude", redirect_uris=("https://claude.ai/callback",)
    )


def test_fetch_cimd_document_rejects_a_client_id_mismatch(monkeypatch) -> None:
    url = "https://claude.ai/.well-known/oauth-client"
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **k: _cimd_response(
            200, {"client_id": "https://someone-else.example/x", "redirect_uris": ["https://x/y"]}
        ),
    )

    with pytest.raises(InvalidClientMetadata, match="does not match its URL"):
        _fetch_cimd_document(url)


def test_fetch_cimd_document_rejects_a_non_200(monkeypatch) -> None:
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _cimd_response(404))

    with pytest.raises(InvalidClientMetadata, match="404"):
        _fetch_cimd_document("https://claude.ai/.well-known/oauth-client")


def test_fetch_cimd_document_rejects_missing_redirect_uris(monkeypatch) -> None:
    url = "https://claude.ai/.well-known/oauth-client"
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _cimd_response(200, {"client_id": url}))

    with pytest.raises(InvalidClientMetadata, match="redirect_uris"):
        _fetch_cimd_document(url)


def test_fetch_cimd_document_rejects_a_transport_failure(monkeypatch) -> None:
    def raise_it(*a, **k):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", raise_it)

    with pytest.raises(InvalidClientMetadata, match="could not fetch"):
        _fetch_cimd_document("https://claude.ai/.well-known/oauth-client")
