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


def test_get_backlinks_reaches_a_real_client_with_structured_content(answering) -> None:
    """**Inverted in KAN-964**, and the inversion is the card landing — see
    `test_get_backlinks.py`'s module docstring for the full account.

    This test used to be `test_get_backlinks_reaches_a_real_client_as_a_structured_tool_error`:
    SLICES §V6's demo for the one tool KAN-569 could not finish, proving a real client asking for
    backlinks got a clear structured refusal over the wire rather than a dropped connection. KAN-566
    landed the route, the client method and the CLI verb, so what has to reach a real client now is
    the notes.

    The failure half of this file did **not** thin out as a result: the test above it drives a `404`
    through the same session and is what proves `_handle_call_tool`'s
    exception → `CallToolResult(is_error=True)` conversion still happens. This one no longer needs
    to be a second witness for that, so it is the demo it was always trying to be.
    """
    answering(200, {"notes": [GROCERIES]})
    result = call("get_backlinks", ref="NOTE-12")
    assert result.is_error is False
    assert [n["ref"] for n in result.structured_content["notes"]] == ["NOTE-12"]
    assert result.structured_content["summary"] == {"count": 1}
