"""`compact_schema` as a rule: the keyword-driven traversal, and ADR 0006 §3's two guards.

This file is about the *function*. `tests/test_schema_compaction.py` is about the six live tools —
the split is the one KAN-570 made for the frozen set, for the same reason: a rule and an
application of it fail for different reasons, and a rule tested only through the surface that
happens to use it is untested for every shape that surface does not currently have.

Two of the shapes below are **constructed and labelled as such**, because kaya's six tools do not
contain them: a nullable *enum* (GUARD 1's whole subject) and the data-valued-keyword case. The
`title` collision is *not* constructed — `create_note` and `edit_note` genuinely take an argument
called `title`, so that guard is asserted against the real schemas next door and only its
mechanical corners are here.
"""

from typing import Any

import jsonschema
import pytest

from kaya_mcp.schema import NULL_INERT_SIBLINGS, compact_schema

NULLABLE_ENUM: dict[str, Any] = {
    "properties": {
        "choice": {
            "anyOf": [{"enum": ["a", "b"], "type": "string"}, {"type": "null"}],
            "default": None,
            "title": "Choice",
        }
    },
    "title": "pickArguments",
    "type": "object",
}
"""**Constructed**, and this is the exact shape pydantic emits for `Literal["a", "b"] | None` —
verified against the real SDK in `test_schema_compaction.py`'s probe, so this literal is a
transcription rather than a guess. Kaya has no such argument today; see
`test_schema_compaction.py::test_kaya_has_no_nullable_enum_so_guard_1_is_asserted_on_a_probe`.
"""

COLLAPSED_ENUM: dict[str, Any] = {"enum": ["a", "b"], "type": ["string", "null"]}
"""What collapsing the branch above would produce — the wrong answer GUARD 1 exists to refuse."""


def _admits(schema: dict[str, Any], instance: Any) -> bool:
    return jsonschema.Draft202012Validator(schema).is_valid(instance)


def test_a_generated_title_is_stripped_at_a_schema_position() -> None:
    compacted = compact_schema({"title": "pickArguments", "type": "object", "properties": {}})
    assert compacted == {"type": "object", "properties": {}}


def test_a_property_named_title_is_a_name_and_survives() -> None:
    """GUARD 2, at its smallest: the outer `title` is a key in `properties` and the inner one is an
    annotation on the schema that key points at. A walk driven by the string cannot tell them
    apart; a walk driven by position never has to.
    """
    compacted = compact_schema(
        {
            "title": "create_noteArguments",
            "type": "object",
            "properties": {"title": {"title": "Title", "type": "string"}},
            "required": ["title"],
        }
    )
    assert "title" in compacted["properties"], "the `title` argument was deleted"
    assert compacted["properties"]["title"] == {"type": "string"}
    assert compacted["required"] == ["title"]
    assert "title" not in compacted


def test_a_property_named_title_survives_at_any_depth() -> None:
    """The same collision, nested — an object-typed argument with a `title` field inside it. The
    recursion re-enters through `properties`, so depth changes nothing.
    """
    compacted = compact_schema(
        {
            "type": "object",
            "properties": {
                "note": {
                    "title": "Note",
                    "type": "object",
                    "properties": {"title": {"title": "Title", "type": "string"}},
                }
            },
        }
    )
    assert "title" in compacted["properties"]["note"]["properties"]
    assert "title" not in compacted["properties"]["note"]


@pytest.mark.parametrize("keyword", ["$defs", "definitions", "patternProperties"])
def test_every_name_to_schema_keyword_treats_its_keys_as_names(keyword: str) -> None:
    """`properties` is not the only mapping whose keys are names. A `$defs` entry called `title`
    is a definition name, and a definition's own `title` is an annotation.
    """
    compacted = compact_schema(
        {"type": "object", keyword: {"title": {"title": "Title", "type": "string"}}}
    )
    assert compacted[keyword] == {"title": {"type": "string"}}


def test_a_title_inside_a_data_valued_keyword_is_left_alone() -> None:
    """**Constructed.** `default`, `const`, `enum` and `examples` hold arbitrary JSON, so their
    contents are values and not schemas. A blind walk edits the caller's data here — the same
    mistake as GUARD 2 one keyword over, and free to avoid once the traversal is keyword-driven.
    """
    schema = {
        "type": "object",
        "properties": {
            "meta": {
                "title": "Meta",
                "type": "object",
                "default": {"title": "untitled", "nested": {"title": "also data"}},
                "examples": [{"title": "an example"}],
                "enum": [{"title": "a member"}],
            }
        },
    }
    compacted = compact_schema(schema)
    meta = compacted["properties"]["meta"]
    assert meta["default"] == {"title": "untitled", "nested": {"title": "also data"}}
    assert meta["examples"] == [{"title": "an example"}]
    assert meta["enum"] == [{"title": "a member"}]
    assert "title" not in meta


def test_the_input_is_never_mutated() -> None:
    schema = {"title": "X", "type": "object", "properties": {"a": {"title": "A", "type": "string"}}}
    before = repr(schema)
    compact_schema(schema)
    assert repr(schema) == before


