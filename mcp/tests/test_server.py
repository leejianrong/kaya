"""The registered surface matches ADR 0006's frozen set, no more and no fewer.

`mcp/tests/test_frozen_tool_set.py` pins the six names as a literal, before any tool existed to
check them against. Now that `kaya_mcp.server` has six real registrations, this file is the other
half: the *running server*'s tool names must equal `kaya_mcp.TOOL_NAMES` exactly. A stray seventh
tool, or one of the six missing its `@server.tool()` decorator, fails here rather than being
noticed only when `tests/test_cli_parity.py` goes looking for a CLI verb behind a name nothing ever
registered.

**Three files, and the split is deliberate** (KAN-570). This one asserts the *set*, name for name,
which is the assertion a rename fails. `test_frozen_tool_set.py` asserts the *count*, twice — once
off `server.py`'s decorators and once off what the server lists — because a count and a set fail
for different reasons and its docstring has the cases where the two counts disagree.
`test_cli_parity.py` asserts the *direction*, `MCP ⊆ CLI`, against `kaya-cli`'s own source.
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
