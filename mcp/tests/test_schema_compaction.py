"""ADR 0006 §3 over the six live tools: what a host is told, and that it still matches what runs.

`tests/test_schema_traversal.py` tests the *rule*. This file tests the **surface**, and the
difference matters most for GUARD 2: kaya has an argument genuinely called `title` on two of its six
tools, so the guard that cost pandan two arguments is live here rather than imported worry, and it
has to be asserted against `create_note`'s and `edit_note`'s real schemas. Every such assertion
below is preceded by a **positive control** — that the *uncompacted* schema genuinely contains what
the compacted one is being checked for keeping. "The `title` argument survived" over a fixture that
never had one is a green test asserting nothing, which is the same trap in the reviewer's chair
(CLAUDE.md §Conventions).

### The two schemas this file compares, and why comparing them is the whole property

Compaction changes what a host is **told**; it must not change what is **accepted**. Those are two
objects in this SDK: `MCPServer.list_tools` advertises `Tool.parameters`, while a call is validated
by `Tool.fn_metadata.arg_model` — and `Tool.parameters` *is* that model's own
`model_json_schema(by_alias=True)`, taken once at registration
(`mcp.server.mcpserver.tools.base.Tool.from_function`, read from the installed package). So the
uncompacted listing, reachable as `MCPServer.list_tools(server)` past
`SchemaCompactingServer`'s override, is the validating model's schema, and every "advertised still
agrees with the model" assertion below is a comparison against it — no reach into a private
attribute, and no second source of truth to drift.

Agreement is checked three ways, deliberately, because each catches what the others miss:

1. **Structurally** — same argument names, same `required` set, same per-argument nullability.
2. **Empirically over a corpus of candidate calls**, with a real JSON Schema validator: every call
   the uncompacted schema admitted, the compacted one admits, and vice versa. That is the claim
   SLICES §V6 asks for, and it is the one a structural check cannot make, since two schemas can
   agree on names and required-ness while disagreeing on what they accept — which is exactly what
   a collapsed nullable enum would look like.
3. **By running the server**, through `MCPServer.call_tool` against the suite's fake API: the
   minimal call succeeds, a wrong-typed argument fails, and `create_note`'s `title` reaches the
   wire carrying the value the caller passed. A schema is a claim about calls; a call is the thing
   the claim is about.
"""

import json
from typing import Any, Literal

import anyio
import httpx
import jsonschema
import pytest
from conftest import GROCERIES, NOTES
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from kaya_mcp import TOOL_NAMES
from kaya_mcp.schema import compact_schema
from kaya_mcp.server import SchemaCompactingServer, server

WRONG_VALUE: dict[str, str] = {"deliberately": "the wrong type"}
"""An object, which is not a valid value for any argument in kaya's six schemas (they are strings
and arrays of string), so it is the wrong type for every one of them without a per-argument
table."""

SAMPLE_FOR_TYPE: dict[str, Any] = {
    "string": "a value",
    "array": ["ref"],
    "integer": 3,
    "number": 1.5,
    "boolean": True,
    "object": {},
}


def advertised() -> dict[str, dict[str, Any]]:
    """The compacted input schemas, keyed by tool name — literally what a host receives."""
    return {tool.name: tool.input_schema for tool in anyio.run(server.list_tools)}


def as_pydantic_built_them() -> dict[str, dict[str, Any]]:
    """The uncompacted input schemas: `MCPServer.list_tools` past the override, which is the
    validating model's own `model_json_schema()` (see this module's docstring)."""
    return {
        tool.name: tool.input_schema for tool in anyio.run(lambda: MCPServer.list_tools(server))
    }


def _admits(schema: dict[str, Any], instance: Any) -> bool:
    return jsonschema.Draft202012Validator(schema).is_valid(instance)


def _type_names(prop_schema: dict[str, Any]) -> set[str]:
    """Every non-null type name a property schema mentions, in either the branch or the collapsed
    spelling."""
    names: set[str] = set()
    declared = prop_schema.get("type")
    if isinstance(declared, str):
        names.add(declared)
    elif isinstance(declared, list):
        names.update(name for name in declared if isinstance(name, str))
    for branch in prop_schema.get("anyOf", []):
        if isinstance(branch, dict):
            names |= _type_names(branch)
    return names - {"null"}


