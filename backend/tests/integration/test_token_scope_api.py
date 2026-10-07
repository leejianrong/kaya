"""A `kaya_pat_` token's `read`/`write` scope, enforced server-side (KAN-1887).

The scope column existed since migration `0008`, but nothing read it: a `read` token could do
anything a `write` token could. These tests mint real tokens and drive the real `get_principal`
(no override), over every mutating route the app serves, so the answer is "what a caller would
see", not "what a unit said".

The route list is not guessed here: `tests/unit/test_token_scope_decision.py` enumerates every
non-GET route and forces a scope decision for each. The table below is the integration half, one
row per route that accepts a bearer.

**No `import app.*` at module top** (see `tests/integration/conftest.py`).
"""

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

BACKEND_ROOT = Path(__file__).resolve().parents[2]

NOTES = "/api/v1/notes"
OWNER_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")


def _alembic_config() -> Any:
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


def mint(scope: str | None) -> str:
    """A real `personal_access_token` row for the one account. `scope=None` omits the column so the
    database default applies: the shape of every token minted before this card."""
    from app.config import get_settings
    from app.db import get_sessionmaker
    from app.identity.pat import PersonalAccessToken, generate_token

    raw, prefix, token_hash = generate_token(get_settings().kaya_auth_secret)
    fields: dict[str, Any] = {}
    if scope is not None:
        fields["scope"] = scope
    with get_sessionmaker()() as session:
        session.add(
            PersonalAccessToken(
                user_id=OWNER_ID,
                name=f"{scope} token",
                token_hash=token_hash,
                token_prefix=prefix,
                **fields,
            )
        )
        session.commit()
    return raw


class FakeObjectStorage:
    def __init__(self) -> None:
        self.puts = 0

    def put(self, key: str, body: Any, *, content_type: str) -> None:
        self.puts += 1
        body.read()

    def get(self, key: str) -> Any:
        return None


@pytest.fixture
def storage() -> FakeObjectStorage:
    return FakeObjectStorage()


@pytest.fixture
def client(database_url: str, storage: FakeObjectStorage) -> Iterator[Any]:
    from alembic import command
    from fastapi.testclient import TestClient

    from app.db import get_sessionmaker
    from app.integrations.dependencies import get_object_storage, reset_object_storage
    from app.main import app
    from tests.integration.auth_helpers import seed_kaya_account

    command.upgrade(_alembic_config(), "head")

    def empty() -> None:
        with get_sessionmaker()() as session:
            session.execute(
                text(
                    "TRUNCATE TABLE attachment, note_link, note, pandan_link, "
                    "personal_access_token, kaya_account CASCADE"
                )
            )
            session.commit()

    empty()
    reset_object_storage()
    with get_sessionmaker()() as session:
        seed_kaya_account(session, id=OWNER_ID, email="scope@example.com")
    app.dependency_overrides[get_object_storage] = lambda: storage
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        reset_object_storage()
        empty()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def seed_note(client: Any, write_token: str, title: str = "seed") -> str:
    response = client.post(NOTES, json={"title": title}, headers=bearer(write_token))
    assert response.status_code == 201, response.text
    return response.json()["ref"]


def note_count() -> int:
    from app.db import get_sessionmaker

    with get_sessionmaker()() as session:
        return session.execute(text("SELECT count(*) FROM note")).scalar_one()


# One row per mutating route that accepts a kaya_pat_ bearer. (method, path template, kwargs).
# `{ref}` is filled with a note the write token created. The unit test pins that this table plus the
# cookie-only routes cover every non-GET route the app has.
MUTATING_BEARER_ROUTES: list[tuple[str, str, dict[str, Any]]] = [
    ("POST", "/api/v1/notes", {"json": {"title": "from a read token"}}),
    ("PATCH", "/api/v1/notes/{ref}", {"json": {"title": "renamed"}}),
    ("PATCH", "/api/v1/notes/{ref}", {"json": {"format": True}}),
    ("PATCH", "/api/v1/notes/{ref}", {"json": {"path": "moved/here"}}),
    ("PUT", "/api/v1/notes/NOTE-424242", {"json": {"title": "claimed"}}),
    ("DELETE", "/api/v1/notes/{ref}", {}),
    (
        "POST",
        "/api/v1/notes/{ref}/attachments",
        {"files": {"file": ("a.png", b"bytes", "image/png")}},
    ),
    ("POST", "/api/v1/pandan-link", {"json": {"token": "pandan_pat_whatever"}}),
    ("DELETE", "/api/v1/pandan-link", {}),
    ("PATCH", "/api/v1/preferences", {"json": {"format_on_save": True}}),
]

COOKIE_ONLY_ROUTES: list[tuple[str, str, dict[str, Any]]] = [
    ("POST", "/api/v1/tokens", {"json": {"name": "minted by a token", "scope": "write"}}),
    ("DELETE", "/api/v1/tokens/1", {}),
]


def route_id(case: tuple[str, str, dict[str, Any]]) -> str:
    method, path, kwargs = case
    return f"{method} {path} {sorted(kwargs)} {kwargs.get('json', '')}"


@pytest.mark.parametrize("case", MUTATING_BEARER_ROUTES, ids=route_id)
def test_a_read_token_gets_a_structured_403_on_every_mutating_route(
    client: Any, case: tuple[str, str, dict[str, Any]], storage: FakeObjectStorage
) -> None:
    method, path, kwargs = case
    write_token = mint("write")
    read_token = mint("read")
    ref = seed_note(client, write_token)
    before = note_count()

    response = client.request(method, path.format(ref=ref), headers=bearer(read_token), **kwargs)

    assert response.status_code == 403, response.text
    error = response.json()["error"]
    assert error["code"] == "insufficient_scope"
    assert isinstance(error["message"], str) and "read" in error["message"]
    assert note_count() == before
    assert storage.puts == 0
    # The note the write token made is untouched.
    assert client.get(f"{NOTES}/{ref}", headers=bearer(read_token)).json()["title"] == "seed"


