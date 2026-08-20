"""`get_backlinks` is registered (ADR 0006's frozen six) but has nothing behind it: no backend
route, no `KayaClient` method and no CLI verb exist anywhere in kaya today (`/links`/`/backlinks`
is KAN-566, V5, blocked on KAN-562, not landed). See `kaya_mcp/errors.py` for the full reasoning.

This file is the explicit-failure behaviour the sequencing gap calls for: every call refuses
immediately, by name, pointing at KAN-566 — never a silent `{"notes": []}` a caller could mistake
for "this note has no backlinks". `test_protocol_e2e.py::
test_get_backlinks_reaches_a_real_client_as_a_structured_tool_error` is the companion test proving
this reaches a real MCP client as `CallToolResult(is_error=True)`, not just a raised exception at
this package's own call boundary.
"""

import anyio
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from kaya_mcp.errors import CODE
from kaya_mcp.server import server


def call(name: str, **arguments):
    return anyio.run(lambda: server.call_tool(name, arguments))


def test_get_backlinks_is_registered() -> None:
    """The frozen name is real and callable — the half of ADR 0006's requirement this card can
    meet honestly, distinct from the tool actually working."""
    names = {tool.name for tool in anyio.run(server.list_tools)}
    assert "get_backlinks" in names


def test_get_backlinks_refuses_rather_than_returning_an_empty_result() -> None:
    """No `fake_api` fixture is installed for this test at all — proof that the refusal happens
    before any request could be made, because there is no request to make."""
    with pytest.raises(ToolError) as excinfo:
        call("get_backlinks", ref="NOTE-12")
    text = str(excinfo.value)
    assert CODE in text
    assert "KAN-566" in text
    assert "get_backlinks" in text


def test_get_backlinks_refuses_regardless_of_fields(answering) -> None:
    """Even with a live-looking transport installed, the tool must refuse before it would ever
    be tempted to call it — `fields` changes nothing, and no request reaches the fake API."""
    seen = answering(200, {"notes": []})
    with pytest.raises(ToolError):
        call("get_backlinks", ref="NOTE-12", fields=["ref"])
    assert seen == []
