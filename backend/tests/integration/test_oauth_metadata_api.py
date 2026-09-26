"""RFC 9728 protected-resource metadata and RFC 8414 authorization-server metadata (ADR 0013/0014,
KAN-1744) — both documents a cold MCP client reads before it can even start the authorization_code
grant."""

from collections.abc import Iterator
from typing import Any

import pytest


@pytest.fixture
def client() -> Iterator[Any]:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def test_protected_resource_metadata_names_this_origin_as_its_own_authorization_server(
    client: Any,
) -> None:
    response = client.get("/.well-known/oauth-protected-resource/mcp")

    assert response.status_code == 200
    body = response.json()
    origin = str(client.base_url).rstrip("/")
    assert body["resource"] == f"{origin}/mcp"
    assert body["authorization_servers"] == [origin]


def test_authorization_server_metadata_points_at_the_three_endpoints(client: Any) -> None:
    response = client.get("/.well-known/oauth-authorization-server")

    assert response.status_code == 200
    body = response.json()
    origin = str(client.base_url).rstrip("/")
    assert body["issuer"] == origin
    assert body["authorization_endpoint"] == f"{origin}/auth/authorize"
    assert body["token_endpoint"] == f"{origin}/auth/device/token"
    assert body["registration_endpoint"] == f"{origin}/auth/register"
    assert body["code_challenge_methods_supported"] == ["S256"]
    assert "authorization_code" in body["grant_types_supported"]
    assert "urn:ietf:params:oauth:grant-type:device_code" in body["grant_types_supported"]


def test_a_subpath_under_mcp_that_matches_nothing_is_a_404_not_an_spa_deep_link(
    client: Any,
) -> None:
    """`app/spa.py`'s `RESERVED_PREFIXES` guard, exercised from this side: `/mcp` itself is a real
    route, but a typo'd sub-path must still 404 as JSON rather than becoming `index.html`."""
    response = client.get("/mcp/nonexistent-subpath")

    assert response.status_code == 404
