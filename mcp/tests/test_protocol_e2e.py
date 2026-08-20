"""One full round trip over the real MCP protocol, in-process.

Every other test in this package calls `MCPServer.call_tool` directly, which is the SDK's
convenience wrapper and — as this file exists to prove — **not** the layer that turns a raised
exception into `CallToolResult(is_error=True)`. That conversion happens one layer up, in
`mcp.server.mcpserver.server.MCPServer._handle_call_tool`, which only runs when a real
`tools/call` JSON-RPC request is dispatched through a session. So `test_tools.py`'s
`pytest.raises(ToolError)` assertions are honest about what they prove (the right exception, with
the right JSON message, is raised) and this file is what proves the thing SLICES §V6's demo
actually describes: an MCP *client*, talking JSON-RPC over a stream pair to this server, receiving
a structured tool error rather than a broken connection or a bare traceback.

`mcp.shared.memory.create_client_server_memory_streams` is the SDK's own in-memory transport — no
socket, no subprocess — so this is still a "no network, no PAT" test, wired the same way
`conftest.answering` fakes the HTTP boundary underneath it.
"""

import anyio
from conftest import GROCERIES
from mcp.client.session import ClientSession
from mcp.shared.memory import create_client_server_memory_streams

from kaya_mcp.server import server


async def _call_over_the_wire(name: str, arguments: dict):
    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        result: dict = {}

        async def run_server() -> None:
            await server._lowlevel_server.run(
                server_read,
                server_write,
                server._lowlevel_server.create_initialization_options(),
            )

        async with anyio.create_task_group() as tg:
            tg.start_soon(run_server)
            async with ClientSession(client_read, client_write) as session:
                await session.initialize()
                result["value"] = await session.call_tool(name, arguments)
        return result["value"]


def call(name: str, **arguments):
    return anyio.run(_call_over_the_wire, name, arguments)


def test_a_successful_call_reaches_a_real_client_with_structured_content(answering) -> None:
    answering(200, GROCERIES)
    result = call("get_note", ref="NOTE-12")
    assert result.is_error is False
    assert result.structured_content["ref"] == "NOTE-12"


def test_a_kaya_error_reaches_a_real_client_as_a_structured_tool_error(answering) -> None:
    """A `404` from the fake API surfaces as `CallToolResult(is_error=True)` over the wire — the
    SDK's tool-level failure channel, not a protocol error and not a dropped connection."""
    answering(404, {"error": {"code": "note_not_found", "message": "no such note"}})
    result = call("get_note", ref="NOTE-999")
    assert result.is_error is True
    assert "note_not_found" in result.content[0].text


def test_get_backlinks_reaches_a_real_client_as_a_structured_tool_error() -> None:
    """SLICES §V6's demo, for the tool this card cannot finish: a real client asking for
    backlinks gets a clear, structured refusal over the wire — never a connection drop and never a
    silently empty result."""
    result = call("get_backlinks", ref="NOTE-12")
    assert result.is_error is True
    assert "KAN-566" in result.content[0].text
