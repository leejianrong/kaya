"""ADR 0006 §2's freeze: a pinned name set, a pinned count asserted two ways, and a message for the
person who is about to delete a tool and does not know why they shouldn't (KAN-570).

The pin came first, before there were any tools: KAN-569 wrote the six against a list that already
existed rather than reverse-engineering the list from whatever got implemented. What KAN-570 adds is
the rest of what ADR 0006 §2 actually asks for — *"a pinned tool-name set and a pinned count,
asserted in a test whose failure message explains why the pin exists and warns that a removal needs
a CLI-parity check first"* — plus the count asserted **two ways**, with
`tests/test_cli_parity.py` beside this file for §4 rule 2.

### Why the failure messages are the deliverable and not decoration

A pin that only says `assert TOOL_NAMES == EXPECTED` is a speed bump. The person who meets it is
mid-change, believes their change is right, and the cheapest way past a red literal is to edit the
literal — which is the accretion the freeze exists to stop, performed by somebody who never learned
there was a decision here. So the messages below carry the argument: what the freeze is for, that
adding a tool is an ADR amendment rather than a decorator, and — the half a pin usually leaves out
— that **removing** one has a check that has to happen first.

### The count, twice, because the two counts can disagree

`FROZEN_TOOL_COUNT` is compared against the number of `@server.tool()` decorators in `server.py`'s
**source** and against the number of tools the **running server** lists. Those are facts about
different things, and either can move without the other:

- a function decorated but not reachable at import time — defined inside a conditional, shadowed by
  a later definition of the same name, registered on some other `MCPServer` instance — counts once
  in the source and not at all in the listing;
- a tool arriving some other way, through `server.add_tool(...)`, an SDK default, or a second
  module, counts in the listing and not in the source;
- `@server.tool(name="something_else")` counts in both and *names* two different things, which is
  why the decorated function names are compared with the listed names as well.

`tests/test_server.py` holds the third leg — the running server's names against
`kaya_mcp.TOOL_NAMES` — and is where a stray registration or a missing decorator gets diagnosed.
"""

import ast
import tomllib
from pathlib import Path

import anyio

import kaya_mcp
from kaya_mcp import TOOL_NAMES
from kaya_mcp.server import server

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = PACKAGE_ROOT / "pyproject.toml"
SERVER_SOURCE = PACKAGE_ROOT / "src" / "kaya_mcp" / "server.py"

SERVER_INSTANCE = "server"
"""The name `server.py` binds its one `MCPServer` to, and therefore the receiver a registration
decorator has to be spelled on. A second instance in that module would be a second surface, so the
scan below finds registrations on this name and on no other."""

FROZEN_TOOLS: tuple[str, ...] = (
    "list_notes",
    "get_note",
    "create_note",
    "edit_note",
    "search_notes",
    "get_backlinks",
)
"""ADR 0006 §2's tool set, written out here as a literal.

Deliberately a **second** copy of `kaya_mcp.TOOL_NAMES` rather than an import of it. A pin that
lives in the module it pins is the module agreeing with itself, and `assert TOOL_NAMES ==
TOOL_NAMES` survives any edit. The two copies are the whole mechanism: changing the surface means
changing both, having read the message below.
"""

FROZEN_TOOL_COUNT = 6
"""How many, as its own literal.

Not `len(FROZEN_TOOLS)`, for the same reason `FROZEN_TOOLS` is not `TOOL_NAMES`. A rename and an
addition are different events with different costs — a rename breaks a call somebody already makes,
an addition widens a surface nobody agreed to widen — so they fail as two assertions reading two
ways, not as one derived number that can only ever agree with what it was derived from.
"""

WHY_THE_SET_IS_PINNED = (
    "ADR 0006 §2 freezes kaya's MCP surface at six tools, and this pin is what makes the freeze a "
    "failing build rather than a good intention. Pandan reached 49 tools by accretion — each one a "
    "two-line decorator nobody reviewed as an architectural change — and 49 schemas cost 8,775 "
    "resident tokens on a surface that had become impossible to retire. Six is a decision, not a "
    "stage of growth.\n"
    "  ADDING A TOOL MEANS AMENDING ADR 0006 §2, not appending a decorator. The ADR first, then "
    "this pin, then the registration. That friction is the mechanism (ADR 0006 §Consequences), so "
    "editing the literal below to match what was written is routing around the guard rather than "
    "satisfying it, and it is the one repair this message exists to talk you out of."
)

