"""ADR 0006's frozen tool set, pinned before there are any tools.

Pinning the list while it is still just a list is the cheap moment to do it. Once there are six
working tools, a seventh is a two-line addition that nobody reviews as an architectural change,
and the surface grows by accretion — which is the outcome ADR 0006 exists to prevent.

V6 adds the other half: that every implemented tool appears in this tuple, and that every name in
it has a CLI verb behind it (`MCP ⊆ CLI`). This file holds the count and the names until then.
"""

import tomllib
from pathlib import Path

import kaya_mcp
from kaya_mcp import TOOL_NAMES

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"

EXPECTED = (
    "list_notes",
    "get_note",
    "create_note",
    "edit_note",
    "search_notes",
    "get_backlinks",
)


def test_the_tool_set_is_exactly_the_six_names_adr_0006_froze() -> None:
    assert TOOL_NAMES == EXPECTED


def test_the_tool_count_is_six() -> None:
    """Asserted separately from the names. A rename is a compatibility break for a caller; a new
    tool is a surface-area decision. They fail for different reasons and should read differently.
    """
    assert len(TOOL_NAMES) == 6


def test_tool_names_are_unique_and_snake_case() -> None:
    assert len(set(TOOL_NAMES)) == len(TOOL_NAMES)
    assert all(name == name.lower() and " " not in name for name in TOOL_NAMES)


def test_the_installed_version_matches_pyproject() -> None:
    declared = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    assert kaya_mcp.__version__ == declared["version"]
    assert declared["license"] == "Apache-2.0"
