"""ADR 0006 §3's schema compaction: strip generated `title` annotations, collapse a nullable scalar.

Two transformations on the JSON Schema an MCP host is *told* about, and nothing else. Both are
"free schema hygiene" in the ADR's words — no rename, no removal, no consumer migration — and both
are the kind of change that reads as cosmetic and is not. ADR 0006 §3 adopts two traps from
pandan's implementation as named guards rather than leaving them to be rediscovered, and this
module is where they live.

### The traversal is driven by JSON Schema keywords, never by a key's spelling

**`title` is both a JSON Schema annotation and a real argument name**, and kaya has the collision
for real: `create_note(title, ...)` and `edit_note(ref, title=None, ...)` each take one, so
`create_note`'s schema contains

    {"properties": {"title": {"title": "Title", "type": "string"}}, ...}

where the *outer* `title` is a **property name** a caller passes and the *inner* one is an
annotation pydantic generated from that name. A recursive walk that deletes every dict key spelled
`title` cannot tell those apart, and pandan's first pass did exactly that and **deleted the
argument from two tools** — a behaviour change wearing a cosmetic disguise, and green in every test
that only measured a size.

So this traversal never asks whether a *key* is called `title`. It asks what **position** it is
looking at. A schema object's keys are JSON Schema keywords, and the keywords are sorted into four
kinds:

- `SCHEMA_MAP_KEYWORDS` — the value is a mapping of *names* to schemas (`properties`, `$defs`, …).
  A key in there is a caller's name and is never inspected; only its value is descended into.
- `SCHEMA_LIST_KEYWORDS` — the value is a list of schemas (`anyOf`, `allOf`, …).
- `SCHEMA_VALUED_KEYWORDS` — the value is one schema (`items`, `not`, `additionalProperties`, …),
  or, for `items` under draft-04, a list of them; a `bool` is passed through untouched.
- everything else is **data**, copied verbatim. That is the third trap, unnamed by the ADR and
  free once the traversal is keyword-driven: `default`, `const`, `enum` and `examples` hold
  arbitrary JSON, so `{"default": {"title": "x"}}` is a *value* whose `title` key a blind walk
  would silently edit.

`title` is dropped only at a **schema position**, which is the one position where it is an
annotation. `tests/test_schema_compaction.py` proves the live collision survives, against the real
`create_note`/`edit_note` schemas rather than a fixture, and asserts they genuinely contain a
`title` argument *before* asserting one survived — an assertion about a case the fixture does not
contain is vacuous.

Nothing in this package authors a `title`: every one of them is pydantic's derivation of a field
name (`if_updated_at` → `"If Updated At"`) or of the argument model's own class name
(`"edit_noteArguments"`), which is what makes "strip *generated* titles" true rather than assumed.
That is checked rather than claimed — the same test rebuilds each removed title from the name it
was generated from.

### The collapse is allow-listed, so the nullable-enum exclusion is a consequence and not a case

`anyOf: [{T}, {"type": "null"}]` → `type: [T, "null"]` is safe for a plain scalar and **wrong for
an enum**: `enum` constrains the whole value irrespective of `type`, so the collapsed
`{"enum": ["a", "b"], "type": ["string", "null"]}` **rejects `null`**, which the two-branch form
accepted. ADR 0006 §3 states the remedy as an allow-list — "the collapse is allow-listed to
sibling keys provably inert for `null` and blocks on anything unreasoned-about" — so
`NULL_INERT_SIBLINGS` below is the rule and the enum exclusion falls out of it. `enum` is refused
because it is not in that set, not because its name appears in a condition; the test names it
because the ADR does.

Provably inert means: JSON Schema's type-specific assertions do not apply to a value of another
type, so `minLength` cannot fail for `null` and neither can `items`. What is deliberately *out* is
every keyword that constrains a value regardless of its type (`enum`, `const`), every
in-place applicator whose outcome would have to be reasoned about (`allOf`, `anyOf`, `oneOf`,
`not`, `if`/`then`/`else`, `$ref`) and the `unevaluated*`/`dependent*` family, which is
object/array-scoped but interacts with annotation collection in ways this module has no reason to
work through. None of them occur in kaya's six schemas; the point of the allow-list is the ones
that occur later.

### What this module may and may not touch

Compaction changes what a host is **told**, never what is **accepted**. The advertised schema and
the pydantic model that validates a call are two objects in this SDK — `Tool.parameters` is
advertised, `Tool.fn_metadata.arg_model` validates, and the former is built from the latter once at
registration and read in exactly one place afterwards (`MCPServer.list_tools`). So
`kaya_mcp.server.SchemaCompactingServer` applies this function at that one place and the validating
model is not reachable from it. That is not payload shaping and does not touch ADR 0004's seam:
`render()` still does every byte of payload work, and this function never sees a payload.

This module raises nothing. A schema it cannot reason about is returned unchanged, which keeps
KAN-964's "this package invents no failure of its own" true: there is no failure to invent, because
declining to compact is a correct outcome rather than an error.
"""

from __future__ import annotations

from typing import Any

STRIPPED_ANNOTATIONS: frozenset[str] = frozenset({"title"})
"""Annotations dropped at a schema position. `description` stays: pydantic builds it from the
tool's own docstring for a `Field(description=...)`, and it is the one thing in a schema a model
reads for meaning."""

SCHEMA_MAP_KEYWORDS: frozenset[str] = frozenset(
    {
        "properties",
        "patternProperties",
        "dependentSchemas",
        "$defs",
        "definitions",
    }
)
"""Keywords whose value maps a **name** to a schema. The names belong to the caller's vocabulary
and are never inspected — this is the set that makes GUARD 2 structural."""