def test_a_nullable_scalar_is_collapsed() -> None:
    """The feature itself, asserted rather than only its exclusions."""
    compacted = compact_schema(
        {
            "type": "object",
            "properties": {
                "body": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "default": None,
                    "title": "Body",
                }
            },
        }
    )
    assert compacted["properties"]["body"] == {"default": None, "type": ["string", "null"]}


def test_a_nullable_array_collapses_and_keeps_its_items() -> None:
    """`items` is array-scoped, so it cannot fail for `null` — which is why it is in
    `NULL_INERT_SIBLINGS` and why `fields` collapses at all."""
    compacted = compact_schema(
        {
            "type": "object",
            "properties": {
                "fields": {
                    "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                    "default": None,
                    "title": "Fields",
                }
            },
        }
    )
    assert compacted["properties"]["fields"] == {
        "default": None,
        "items": {"type": "string"},
        "type": ["array", "null"],
    }


def test_a_nullable_enum_is_left_uncollapsed() -> None:
    """GUARD 1. The branch carries `enum`, which is not in `NULL_INERT_SIBLINGS`, so the schema is
    returned with both branches intact — a few bytes not saved, against a schema that would have
    started rejecting a call it used to accept.
    """
    assert "enum" not in NULL_INERT_SIBLINGS
    compacted = compact_schema(NULLABLE_ENUM)
    choice = compacted["properties"]["choice"]
    assert "anyOf" in choice, "a nullable enum was collapsed; the collapsed form rejects null"
    assert choice["anyOf"] == [{"enum": ["a", "b"], "type": "string"}, {"type": "null"}]
    assert "type" not in choice, "the branch form carries no top-level `type`; a collapse added one"
    # The generated annotation still goes, because that half is unconditional.
    assert "title" not in choice


def test_the_collapsed_enum_form_really_would_reject_null() -> None:
    """The *reason* GUARD 1 exists, proven against a JSON Schema validator rather than quoted from
    the ADR. `enum` constrains the whole value, so widening `type` does not readmit `null`: the
    two-branch form accepts it and the collapsed one does not.
    """
    two_branch = NULLABLE_ENUM["properties"]["choice"]
    assert _admits(two_branch, None), "the branch form should accept null"
    assert _admits(two_branch, "a")
    assert not _admits(COLLAPSED_ENUM, None), "the collapsed form should reject null"
    assert _admits(COLLAPSED_ENUM, "a")


def test_a_const_branch_is_refused_for_the_same_reason() -> None:
    """`const` is `enum` with one member, and it is out of the allow-list for the same reason. Not
    a case the ADR names — the point of an allow-list rather than a deny-list is that it does not
    have to."""
    schema = {"anyOf": [{"const": "a", "type": "string"}, {"type": "null"}]}
    assert compact_schema(schema) == schema
    assert _admits(schema, None)
    assert not _admits({"const": "a", "type": ["string", "null"]}, None)


@pytest.mark.parametrize(
    "branch",
    [
        {"$ref": "#/$defs/Thing", "type": "object"},
        {"allOf": [{"type": "string"}], "type": "string"},
        {"not": {"type": "string"}, "type": "string"},
        {"if": {"type": "string"}, "then": {"minLength": 1}, "type": "string"},
        {"dependentRequired": {"a": ["b"]}, "type": "object"},
        {"unevaluatedProperties": False, "type": "object"},
    ],
)
def test_an_unreasoned_about_sibling_blocks_the_collapse(branch: dict[str, Any]) -> None:
    """ADR 0006 §3: the collapse "blocks on anything unreasoned-about". These are the families
    deliberately left out of the allow-list, so each one declines rather than guessing."""
    schema = {"anyOf": [branch, {"type": "null"}], "default": None}
    assert compact_schema(schema) == {"anyOf": [branch, {"type": "null"}], "default": None}


@pytest.mark.parametrize(
    "schema",
    [
        # Three branches: not the shape at all.
        {"anyOf": [{"type": "string"}, {"type": "integer"}, {"type": "null"}]},
        # No null branch.
        {"anyOf": [{"type": "string"}, {"type": "integer"}]},
        # The null branch carries something a collapse would drop.
        {"anyOf": [{"type": "string"}, {"type": "null", "description": "explicitly nothing"}]},
        # Two null branches: no single type to widen.
        {"anyOf": [{"type": "null"}, {"type": "null"}]},
        # No `type` on the surviving branch, so nothing to widen.
        {"anyOf": [{"minLength": 1}, {"type": "null"}]},
        # An already-plural `type`: widening a list is a different operation.
        {"anyOf": [{"type": ["string", "integer"]}, {"type": "null"}]},
        # A key on both the `anyOf` and the branch: one would silently win.
        {
            "anyOf": [{"type": "string", "description": "inner"}, {"type": "null"}],
            "description": "outer",
        },
    ],
)
def test_a_shape_that_is_not_a_nullable_scalar_is_returned_unchanged(
    schema: dict[str, Any],
) -> None:
    assert compact_schema(schema) == schema


def test_a_non_dict_schema_is_returned_unchanged() -> None:
    """`additionalProperties: false` and `items: true` are booleans, not schemas. Passed through,
    because a `bool` has no keys to compact and no keys to lose."""
    compacted = compact_schema({"type": "object", "additionalProperties": False, "items": True})
    assert compacted == {"type": "object", "additionalProperties": False, "items": True}