def candidate_calls(schema: dict[str, Any]) -> list[dict[str, Any]]:
    """A corpus of argument dicts to try against a tool's schema.

    Derived from the schema rather than hand-written per tool, so a tool whose arguments change
    gets a corpus that changed with it.
    """
    properties: dict[str, Any] = schema.get("properties", {})
    required: list[str] = list(schema.get("required", []))
    optional = [name for name in properties if name not in required]

    def sample(name: str) -> Any:
        types = _type_names(properties[name])
        for type_name in ("string", "array", "integer", "number", "boolean", "object"):
            if type_name in types:
                return SAMPLE_FOR_TYPE[type_name]
        raise AssertionError(f"no sample value for {name}: {properties[name]}")

    minimal = {name: sample(name) for name in required}

    calls: list[dict[str, Any]] = [{}, dict(minimal)]
    calls.append({**minimal, **{name: None for name in optional}})
    calls.append({**minimal, **{name: sample(name) for name in optional}})
    for name in properties:
        calls.append({**minimal, name: WRONG_VALUE})
        calls.append({**minimal, name: None})
    for name in required:
        calls.append({key: value for key, value in minimal.items() if key != name})
    return calls


# ---------------------------------------------------------------------------
# GUARD 2, live: the argument called `title`
# ---------------------------------------------------------------------------

TOOLS_TAKING_A_TITLE = ("create_note", "edit_note")


def test_the_uncompacted_schemas_really_take_an_argument_called_title() -> None:
    """The positive control, and it is not decoration: every assertion in the next two tests is
    vacuous without it. Asserted against the real schemas, so the day `create_note` stops taking a
    `title` this file says so instead of passing over a collision that no longer exists.
    """
    schemas = as_pydantic_built_them()
    for name in TOOLS_TAKING_A_TITLE:
        assert "title" in schemas[name]["properties"], (
            f"{name} does not take a `title` argument, so GUARD 2 is being asserted over a case "
            "that cannot arise"
        )
    # And the collision is real: the property's own schema carries a generated `title` annotation,
    # which is the key a blind walk cannot tell from the property name above it.
    assert schemas["create_note"]["properties"]["title"]["title"] == "Title"


@pytest.mark.parametrize("name", TOOLS_TAKING_A_TITLE)
def test_the_title_argument_survives_compaction(name: str) -> None:
    """GUARD 2. Pandan's first pass deleted this argument from two tools; this is the assertion
    that fails when that happens, and it names the argument rather than a size."""
    schema = advertised()[name]
    assert "title" in schema["properties"], (
        f"the `title` argument was deleted from {name} by compaction — a JSON Schema annotation "
        "and a property name were confused (ADR 0006 §3, GUARD 2)"
    )


def test_no_argument_name_is_lost_from_any_tool() -> None:
    """The general form of the same claim: not just `title`, every argument on every tool."""
    before, after = as_pydantic_built_them(), advertised()
    for name in TOOL_NAMES:
        lost = set(before[name]["properties"]) - set(after[name]["properties"])
        assert not lost, f"compaction deleted argument(s) {sorted(lost)} from {name}"
        gained = set(after[name]["properties"]) - set(before[name]["properties"])
        assert not gained, f"compaction invented argument(s) {sorted(gained)} on {name}"


def test_every_stripped_title_was_a_generated_one() -> None:
    """ADR 0006 §3 says strip *generated* titles, and nothing in this package authors one — so
    that word is checkable rather than assumed: each annotation removed is rebuilt from the name it
    was generated from. A card that starts writing `Field(title=...)` reddens here, which is the
    notification that the strip has begun costing information.
    """
    for name, schema in as_pydantic_built_them().items():
        assert schema["title"] == f"{name}Arguments"
        for argument, prop_schema in schema["properties"].items():
            if "title" in prop_schema:
                assert prop_schema["title"] == argument.replace("_", " ").title(), (
                    f"{name}.{argument} carries an authored title, which compaction would drop"
                )


# ---------------------------------------------------------------------------
# The advertisement still agrees with the model that validates the call
# ---------------------------------------------------------------------------


def test_required_ness_is_preserved_exactly() -> None:
    before, after = as_pydantic_built_them(), advertised()
    for name in TOOL_NAMES:
        assert set(after[name].get("required", [])) == set(before[name].get("required", [])), (
            f"{name}'s required arguments changed under compaction"
        )


def test_nullability_is_preserved_argument_by_argument() -> None:
    """Checked by asking a validator, not by reading the spelling: the branch form and the
    collapsed form say the same thing in different words, and `null` either validates or it does
    not."""
    before, after = as_pydantic_built_them(), advertised()
    for name in TOOL_NAMES:
        for argument, prop_schema in before[name]["properties"].items():
            was_nullable = _admits(prop_schema, None)
            is_nullable = _admits(after[name]["properties"][argument], None)
            assert is_nullable == was_nullable, (
                f"{name}.{argument} changed nullability under compaction: "
                f"{was_nullable} -> {is_nullable}"
            )


def test_every_call_the_uncompacted_schema_admitted_the_compacted_one_admits() -> None:
    """SLICES §V6's property, both directions, over a derived corpus and a real validator."""
    before, after = as_pydantic_built_them(), advertised()
    checked = 0
    for name in TOOL_NAMES:
        for call in candidate_calls(before[name]):
            was, now = _admits(before[name], call), _admits(after[name], call)
            assert was == now, (
                f"{name} disagrees on {call!r}: uncompacted admits={was}, compacted admits={now}"
            )
            checked += 1
    assert checked >= 6 * 4, "the corpus collapsed to nothing, so this test asserted nothing"