SCHEMA_LIST_KEYWORDS: frozenset[str] = frozenset(
    {
        "anyOf",
        "allOf",
        "oneOf",
        "prefixItems",
    }
)
"""Keywords whose value is a list of schemas."""

SCHEMA_VALUED_KEYWORDS: frozenset[str] = frozenset(
    {
        "items",
        "additionalItems",
        "unevaluatedItems",
        "additionalProperties",
        "unevaluatedProperties",
        "propertyNames",
        "contains",
        "not",
        "if",
        "then",
        "else",
    }
)
"""Keywords whose value is a single schema — or a `bool`, for `additionalProperties` and friends,
which is passed through, or a list, for `items` under draft-04's tuple form."""

NULL_INERT_SIBLINGS: frozenset[str] = frozenset(
    {
        # Pure annotations: they assert nothing about any value.
        "description",
        "default",
        "examples",
        "deprecated",
        "readOnly",
        "writeOnly",
        "$comment",
        # String-only assertions.
        "minLength",
        "maxLength",
        "pattern",
        "format",
        # Number-only assertions.
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        # Array-only assertions.
        "items",
        "prefixItems",
        "minItems",
        "maxItems",
        "uniqueItems",
        "contains",
        "minContains",
        "maxContains",
        # Object-only assertions.
        "properties",
        "required",
        "additionalProperties",
        "patternProperties",
        "propertyNames",
        "minProperties",
        "maxProperties",
    }
)
"""Keys that may sit beside `type` in a branch being collapsed into a nullable type.

Every one is either an annotation or an assertion JSON Schema scopes to a single instance type, so
it cannot fail for `null`. `enum`, `const`, `$ref`, the in-place applicators and the
`unevaluated*`/`dependent*` family are absent **on purpose** — see this module's docstring. A
branch carrying anything outside this set is left as two branches, which costs a few bytes and
cannot change what the schema admits.
"""

NULL_BRANCH: dict[str, Any] = {"type": "null"}
"""The exact branch a collapse consumes. Nothing else counts as the null branch: a branch that also
carries a `description` would lose it, so such a schema is declined rather than half-collapsed."""


def compact_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return `schema` with generated `title`s stripped and nullable scalars collapsed.

    Pure, and never mutates its argument: an advertised schema is derived from the registration
    rather than replacing it, so the two stay comparable (which is what lets a test assert the
    advertisement still agrees with the validating model).
    """
    compacted = _compact_at_schema_position(schema)
    # A JSON Schema document's root is an object, so this narrowing is the type talking, not a
    # runtime possibility: the recursion returns a non-dict only for a non-dict input.
    return compacted if isinstance(compacted, dict) else schema


def _compact_at_schema_position(node: Any) -> Any:
    """Compact one node, knowing that it sits where a **schema** is expected.

    Everything GUARD 2 is about is in that sentence: `title` is stripped here because a schema is
    the one position where `title` is an annotation, and the recursion only ever re-enters through
    a keyword whose value the specification says is a schema.
    """
    if not isinstance(node, dict):
        return node

    out: dict[str, Any] = {}
    for keyword, value in node.items():
        if keyword in STRIPPED_ANNOTATIONS:
            continue
        if keyword in SCHEMA_MAP_KEYWORDS and isinstance(value, dict):
            # The keys here are *names* — a property called `title` is data, not an annotation.
            out[keyword] = {
                name: _compact_at_schema_position(subschema) for name, subschema in value.items()
            }
        elif keyword in SCHEMA_LIST_KEYWORDS and isinstance(value, list):
            out[keyword] = [_compact_at_schema_position(item) for item in value]
        elif keyword in SCHEMA_VALUED_KEYWORDS:
            out[keyword] = _compact_schema_or_list(value)
        else:
            # Data: `type`, `enum`, `const`, `default`, `required`, `examples`, … copied verbatim,
            # because a value's own keys are not JSON Schema keywords.
            out[keyword] = value

    return _collapse_nullable(out)


def _compact_schema_or_list(value: Any) -> Any:
    """A single-schema keyword's value, which may also be a list (`items`, draft-04) or a `bool`."""
    if isinstance(value, dict):
        return _compact_at_schema_position(value)
    if isinstance(value, list):
        return [_compact_at_schema_position(item) for item in value]
    return value


def _collapse_nullable(node: dict[str, Any]) -> dict[str, Any]:
    """`anyOf: [{T}, {"type": "null"}]` → `type: [T, "null"]`, or `node` unchanged.

    GUARD 1 lives in the one `unreasoned` line below, as a consequence of `NULL_INERT_SIBLINGS`
    rather than as a check for `enum` by name.
    """
    branches = node.get("anyOf")
    if not isinstance(branches, list) or len(branches) != 2:
        return node
    if not all(isinstance(branch, dict) for branch in branches):
        return node

    nulls = [branch for branch in branches if branch == NULL_BRANCH]
    others = [branch for branch in branches if branch != NULL_BRANCH]
    if len(nulls) != 1 or len(others) != 1:
        return node

    other = others[0]
    inner_type = other.get("type")
    if not isinstance(inner_type, str) or inner_type == "null":
        # No single type name to widen — a missing `type`, or a list, or `null` twice over.
        return node

    unreasoned = set(other) - NULL_INERT_SIBLINGS - {"type"}
    if unreasoned:
        return node

    siblings = {key: value for key, value in node.items() if key != "anyOf"}
    if set(siblings) & set(other):
        # A key on both the `anyOf` and the branch it would be merged into: one would win
        # silently, and which one is exactly the question this module refuses to guess.
        return node

    return {**siblings, **other, "type": [inner_type, "null"]}
