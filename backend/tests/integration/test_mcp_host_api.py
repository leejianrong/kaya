"""The hosted MCP endpoint's bearer-auth boundary (ADR 0013/0014, KAN-1744).

Not a full MCP protocol conformance test (that would mean speaking the real Streamable HTTP
handshake) — this file proves the one thing `app/identity/mcp_host.py` is responsible for: a
request with no bearer, or an unrecognised one, never reaches the tool layer at all, and a request
with a real `personal_access_token` bearer does. `kaya_mcp`'s own test suite covers the tool bodies
themselves.
"""

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]

MCP = "/mcp"
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}
TOOLS_LIST_BODY = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}


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
    from app.main import app

    command.upgrade(_alembic_config(), "head")

    def empty() -> None:
        with get_sessionmaker()() as session:
            session.execute(text("TRUNCATE TABLE personal_access_token, kaya_account CASCADE"))
            session.commit()

    empty()
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        empty()


def mint_pat(client: Any) -> str:
    """A real `personal_access_token` row, minted the same way `poll_device_token` does — not
    through a route, since this file's subject is the bearer boundary, not how a token is minted
    (covered by `test_device_auth_api.py`/`test_oauth_authorize_api.py`)."""
    from app.config import get_settings
    from app.db import get_sessionmaker
    from app.identity.models import KayaAccount
    from app.identity.pat import PersonalAccessToken, generate_token

    raw, prefix, token_hash = generate_token(get_settings().kaya_auth_secret)
    with get_sessionmaker()() as session:
        account = KayaAccount(
            id=uuid.uuid4(),
            email="mcp-caller@example.com",
            hashed_password="not-a-real-hash",
            is_active=True,
            is_superuser=False,
            is_verified=False,
        )
        session.add(account)
        session.flush()
        session.add(
            PersonalAccessToken(
                user_id=account.id,
                name="test token",
                token_hash=token_hash,
                token_prefix=prefix,
                scope="write",
            )
        )
        session.commit()
    return raw


def test_a_request_with_no_bearer_is_401_with_rfc9728_discovery(client: Any) -> None:
    response = client.post(MCP, json=TOOLS_LIST_BODY, headers=MCP_HEADERS)

    assert response.status_code == 401
    www_authenticate = response.headers["www-authenticate"]
    assert www_authenticate.startswith("Bearer resource_metadata=")
    assert "/.well-known/oauth-protected-resource/mcp" in www_authenticate


def test_a_request_with_an_unrecognised_bearer_is_401(client: Any) -> None:
    headers = {**MCP_HEADERS, "Authorization": "Bearer kaya_pat_this-token-was-never-minted"}

    response = client.post(MCP, json=TOOLS_LIST_BODY, headers=headers)

    assert response.status_code == 401


def test_a_request_with_a_malformed_authorization_header_is_401(client: Any) -> None:
    headers = {**MCP_HEADERS, "Authorization": "not-even-a-bearer-scheme"}

    response = client.post(MCP, json=TOOLS_LIST_BODY, headers=headers)

    assert response.status_code == 401


def test_a_request_with_a_real_pat_reaches_the_mcp_transport(client: Any) -> None:
    """Not a 401 — the bearer validated and the request reached the real Streamable HTTP session
    manager, which then answers on its own protocol terms (a bare `tools/list` with no prior
    `initialize` handshake is a protocol-level `400`, not an auth failure)."""
    raw = mint_pat(client)
    headers = {**MCP_HEADERS, "Authorization": f"Bearer {raw}"}

    response = client.post(MCP, json=TOOLS_LIST_BODY, headers=headers)

    assert response.status_code != 401
