"""`/auth/register`, `/auth/authorize*`, and `/auth/device/token`'s `grant_type=authorization_code`
branch, end to end (ADR 0014, KAN-1744).

Mirrors `test_device_auth_api.py`'s fixture shape: `get_current_active_user` overridden directly for
the human half (`/auth/authorize/info`, `/approve`, `/deny`), while `/auth/register`,
`/auth/authorize` and the token endpoint take no auth of their own, exercised as any client would
reach them.
"""

import base64
import hashlib
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]

REGISTER = "/auth/register"
AUTHORIZE = "/auth/authorize"
AUTHORIZE_INFO = "/auth/authorize/info"
APPROVE = "/auth/authorize/approve"
DENY = "/auth/authorize/deny"
TOKEN = "/auth/device/token"


def _alembic_config() -> Any:
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


@pytest.fixture
def client(database_url: str) -> Iterator[Any]:
    from alembic import command
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    from app.db import get_sessionmaker
    from app.identity.current_user import get_current_active_user
    from app.identity.models import KayaAccount
    from app.main import app

    command.upgrade(_alembic_config(), "head")

    def empty() -> None:
        with get_sessionmaker()() as session:
            session.execute(
                text(
                    "TRUNCATE TABLE device_authorization, oauth_client, personal_access_token, "
                    "kaya_account CASCADE"
                )
            )
            session.commit()

    empty()

    account = KayaAccount(
        id=uuid.uuid4(),
        email="alice@example.com",
        hashed_password="not-a-real-hash",
        is_active=True,
        is_superuser=False,
        is_verified=False,
    )
    with get_sessionmaker()() as session:
        session.add(account)
        session.commit()
        session.refresh(account)

    app.dependency_overrides[get_current_active_user] = lambda: account
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        empty()


def register(client: Any, redirect_uris: list[str], client_name: str | None = "Claude.ai") -> dict:
    response = client.post(
        REGISTER, json={"redirect_uris": redirect_uris, "client_name": client_name}
    )
    assert response.status_code == 201, response.text
    return response.json()


def pkce_pair() -> tuple[str, str]:
    verifier = "a-fixed-code-verifier-for-tests-0123456789ABCDEF"
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def authorize_params(client_id: str, redirect_uri: str, resource: str, **overrides: Any) -> dict:
    _, challenge = pkce_pair()
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": resource,
        "scope": "write",
        "state": "xyz",
    }
    params.update(overrides)
    return params


def mcp_resource(client: Any) -> str:
    return str(client.base_url).rstrip("/") + "/mcp"


# --- RFC 7591 DCR ---------------------------------------------------------------------------------


def test_register_mints_a_public_client_with_no_secret(client: Any) -> None:
    body = register(client, ["https://claude.ai/callback"])

    assert body["client_id"].startswith("kaya_client_")
    assert body["token_endpoint_auth_method"] == "none"
    assert "client_secret" not in body