def test_the_corpus_contains_both_admitted_and_refused_calls() -> None:
    """Anti-vacuity for the test above: a corpus every schema accepts would let a compaction that
    dropped every constraint pass it."""
    before = as_pydantic_built_them()
    verdicts = {
        _admits(before[name], call) for name in TOOL_NAMES for call in candidate_calls(before[name])
    }
    assert verdicts == {True, False}


# ---------------------------------------------------------------------------
# GUARD 1, on a probe, because kaya has no nullable enum
# ---------------------------------------------------------------------------


def test_kaya_has_no_nullable_enum_so_guard_1_is_asserted_on_a_probe() -> None:
    """The honest statement of what GUARD 1 covers here.

    Kaya's six tools take strings and lists of strings, so **no argument on any of them is a
    nullable enum**: the exclusion is a guard against a case that cannot arise from today's
    signatures, and dressing it up as covering a live one would be the vacuity this file's other
    positive controls exist to prevent. It is still worth having — ADR 0006 froze six tools, not
    six signatures, and a `Literal[...] | None` argument is one keyword away — so it is asserted
    over a *constructed* tool driven through the real SDK, below.

    This test is also the notification: the day a real nullable enum lands, it reddens, and the
    guard graduates from constructed to live.
    """
    for name, schema in as_pydantic_built_them().items():
        for argument, prop_schema in schema["properties"].items():
            branches = [prop_schema, *prop_schema.get("anyOf", [])]
            assert not any("enum" in branch or "const" in branch for branch in branches), (
                f"{name}.{argument} is now an enum — GUARD 1 has a live case and this file should "
                "assert it against the real schema rather than the probe below"
            )


def _probe_server() -> SchemaCompactingServer:
    """**Constructed**, and labelled: a server that is not kaya's, holding one tool kaya does not
    have. It exists so GUARD 1 is asserted against a schema pydantic and this SDK actually
    produced, rather than against a literal somebody believed they would produce.
    """
    probe = SchemaCompactingServer(name="probe")

    @probe.tool()
    def pick(
        choice: Literal["a", "b"] | None = None, note: str | None = None
    ) -> dict[str, Any]:  # pragma: no cover - never called; only its schema is read
        """A tool with one nullable enum argument and one nullable scalar, side by side."""
        return {}

    return probe


def test_the_probe_really_produces_a_nullable_enum() -> None:
    """Positive control for the probe: the SDK emits the shape GUARD 1 is about."""
    probe = _probe_server()
    schema = anyio.run(lambda: MCPServer.list_tools(probe))[0].input_schema
    assert schema["properties"]["choice"]["anyOf"] == [
        {"enum": ["a", "b"], "type": "string"},
        {"type": "null"},
    ]


def test_the_probes_nullable_enum_is_advertised_uncollapsed_and_its_scalar_collapsed() -> None:
    """GUARD 1 and the feature it excepts, in one schema, as a host would receive them."""
    probe = _probe_server()
    schema = anyio.run(probe.list_tools)[0].input_schema
    choice, note = schema["properties"]["choice"], schema["properties"]["note"]

    assert "anyOf" in choice, (
        "the nullable enum was collapsed; the collapsed form rejects null, which the branch form "
        "accepted (ADR 0006 §3, GUARD 1)"
    )
    assert _admits(choice, None) and _admits(choice, "a")

    assert note == {"default": None, "type": ["string", "null"]}, (
        "the nullable scalar was not collapsed, so ADR 0006 §3's saving is not being taken"
    )
    assert _admits(note, None) and _admits(note, "anything")


# ---------------------------------------------------------------------------
# Driving the server: a schema is a claim about calls
# ---------------------------------------------------------------------------


def _routed(request: httpx.Request) -> httpx.Response:
    """One note for an entity read or a write, the list for a collection read."""
    if request.method == "GET" and request.url.path.rstrip("/").endswith("notes"):
        return httpx.Response(200, json=NOTES)
    if request.method == "GET" and "backlinks" in request.url.path:
        return httpx.Response(200, json=NOTES)
    return httpx.Response(201 if request.method == "POST" else 200, json=GROCERIES)


