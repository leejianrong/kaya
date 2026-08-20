"""kaya's MCP adapter.

A thin shell over ``kaya-client``. KAN-569 stood the server up: ``kaya_mcp.server`` holds the one
``MCPServer`` instance and the six ``@server.tool()`` registrations, ``kaya_mcp.tools`` holds the
one-client-call-each bodies (the same discipline ``kaya_cli.verbs`` documents), and
``kaya_mcp.errors`` holds the one failure this package invents itself (``get_backlinks`` has
nothing behind it yet — see that module). Every tool calls ``render()`` for its output, which is
how ``fields`` and truncation come for free instead of being retrofitted (ADR 0004).

``TOOL_NAMES`` below is ADR 0006's frozen set, declared before there were any tools so that the
tools were written against a list that already existed rather than the list being
reverse-engineered from whatever got implemented. ``kaya_mcp.server``'s registrations are checked
against it in ``tests/test_server.py``, so "the six frozen names are exactly the six implemented
tools" is asserted rather than assumed.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("kaya-mcp")
except PackageNotFoundError:  # pragma: no cover - source checkout without an install
    __version__ = "0.0.0"

TOOL_NAMES: tuple[str, ...] = (
    "list_notes",
    "get_note",
    "create_note",
    "edit_note",
    "search_notes",
    "get_backlinks",
)
"""The frozen tool set (ADR 0006).

Narrow on purpose. Every name here must have a CLI verb behind it — the direction is
``MCP ⊆ CLI``, and V6's parity test proves it. Adding a name is a decision that amends ADR 0006.
"""

__all__ = ["TOOL_NAMES", "__version__"]
