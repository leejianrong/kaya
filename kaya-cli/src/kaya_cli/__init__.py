"""kaya's command-line adapter.

argv in, ``kaya-client`` call, ``render()`` out. Nothing in this package decides what a payload
looks like — that is ADR 0004's whole point, and the reason pandan's MCP adapter inherited none of
its CLI's shaping. That holds for failures too: `failures.report` prints whatever
``kaya_client.render_error`` returns and edits none of it.

The one thing this package *does* own is what an adapter alone can: which stream a byte goes to
(`parsing`), and what number the process exits with (`failures`). An MCP tool has neither, which is
why the exit table is here and the error shape is not.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("kaya-notes")
except PackageNotFoundError:  # pragma: no cover - source checkout without an install
    __version__ = "0.0.0"

__all__ = ["__version__"]