def test_register_rejects_a_confidential_auth_method(client: Any) -> None:
    response = client.post(
        REGISTER,
        json={
            "redirect_uris": ["https://claude.ai/callback"],
            "token_endpoint_auth_method": "client_secret_post",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_client_metadata"


def test_register_rejects_a_bare_http_redirect_uri(client: Any) -> None:
    response = client.post(REGISTER, json={"redirect_uris": ["http://example.com/callback"]})

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_redirect_uri"


def test_register_rejects_no_redirect_uris_at_all(client: Any) -> None:
    response = client.post(REGISTER, json={"redirect_uris": []})

    assert response.status_code == 400


# --- GET /auth/authorize --------------------------------------------------------------------------


def test_authorize_redirects_to_the_device_consent_screen(client: Any) -> None:
    registered = register(client, ["https://claude.ai/callback"])
    params = authorize_params(
        registered["client_id"], "https://claude.ai/callback", mcp_resource(client)
    )

    response = client.get(AUTHORIZE, params=params, follow_redirects=False)

    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith(str(client.base_url) + "/device?")
    forwarded = parse_qs(urlparse(location).query)
    assert forwarded["client_id"] == [registered["client_id"]]
    assert forwarded["state"] == ["xyz"]


def test_authorize_with_an_unknown_client_id_is_a_direct_json_error_never_a_redirect(
    client: Any,
) -> None:
    """RFC 6749 §4.1.2.1: an unknown client_id must never be answered via a redirect to an
    attacker-supplied `redirect_uri` — the open-redirect guard ADR 0014 names explicitly."""
    params = authorize_params(
        "nonexistent-client", "https://evil.example/steal", mcp_resource(client)
    )

    response = client.get(AUTHORIZE, params=params, follow_redirects=False)

    assert response.status_code == 400, "a direct JSON error, not a redirect"
    assert response.json()["error"] == "invalid_client"


def test_authorize_with_an_unregistered_redirect_uri_is_also_a_direct_json_error(
    client: Any,
) -> None:
    registered = register(client, ["https://claude.ai/callback"])
    params = authorize_params(
        registered["client_id"], "https://an-unregistered-uri.example/cb", mcp_resource(client)
    )

    response = client.get(AUTHORIZE, params=params, follow_redirects=False)

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"


def test_authorize_rejects_plain_pkce_via_redirect(client: Any) -> None:
    """Once redirect_uri is trusted, every further problem goes back to the client via that URI —
    unlike the two errors above."""
    registered = register(client, ["https://claude.ai/callback"])
    params = authorize_params(
        registered["client_id"],
        "https://claude.ai/callback",
        mcp_resource(client),
        code_challenge_method="plain",
    )

    response = client.get(AUTHORIZE, params=params, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"].startswith("https://claude.ai/callback?")
    assert "error=invalid_request" in response.headers["location"]


def test_authorize_rejects_the_wrong_resource_via_redirect(client: Any) -> None:
    registered = register(client, ["https://claude.ai/callback"])
    params = authorize_params(
        registered["client_id"], "https://claude.ai/callback", "https://not-this-server/mcp"
    )

    response = client.get(AUTHORIZE, params=params, follow_redirects=False)

    assert response.status_code == 302
    assert "error=invalid_target" in response.headers["location"]


# --- the consent screen's own read/approve/deny ---------------------------------------------------


def test_authorize_info_reports_the_client_name_and_scope(client: Any) -> None:
    registered = register(client, ["https://claude.ai/callback"], client_name="Claude.ai")
    params = authorize_params(
        registered["client_id"], "https://claude.ai/callback", mcp_resource(client)
    )

    response = client.get(AUTHORIZE_INFO, params=params)

    assert response.status_code == 200
    assert response.json() == {
        "client_name": "Claude.ai",
        "requested_scope": "write",
        "resource": mcp_resource(client),
    }


def test_authorize_info_requires_a_cookie_session(client: Any) -> None:
    from app.identity.current_user import get_current_active_user
    from app.main import app

    registered = register(client, ["https://claude.ai/callback"])
    params = authorize_params(
        registered["client_id"], "https://claude.ai/callback", mcp_resource(client)
    )
    app.dependency_overrides.pop(get_current_active_user)

    response = client.get(AUTHORIZE_INFO, params=params)

    assert response.status_code == 401


def test_approve_then_exchange_mints_a_working_token(client: Any) -> None:
    registered = register(client, ["https://claude.ai/callback"], client_name="Claude.ai")
    verifier, challenge = pkce_pair()
    resource = mcp_resource(client)
    params = {
        "client_id": registered["client_id"],
        "redirect_uri": "https://claude.ai/callback",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": resource,
        "scope": "read",
        "state": "xyz",
    }

    approved = client.post(APPROVE, json=params)
    assert approved.status_code == 200, approved.text
    redirect_to = approved.json()["redirect_to"]
    assert redirect_to.startswith("https://claude.ai/callback?")
    query = parse_qs(urlparse(redirect_to).query)
    assert query["state"] == ["xyz"]
    code = query["code"][0]

    exchanged = client.post(
        TOKEN,
        json={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "https://claude.ai/callback",
            "client_id": registered["client_id"],
            "code_verifier": verifier,
            "resource": resource,
        },
    )
    assert exchanged.status_code == 200, exchanged.text
    body = exchanged.json()
    assert body["access_token"].startswith("kaya_pat_")
    assert body["token_type"] == "Bearer"
    assert body["scope"] == "read"
    assert "expires_in" not in body, "ADR 0014's simplification: no refresh-token rotation"
    assert "refresh_token" not in body

    listed = client.get("/api/v1/tokens").json()
    assert len(listed) == 1
    assert listed[0]["name"] == "Claude.ai (authorization code)"
    assert listed[0]["scope"] == "read"


def test_a_second_exchange_of_the_same_code_fails(client: Any) -> None:
    registered = register(client, ["https://claude.ai/callback"])
    verifier, challenge = pkce_pair()
    resource = mcp_resource(client)
    params = {
        "client_id": registered["client_id"],
        "redirect_uri": "https://claude.ai/callback",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": resource,
        "scope": "write",
        "state": None,
    }
    code = parse_qs(urlparse(client.post(APPROVE, json=params).json()["redirect_to"]).query)[
        "code"
    ][0]
    exchange_body = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": "https://claude.ai/callback",
        "client_id": registered["client_id"],
        "code_verifier": verifier,
        "resource": resource,
    }
    first = client.post(TOKEN, json=exchange_body)
    assert first.status_code == 200

    second = client.post(TOKEN, json=exchange_body)

    assert second.status_code == 400
    assert second.json() == {"error": "invalid_grant"}


def test_exchange_rejects_the_wrong_code_verifier(client: Any) -> None:
    registered = register(client, ["https://claude.ai/callback"])
    _, challenge = pkce_pair()
    resource = mcp_resource(client)
    params = {
        "client_id": registered["client_id"],
        "redirect_uri": "https://claude.ai/callback",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": resource,
        "scope": "write",
        "state": None,
    }
    code = parse_qs(urlparse(client.post(APPROVE, json=params).json()["redirect_to"]).query)[
        "code"
    ][0]

    response = client.post(
        TOKEN,
        json={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "https://claude.ai/callback",
            "client_id": registered["client_id"],
            "code_verifier": "the-wrong-verifier-entirely",
            "resource": resource,
        },
    )

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_grant"}


def test_exchange_rejects_a_mismatched_redirect_uri(client: Any) -> None:
    registered = register(client, ["https://claude.ai/callback", "https://claude.ai/other"])
    verifier, challenge = pkce_pair()
    resource = mcp_resource(client)
    params = {
        "client_id": registered["client_id"],
        "redirect_uri": "https://claude.ai/callback",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": resource,
        "scope": "write",
        "state": None,
    }
    code = parse_qs(urlparse(client.post(APPROVE, json=params).json()["redirect_to"]).query)[
        "code"
    ][0]

    response = client.post(
        TOKEN,
        json={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "https://claude.ai/other",  # registered, but not what was approved
            "client_id": registered["client_id"],
            "code_verifier": verifier,
            "resource": resource,
        },
    )

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_grant"}


def test_deny_redirects_with_access_denied_and_mints_nothing(client: Any) -> None:
    registered = register(client, ["https://claude.ai/callback"])
    _, challenge = pkce_pair()
    params = {
        "client_id": registered["client_id"],
        "redirect_uri": "https://claude.ai/callback",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": mcp_resource(client),
        "scope": "write",
        "state": "abc",
    }

    response = client.post(DENY, json=params)

    assert response.status_code == 200
    query = parse_qs(urlparse(response.json()["redirect_to"]).query)
    assert query["error"] == ["access_denied"]
    assert query["state"] == ["abc"]
    assert client.get("/api/v1/tokens").json() == []


# --- device-flow polling is unaffected by the shared token endpoint -------------------------------


def test_the_device_flow_grant_still_defaults_when_grant_type_is_omitted(client: Any) -> None:
    """`kaya auth login` (KAN-1743) never sends `grant_type` at all — this must still work
    unchanged now that the same endpoint also serves `authorization_code`."""
    code = client.post("/auth/device/code", json={"scope": "write"}).json()

    response = client.post(TOKEN, json={"device_code": code["device_code"]})

    assert response.status_code == 400
    assert response.json() == {"error": "authorization_pending"}
