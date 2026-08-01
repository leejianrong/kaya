"""kaya's MCP adapter.

A thin shell over ``kaya-client``. Every tool will call ``render()`` for its output, which is how
``fields`` and truncation come for free instead of being retrofitted (ADR 0004).

The server itself lands in V6. What exists now is the *set* of tool names ADR 0006 froze, declared
here so that when the tools are written they are written against a list that already exists —
rather than the list being reverse-engineered from whatever got implemented.
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
