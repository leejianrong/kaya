"""The registered surface matches ADR 0006's frozen set, no more and no fewer.

`mcp/tests/test_frozen_tool_set.py` pins `kaya_mcp.TOOL_NAMES` as a literal, before any tool
existed to check it against. Now that `kaya_mcp.server` has six real registrations, this file is
the other half: the *running server*'s tool names must equal that same tuple exactly. A stray
seventh tool, or one of the six missing its `@server.tool()` decorator, fails here rather than
being noticed only when KAN-570's future CLI-parity test goes looking for a name nothing ever
registered.
"""

import anyio

from kaya_mcp import TOOL_NAMES
from kaya_mcp.server import server


def test_the_registered_tools_are_exactly_the_frozen_six() -> None:
    names = {tool.name for tool in anyio.run(server.list_tools)}
    assert names == set(TOOL_NAMES)


def test_every_read_tool_declares_a_fields_parameter() -> None:
    """ADR 0006 §1: every *read* tool takes `fields`. `create_note`/`edit_note` are writes and are
    named here explicitly as the exemption, so a read tool added later without `fields` fails this
    rather than being noticed only in review.
    """
    writes = {"create_note", "edit_note"}
    reads = [name for name in TOOL_NAMES if name not in writes]
    assert reads  # the assumption this test rests on: some frozen name is a read

    tools_by_name = {tool.name: tool for tool in anyio.run(server.list_tools)}
    for name in reads:
        schema = tools_by_name[name].input_schema
        assert "fields" in schema.get("properties", {}), f"{name} has no fields parameter"

    for name in writes:
        schema = tools_by_name[name].input_schema
        assert "fields" not in schema.get("properties", {}), f"{name} unexpectedly takes fields"
