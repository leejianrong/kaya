"""kaya's MCP adapter.

A thin shell over ``kaya-client``. KAN-569 stood the server up: ``kaya_mcp.server`` holds the one
``MCPServer`` instance and the six ``@server.tool()`` registrations and ``kaya_mcp.tools`` holds the
one-client-call-each bodies (the same discipline ``kaya_cli.verbs`` documents). Every tool calls
``render()`` for its output, which is how ``fields`` and truncation come for free instead of being
retrofitted (ADR 0004).

**This package invents no failure of its own** — KAN-964 deleted ``kaya_mcp.errors``, whose single
class existed so that ``get_backlinks`` could refuse every call while ``/links``/``/backlinks`` had
landed at no layer. KAN-566 landed all three (the route, ``KayaClient.backlinks``, ``kaya
backlinks``), so the refusal became a false statement about the repository rather than an honest
gap, and the module went with it. Every failure a tool can raise is now a ``kaya_client`` one,
which is what ADR 0004's arrow predicts of a thin adapter.

``kaya_mcp.schema`` is ADR 0006 §3's schema compaction (KAN-571): generated ``title``
annotations stripped and ``anyOf: [{T}, {null}]`` collapsed, applied where the schemas are
*advertised* and nowhere near where a call is *validated*. It raises nothing, so the sentence above
survives it — a schema the rule cannot reason about is returned unchanged, which is an answer rather
than an error.

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