def test_the_advertised_schema_is_pinned_byte_for_byte(fake_api) -> None:
    """What a host sees, as a literal. Every other test here checks a property; this one records
    the artefact, so a change to it is a diff in review rather than a percentage in a PR body."""
    assert advertised() == {
        "list_notes": {
            "properties": {
                "fields": {
                    "default": None,
                    "items": {"type": "string"},
                    "type": ["array", "null"],
                }
            },
            "type": "object",
        },
        "get_note": {
            "properties": {
                "ref": {"type": "string"},
                "fields": {
                    "default": None,
                    "items": {"type": "string"},
                    "type": ["array", "null"],
                },
            },
            "required": ["ref"],
            "type": "object",
        },
        "create_note": {
            "properties": {
                "title": {"type": "string"},
                "body": {"default": None, "type": ["string", "null"]},
                "path": {"default": None, "type": ["string", "null"]},
            },
            "required": ["title"],
            "type": "object",
        },
        "edit_note": {
            "properties": {
                "ref": {"type": "string"},
                "title": {"default": None, "type": ["string", "null"]},
                "body": {"default": None, "type": ["string", "null"]},
                "path": {"default": None, "type": ["string", "null"]},
                "if_updated_at": {"default": None, "type": ["string", "null"]},
            },
            "required": ["ref"],
            "type": "object",
        },
        "search_notes": {
            "properties": {
                "q": {"type": "string"},
                "fields": {
                    "default": None,
                    "items": {"type": "string"},
                    "type": ["array", "null"],
                },
            },
            "required": ["q"],
            "type": "object",
        },
        "get_backlinks": {
            "properties": {
                "ref": {"type": "string"},
                "fields": {
                    "default": None,
                    "items": {"type": "string"},
                    "type": ["array", "null"],
                },
            },
            "required": ["ref"],
            "type": "object",
        },
    }


def test_the_title_argument_still_reaches_the_wire_carrying_its_value(fake_api) -> None:
    """GUARD 2's behavioural half. An argument can survive in a schema and still be the one a host
    was told to stop sending, so the proof is a real call through `MCPServer.call_tool` and the
    request body it produced."""
    seen = fake_api(_routed)

    result = anyio.run(lambda: server.call_tool("create_note", {"title": "Groceries"}))

    assert not result.is_error, result.content
    assert json.loads(seen[-1].content)["title"] == "Groceries"


def test_edit_note_sends_a_title_too(fake_api) -> None:
    seen = fake_api(_routed)

    result = anyio.run(lambda: server.call_tool("edit_note", {"ref": "12", "title": "Renamed"}))

    assert not result.is_error, result.content
    assert json.loads(seen[-1].content)["title"] == "Renamed"


def _run(name: str, call: dict[str, Any]) -> tuple[bool, str]:
    """Run a tool call for real, returning whether it ran and, if not, why.

    `MCPServer.call_tool` *raises* `ToolError` on an argument the model refuses — the catch that
    turns it into `CallToolResult(is_error=True)` is one layer further out, in
    `_handle_call_tool`, which is the protocol handler rather than this method. So the refusal
    arrives here as an exception, and its text is kept: a test that only counted refusals could not
    tell "the model rejected these arguments" from "the API answered badly", and the two mean
    opposite things about the schema.
    """
    try:
        result = anyio.run(lambda: server.call_tool(name, call))
    except ToolError as refusal:
        return False, str(refusal)
    return not result.is_error, str(result.content)


@pytest.mark.parametrize("name", TOOL_NAMES)
def test_a_call_the_advertised_schema_admits_is_accepted_and_one_it_refuses_is_not(
    name: str, fake_api
) -> None:
    """The three-way agreement: the compacted advertisement, the uncompacted model schema, and the
    server actually running the call.

    The claim is precise, and the imprecise version of it does not hold — measured, not guessed. A
    schema is a statement about an argument dict's **shape**, so the assertion is "refused *as
    invalid* exactly when the advertised schema refuses". Two calls in this corpus are admitted by
    every schema involved and still refused, both by `kaya-client` and both correctly:
    `edit_note {"ref": …}` alone is `usage: nothing to change — name at least one of title, body,
    path`, and `get_note {"ref": …, "fields": […]}` is ADR 0004's `fields` on a single entity. A
    test demanding "admitted ⇒ ran" would have to special-case them, and would then be asserting
    kaya's semantics rather than the compaction's fidelity.
    """
    fake_api(_routed)
    schema = advertised()[name]
    uncompacted = as_pydantic_built_them()[name]

    for call in candidate_calls(uncompacted):
        admitted = _admits(schema, call)
        ran, detail = _run(name, call)
        refused_as_invalid = not ran and "validation error" in detail
        assert refused_as_invalid == (not admitted), (
            f"{name}{call!r}: the advertised schema says admitted={admitted} but the server "
            f"{'ran' if ran else 'refused'} it — {detail}"
        )


def test_compacting_the_advertised_schema_again_changes_nothing() -> None:
    """Idempotence, which is what makes "the advertisement is derived" safe to say: nothing
    accumulates if the transformation is applied twice."""
    for schema in advertised().values():
        assert compact_schema(schema) == schema
