"""What every MCP test runs against: no ambient configuration, and a faked API.

Same shape as `kaya-cli/tests/conftest.py`, for the same reasons — copied rather than imported,
because the two adapter packages are separately installable and a test suite that reached into a
sibling package's tests would break the day one of them ships alone.

### The environment is cleared for every test, without exception

`kaya_client.config` reads `KAYA_API_URL` and `KAYA_TOKEN` from the environment at call time, so a
developer with a real PAT exported would otherwise have a tool call reach a real deployment from
inside the fast test layer. The autouse fixture below clears both.

### The API is an `httpx.MockTransport`, and everything above it is real

`fake_api` replaces `kaya_mcp.tools.open_client` with one that builds a **real** `KayaClient` over
a fake transport. Everything from a tool function down to the JSON `structuredContent` a call
returns is the shipped code path: `kaya_mcp.tools`, `KayaClient._request`, the exception classes,
`render`, `render_error`. Only the socket is imaginary.
"""

import httpx
import pytest
from kaya_client import config

from kaya_mcp import tools

BASE_URL = "https://kaya.example"

TOKEN = "kanban_pat_notarealtokenatall"
"""Not a real credential, and shaped like a pre-rebrand one deliberately: ADR 0002 gives kaya no
token format and no prefix logic, so the tests must not accidentally imply one exists."""

GROCERIES = {
    "ref": "NOTE-12",
    "id": 12,
    "title": "Groceries",
    "body": "milk\neggs",
    "path": "home/groceries.md",
    "created_at": "2026-08-01T09:15:00+00:00",
    "updated_at": "2026-08-09T11:02:33.123456+00:00",
}

READING_LIST = {
    "ref": "NOTE-3",
    "id": 3,
    "title": "A reading list",
    "body": "",
    "path": "",
    "created_at": "2026-07-14T18:00:00+00:00",
    "updated_at": "2026-07-14T18:00:00+00:00",
}

NOTES = {"notes": [GROCERIES, READING_LIST]}


@pytest.fixture(autouse=True)
def no_ambient_configuration(monkeypatch, tmp_path) -> None:
    """Every test starts with no deployment, no credential, no text limit and an empty config file.

    Same reasoning as `kaya-cli/tests/conftest.py`'s fixture of the same name: a developer's own
    shell or `~/.config/kaya/config.json` must never leak into this suite.
    """
    monkeypatch.delenv(config.API_URL_ENV, raising=False)
    monkeypatch.delenv(config.TOKEN_ENV, raising=False)
    monkeypatch.delenv(config.MAX_TEXT_CHARS_ENV, raising=False)
    monkeypatch.setenv(config.CONFIG_HOME_ENV, str(tmp_path / "xdg"))
    monkeypatch.setenv(config.HOME_ENV, str(tmp_path / "home"))


@pytest.fixture
def fake_api(monkeypatch):
    """Install a fake API, returning the request log so a test can assert on what was sent."""
    seen: list[httpx.Request] = []

    def install(handler, *, token: str = TOKEN, base_url: str = BASE_URL) -> list[httpx.Request]:
        def recording(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return handler(request)

        def open_client():
            return config.open_client(
                {config.API_URL_ENV: base_url, config.TOKEN_ENV: token},
                transport=httpx.MockTransport(recording),
            )

        monkeypatch.setattr(tools, "open_client", open_client)
        return seen

    return install


@pytest.fixture
def answering(fake_api):
    """The common case: one canned JSON body for whatever is asked."""

    def install(status: int, body: dict) -> list[httpx.Request]:
        return fake_api(lambda request: httpx.Response(status, json=body))

    return install