@pytest.mark.parametrize("case", MUTATING_BEARER_ROUTES, ids=route_id)
def test_a_write_token_is_not_stopped_by_scope_on_any_of_them(
    client: Any, case: tuple[str, str, dict[str, Any]]
) -> None:
    method, path, kwargs = case
    write_token = mint("write")
    ref = seed_note(client, write_token)

    response = client.request(method, path.format(ref=ref), headers=bearer(write_token), **kwargs)

    body = response.json() if response.content else {}
    assert body.get("error", {}).get("code") != "insufficient_scope", response.text


def test_a_token_minted_with_no_scope_column_set_is_a_write_token(client: Any) -> None:
    """Every token minted before this card has `scope = 'write'` from the server default (migration
    `0008`), so enforcing `read` cannot lock one out."""
    legacy = mint(None)

    response = client.post(NOTES, json={"title": "legacy"}, headers=bearer(legacy))

    assert response.status_code == 201


def test_a_read_token_still_reads(client: Any) -> None:
    write_token = mint("write")
    read_token = mint("read")
    ref = seed_note(client, write_token)
    headers = bearer(read_token)

    assert client.get(NOTES, headers=headers).status_code == 200
    assert client.get(f"{NOTES}/{ref}", headers=headers).status_code == 200
    assert client.get(f"{NOTES}?q=seed", headers=headers).status_code == 200
    assert client.get(f"{NOTES}/{ref}/backlinks", headers=headers).status_code == 200
    assert client.get(f"{NOTES}/{ref}/versions", headers=headers).status_code == 200
    assert client.get("/api/v1/graph", headers=headers).status_code == 200
    assert client.get("/api/v1/preferences", headers=headers).status_code == 200


@pytest.mark.parametrize("case", COOKIE_ONLY_ROUTES, ids=route_id)
def test_token_management_never_accepts_a_bearer_of_either_scope(
    client: Any, case: tuple[str, str, dict[str, Any]]
) -> None:
    method, path, kwargs = case
    for scope in ("read", "write"):
        response = client.request(method, path, headers=bearer(mint(scope)), **kwargs)
        assert response.status_code == 401, (scope, response.text)


def test_a_read_token_cannot_mint_a_write_token_through_the_device_flow(client: Any) -> None:
    """The device-flow approve step is a cookie-session action; a bearer of any scope is refused."""
    response = client.post("/auth/device/ABCD-EFGH/approve", headers=bearer(mint("read")))

    assert response.status_code in (401, 403, 404, 422)
    assert response.status_code != 200


# --- the hosted /mcp endpoint -------------------------------------------------------------------
#
# Its tools call the REST API over HTTP with the caller's own bearer (`kaya_mcp.tools._client`), so
# a read token is stopped by the same `get_principal` check. Proven end to end against a real server
# on a loopback port, because the tool layer needs a real `KAYA_API_URL` to call back into.

MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def _free_port() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def live_server(client: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """The real app on a loopback port, with `KAYA_API_URL` pointed back at it. Depends on
    `client` for its schema and truncation, not for its transport; the object-storage override it
    installs is irrelevant to the two tools exercised here."""
    import threading
    import time

    import uvicorn

    from app.main import app

    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started, "uvicorn did not start"
    origin = f"http://127.0.0.1:{port}"
    monkeypatch.setenv("KAYA_API_URL", origin)
    try:
        yield origin
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def _rpc_result(response: Any) -> dict[str, Any]:
    import json

    if response.headers.get("content-type", "").startswith("text/event-stream"):
        for line in response.text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[len("data:") :])
        raise AssertionError(response.text)
    return response.json()


def _mcp_session(origin: str, token: str) -> tuple[Any, dict[str, str]]:
    import httpx

    http = httpx.Client(base_url=origin, timeout=20)
    headers = {**MCP_HEADERS, "Authorization": f"Bearer {token}"}
    init = http.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "scope-test", "version": "0"},
            },
        },
    )
    assert init.status_code == 200, init.text
    session_id = init.headers.get("mcp-session-id")
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    http.post(
        "/mcp", headers=headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"}
    )
    return http, headers


def _call_tool(http: Any, headers: dict[str, str], name: str, arguments: dict[str, Any]) -> Any:
    response = http.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )
    assert response.status_code == 200, response.text
    return _rpc_result(response)["result"]


def test_over_mcp_a_read_token_reads_but_every_write_tool_fails_with_403(
    client: Any, live_server: str
) -> None:
    write_token = mint("write")
    read_token = mint("read")
    ref = seed_note(client, write_token, "readable over mcp")
    http, headers = _mcp_session(live_server, read_token)
    before = note_count()

    listed = _call_tool(http, headers, "list_notes", {})
    created = _call_tool(http, headers, "create_note", {"title": "nope"})
    edited = _call_tool(http, headers, "edit_note", {"ref": ref, "title": "nope"})

    assert not listed.get("isError"), listed
    assert "readable over mcp" in str(listed)
    for refused in (created, edited):
        assert refused["isError"] is True, refused
        assert "403" in str(refused) or "insufficient_scope" in str(refused), refused
    assert note_count() == before
    assert client.get(f"{NOTES}/{ref}", headers=bearer(read_token)).json()["title"] == (
        "readable over mcp"
    )


def test_over_mcp_a_write_token_can_write(client: Any, live_server: str) -> None:
    http, headers = _mcp_session(live_server, mint("write"))

    created = _call_tool(http, headers, "create_note", {"title": "from a write token"})

    assert not created.get("isError"), created