BEFORE_YOU_REMOVE_ONE = (
    "REMOVING A TOOL NEEDS A CLI-PARITY CHECK FIRST, before the decorator goes.\n"
    "  `MCP ⊆ CLI` (ADR 0006 §4, stated once in mcp/README.md and nowhere else) says every tool "
    "here has a CLI verb behind it. It does not say every *caller* can reach that verb: an MCP "
    "host with no checkout has no `kaya` binary, so deleting a tool takes a capability away from "
    "the caller who had only this surface, while the repository still looks complete.\n"
    "  So, in this order: (1) find the tool's row in mcp/README.md's MCP → KayaClient → CLI table "
    "and name the verb it is losing; (2) confirm the caller you are removing it for can reach that "
    "verb another way; (3) amend ADR 0006 §2's list; (4) only then delete the registration, the "
    "name below, and the row in tests/test_cli_parity.py. Deleting the parity row first makes both "
    "halves agree about a capability nobody checked, which is the failure this file and that one "
    "are both shaped around.\n"
    "  Not hypothetical: pandan's packaged skill claimed tool-for-tool coverage in bold while "
    "documenting a `curl` workaround for a missing CLI verb forty lines below it, and that claim "
    "reached a roadmap card where it nearly justified deleting a working MCP surface "
    "(ADR 0006 §Context, finding 2)."
)

WHY_THE_COUNT_IS_ASSERTED_TWICE = (
    "The count is asserted against the source and against the running server, because the two can "
    "disagree and one assertion misses exactly that: a decorated function that never becomes a "
    "registration counts in the source alone, and a tool arriving some other way — "
    "`server.add_tool(...)`, an SDK default, a second module — counts in the listing alone. A "
    "surface is what a host can call, so the listing is the count that decides; the source count "
    "is what tells you where the drift is. See this module's docstring."
)


# ------------------------------------------------------------ reading the registrations


def decorated_tool_names(source: str, *, filename: str = "<memory>") -> tuple[str, ...]:
    """The module-level functions carrying `@server.tool(...)`, in source order.

    An AST read and not a `grep`, for the reason CLAUDE.md §Conventions gives about the guards in
    this repository that got it wrong once: `server.py`'s docstring writes `@server.tool()` while
    explaining what the registrations are, so a text scan counts the prose. That is the vacuity a
    probe here is most exposed to, and
    `test_the_decorator_scan_is_not_fooled_by_prose_or_by_a_lookalike` is what proves this one
    isn't.

    Both `@server.tool` and `@server.tool()` count: which is written is a call-syntax choice the
    SDK accepts either way, and a scan recognising only one would report a real registration as
    missing.
    """
    found: list[str] = []

    for node in ast.parse(source, filename=filename).body:
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if any(_is_a_registration(decorator) for decorator in node.decorator_list):
            found.append(node.name)

    return tuple(found)


def _is_a_registration(decorator: ast.expr) -> bool:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    return (
        isinstance(target, ast.Attribute)
        and target.attr == "tool"
        and isinstance(target.value, ast.Name)
        and target.value.id == SERVER_INSTANCE
    )


def _registered_in_source() -> tuple[str, ...]:
    assert SERVER_SOURCE.is_file(), (
        f"{SERVER_SOURCE} is not there, so the source half of the count has checked nothing. If "
        "the server module moved, move this path with it rather than dropping the assertion."
    )
    return decorated_tool_names(SERVER_SOURCE.read_text(encoding="utf-8"), filename="server.py")


def _listed_by_the_server() -> tuple[str, ...]:
    return tuple(tool.name for tool in anyio.run(server.list_tools))


# ------------------------------------------------------------------------------ the names


def test_the_shipped_tool_set_is_exactly_the_six_names_adr_0006_froze() -> None:
    assert TOOL_NAMES == FROZEN_TOOLS, (
        f"`kaya_mcp.TOOL_NAMES` is {list(TOOL_NAMES)} and the pin is {list(FROZEN_TOOLS)}.\n\n"
        f"{WHY_THE_SET_IS_PINNED}\n\n{BEFORE_YOU_REMOVE_ONE}"
    )


def test_tool_names_are_unique_and_snake_case() -> None:
    assert len(set(TOOL_NAMES)) == len(TOOL_NAMES)
    assert all(name == name.lower() and " " not in name for name in TOOL_NAMES)


def test_the_two_pins_agree_with_each_other() -> None:
    """Both are literals on purpose, so this is what notices one of them being edited alone.

    A rename is a compatibility break for a caller that already calls the old name; an addition is a
    surface-area decision nobody made. Asserting the names and the count separately is what lets
    those fail as two different messages — and the cost of that is a third assertion, here, that
    the two literals have not drifted apart.
    """
    assert len(FROZEN_TOOLS) == FROZEN_TOOL_COUNT, (
        "the two pins disagree with each other, which means one was edited alone: "
        f"{len(FROZEN_TOOLS)} names against a count of {FROZEN_TOOL_COUNT}.\n\n"
        f"{WHY_THE_SET_IS_PINNED}"
    )


# -------------------------------------------------------------------- the count, twice


