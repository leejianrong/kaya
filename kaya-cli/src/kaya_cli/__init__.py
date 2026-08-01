"""kaya's command-line adapter.

argv in, ``kaya-client`` call, ``render()`` out. Nothing in this package decides what a payload
looks like — that is ADR 0004's whole point, and the reason pandan's MCP adapter inherited none of
its CLI's shaping.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("kaya-notes")
except PackageNotFoundError:  # pragma: no cover - source checkout without an install
    __version__ = "0.0.0"

__all__ = ["__version__"]