def test_the_registrations_in_the_source_number_the_frozen_count() -> None:
    """Way one: `@server.tool()` decorators, counted out of `server.py`'s AST."""
    registered = _registered_in_source()

    assert len(registered) == FROZEN_TOOL_COUNT, (
        f"{SERVER_SOURCE.name} carries {len(registered)} `@{SERVER_INSTANCE}.tool()` "
        f"registrations, not {FROZEN_TOOL_COUNT}: {list(registered)}.\n\n"
        f"{WHY_THE_COUNT_IS_ASSERTED_TWICE}\n\n{WHY_THE_SET_IS_PINNED}\n\n{BEFORE_YOU_REMOVE_ONE}"
    )


def test_the_tools_the_server_lists_number_the_frozen_count() -> None:
    """Way two: what a host actually sees when it asks. This is the count that decides."""
    listed = _listed_by_the_server()

    assert len(listed) == FROZEN_TOOL_COUNT, (
        f"the running server lists {len(listed)} tools, not {FROZEN_TOOL_COUNT}: "
        f"{sorted(listed)}.\n\n"
        f"{WHY_THE_COUNT_IS_ASSERTED_TWICE}\n\n{WHY_THE_SET_IS_PINNED}\n\n{BEFORE_YOU_REMOVE_ONE}"
    )


def test_the_source_and_the_running_server_agree_name_for_name() -> None:
    """Two counts that match can still be two different sets, and that is the drift worth naming.

    `@server.tool(name="something_else")` is the cheap way there: the source says `list_notes` and
    a host is offered a name nothing in this repository mentions. Counting cannot see it, so the
    names are compared too — in source order against the pin, since the order the registrations are
    written in is the order ADR 0006 §2 lists them.
    """
    registered = _registered_in_source()

    assert registered == FROZEN_TOOLS, (
        f"{SERVER_SOURCE.name} defines {list(registered)} where the pin is "
        f"{list(FROZEN_TOOLS)}.\n\n{WHY_THE_SET_IS_PINNED}\n\n{BEFORE_YOU_REMOVE_ONE}"
    )
    assert set(_listed_by_the_server()) == set(registered), (
        "the decorated functions in the source and the tools the server lists are different sets "
        "with the same count. Something is registering or renaming a tool outside "
        f"{SERVER_SOURCE.name}'s decorators.\n\n{WHY_THE_COUNT_IS_ASSERTED_TWICE}"
    )


# ------------------------------------------------------------- the scan, shown working


def test_the_decorator_scan_is_not_fooled_by_prose_or_by_a_lookalike() -> None:
    """Every count above is vacuous if this scan can return the wrong thing quietly.

    The first case is the one that matters most, and the one CLAUDE.md §Conventions warns about by
    name: a probe that matched a **docstring** mentioning the thing it was looking for, so the
    "mutation" was a comment. `server.py`'s module docstring writes `@server.tool()`.
    """
    # Prose and a commented-out decorator. A grep over server.py finds both; an AST read does not.
    assert decorated_tool_names('"""Six `@server.tool()` registrations live here."""\n') == ()
    assert decorated_tool_names("# @server.tool()\ndef list_notes():\n    pass\n") == ()

    # Both call spellings are registrations.
    assert decorated_tool_names("@server.tool()\ndef a():\n    pass\n") == ("a",)
    assert decorated_tool_names("@server.tool\ndef a():\n    pass\n") == ("a",)

    # Source order, not sorted and not set order — the pin is compared in order.
    two = "@server.tool()\ndef b():\n    pass\n@server.tool()\ndef a():\n    pass\n"
    assert decorated_tool_names(two) == ("b", "a")

    # An undecorated function is not a tool, nor is a different decorator, nor `tool` on some other
    # object — a second `MCPServer` in this module would be a second surface.
    assert decorated_tool_names("def a():\n    pass\n") == ()
    assert decorated_tool_names("@server.prompt()\ndef a():\n    pass\n") == ()
    assert decorated_tool_names("@other.tool()\ndef a():\n    pass\n") == ()

    # Not module level, so not found — and the counts above turn that into a red assertion naming
    # the shortfall rather than into a pass.
    nested = "def outer():\n    @server.tool()\n    def a():\n        pass\n"
    assert decorated_tool_names(nested) == ()


def test_the_scan_finds_the_registrations_that_are_actually_there() -> None:
    """The other half of the control: shown finding, as well as shown refusing.

    An emptiness assertion passes for the wrong reason if the scanner is broken the other way, so
    this reads the real module. It is also the assertion that would fail first if `server.py`
    stopped being where the registrations live.
    """
    registered = _registered_in_source()

    assert len(registered) == len(set(registered))
    assert all(name.isidentifier() for name in registered)
    assert "list_notes" in registered


# ---------------------------------------------------------------------------- the package


def test_the_installed_version_matches_pyproject() -> None:
    declared = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    assert kaya_mcp.__version__ == declared["version"]
    assert declared["license"] == "Apache-2.0"
