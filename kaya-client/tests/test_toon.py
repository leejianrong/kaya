"""The ``toon`` encoder: a fixed corpus byte-for-byte, and the round trip that says it is TOON.

Two kinds of assertion, and they are load-bearing in different directions.

**Byte-for-byte against a fixed corpus** (SLICES §V2a, unit) is what pins the *grammar*. TOON is a
published format, and an encoder that emitted a private dialect would round-trip perfectly through
a decoder written to match it while being unreadable to anything else. The corpus below is written
out as literals — the header line, the quoting, the two-space indent — so a change to any of them is
a change a reviewer reads rather than a diff of two generated strings.

**Round-trip equality through `toon_decode`** (SLICES §V2a, e2e) is what pins the *data*. The
decoder is written against the grammar rather than against the encoder's internals, so a bug that
made both agree would have to be made twice, in opposite directions.

Neither is sufficient alone: a corpus test passes for an encoder that mangles anything outside the
corpus, and a round-trip test passes for an encoder that invented its own format.
"""

import ast
import json
import math
from pathlib import Path

import pytest
from conftest import GROCERIES, READING_LIST
from toon_decode import decode

from kaya_client import Payload, render
from kaya_client.toon import encode

# ------------------------------------------------------------------ the fixed corpus

NOTE_LIST = (
    "notes[2]{ref,id,title,body,path,created_at,updated_at}:\n"
    '  NOTE-12,12,Groceries,"milk\\neggs",home/groceries.md,'
    '"2026-08-01T09:15:00+00:00","2026-08-09T11:02:33.123456+00:00"\n'
    '  NOTE-3,3,A reading list,"","",'
    '"2026-07-14T18:00:00+00:00","2026-07-14T18:00:00+00:00"'
)
"""`note list`, and the whole argument for the format in five lines.

The seven field names appear **once**, in the header, and each note is one row — which is the saving
`scripts/measure_toon_delta.py` measures. Three details are worth reading rather than skimming:

- ``A reading list`` is bare. Spaces inside a cell are safe; only a leading or trailing one is not.
- The timestamps are quoted because they contain ``:``, which is TOON's key separator.
- ``""`` is an empty string and ``null`` would be ``None``. `NoteCreate` defaults ``body`` and
  ``path`` to ``""``, so the difference is the common case rather than an edge one.
"""

SINGLE_NOTE = (
    "ref: NOTE-12\n"
    "id: 12\n"
    "title: Groceries\n"
    'body: "milk\\neggs"\n'
    "path: home/groceries.md\n"
    'created_at: "2026-08-01T09:15:00+00:00"\n'
    'updated_at: "2026-08-09T11:02:33.123456+00:00"'
)
"""`note get`, and the payload shape TOON does **not** win on — one object has no repeated keys to
dedupe. Pandan's V47 measured `get` at +2% against compact JSON; kaya's own number for both shapes
is in KAN-541's PR body. The format is still offered for it, because a consumer that asked for one
document grammar should not get two."""

CONFLICT = (
    "error:\n"
    "  code: note_conflict\n"
    '  message: "NOTE-12 has changed since you read it.\\nNothing was written."\n'
    '  arg: ""\n'
    "  attempted:\n"
    "    ref: NOTE-12\n"
    "    body: mine\n"
    "  stored:\n"
    "    ref: NOTE-12\n"
    "    body: theirs"
)
"""ADR 0009's `409`, which is the deepest object this repository emits and the one with a newline
inside a value. The newline is escaped rather than emitted raw — a raw one would end the line and
the decoder would read the remainder as a sibling entry."""

CONFLICT_ERROR = {
    "error": {
        "code": "note_conflict",
        "message": "NOTE-12 has changed since you read it.\nNothing was written.",
        "arg": "",
        "attempted": {"ref": "NOTE-12", "body": "mine"},
        "stored": {"ref": "NOTE-12", "body": "theirs"},
    }
}

GRAMMAR: list[tuple[str, object, str]] = [
    ("an empty object is the empty document", {}, ""),
    ("an empty array", [], "[]"),
    ("an empty collection is an empty array", {"notes": []}, "notes: []"),
    ("primitives inline with their count", {"tags": ["a", "b"]}, "tags[2]: a,b"),
    ("null, true and false are bare words", {"a": None, "b": True, "c": False},
     "a: null\nb: true\nc: false"),
    ("a numeric-looking string is quoted", {"ref": "12"}, 'ref: "12"'),
    ("a number is not", {"id": 12}, "id: 12"),
    ("a value containing the delimiter is quoted", {"t": "a,b"}, 't: "a,b"'),
    ("a value that looks like a literal is quoted", {"t": "null"}, 't: "null"'),
    ("a leading dash is quoted; an interior one is not", {"t": "-a b-c"}, 't: "-a b-c"'),
    ("a tab inside a value is escaped", {"t": "a\tb"}, 't: "a\\tb"'),
    ("a nested object indents by two", {"a": {"b": 1}}, "a:\n  b: 1"),
    (
        "an object of uniform objects is a keyed table",
        {"attempted": {"ref": "NOTE-12"}, "stored": {"ref": "NOTE-9"}},
        "[2:]{ref}:\n  attempted: NOTE-12\n  stored: NOTE-9",
    ),
    (
        "a non-uniform array falls back to list items",
        {"xs": [1, {"a": 2}]},
        "xs[2]:\n  - 1\n  - a: 2",
    ),
]
"""The grammar the encoder has to get right for payloads this repository does not emit *yet*.

`/links` and `/backlinks` (KAN-566) and V2b's ``summary`` will reach several of these, and a format
that only worked on today's two shapes would be discovered to be wrong by the card that first
needed it. Non-ASCII is deliberately absent from this list and tested separately below, where its
reason can be stated.
"""


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"notes": [GROCERIES, READING_LIST]}, NOTE_LIST),
        (GROCERIES, SINGLE_NOTE),
        (CONFLICT_ERROR, CONFLICT),
    ],
    ids=["note list", "note get", "the 409"],
)
def test_the_real_payloads_encode_byte_for_byte(value: object, expected: str) -> None:
    assert encode(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(value, expected) for _, value, expected in GRAMMAR],
    ids=[name for name, _, _ in GRAMMAR],
)
def test_the_grammar_encodes_byte_for_byte(value: object, expected: str) -> None:
    assert encode(value) == expected


def test_no_encoding_ends_in_a_newline() -> None:
    """``print`` adds one, exactly as it does for ``json``. Two would be a blank line between a
    payload and whatever the shell prints next, and a stripped-trailing-newline comparison in a
    consumer's test is how that becomes permanent."""
    for value in ({"notes": [GROCERIES]}, GROCERIES, CONFLICT_ERROR):
        assert not encode(value).endswith("\n")


def test_non_ascii_is_not_escaped() -> None:
    """The same argument as ``_as_json``'s ``ensure_ascii=False``: a note is prose, prose is not
    ASCII, and escaping a CJK title to ``\\uXXXX`` triples its token cost in the format whose entire
    purpose is to be cheap."""
    assert encode({"title": "咖椰吐司"}) == "title: 咖椰吐司"


# ------------------------------------------------------------------ the round trip


AWKWARD_ROWS = {
    "notes": [
        {"ref": "NOTE-1", "title": "Milk, eggs, bread", "body": "key: value\nnext"},
        {"ref": "NOTE-2", "title": "-a leading dash", "body": 'he said "hi", loudly'},
        {"ref": "NOTE-3", "title": "12", "body": ""},
    ]
}
"""A uniform table whose **cells** contain every character the row grammar depends on.

Written after a mutation showed the earlier corpus was not reaching the rule it meant to test.
Removing the delimiter check from ``_is_safe_unquoted`` reddened only the byte-for-byte corpus, not
the round trip, because the only comma-bearing value in it sat at a ``key: value`` position — where
a bare ``a,b`` decodes back to ``"a,b"`` and the round trip survives a genuinely broken encoder. A
delimiter is only ambiguous **inside a tabular row**, so that is where the corpus now puts one.

CLAUDE.md's rule, met in the wild: watch what the mutation actually reaches. A guard that fires only
through some other rule's success is not a guard over the rule you meant to test.
"""

ROUND_TRIP = [
    {"notes": [GROCERIES, READING_LIST]},
    {"notes": [GROCERIES]},
    {"notes": []},
    GROCERIES,
    READING_LIST,
    CONFLICT_ERROR,
    {"error": {"code": "note_not_found", "message": "no such note", "arg": ""}},
    *[value for _, value, _ in GRAMMAR if value != {}],
    {"awkward": ['he said "hi"', "a\\b", "line\nbreak", "  padded  ", "#hash", "[brackets]"]},
    {"numbers": [0, -1, 1.5, 1e21, 1e-7, 0.1]},
    AWKWARD_ROWS,
]


@pytest.mark.parametrize("value", ROUND_TRIP, ids=range(len(ROUND_TRIP)))
def test_every_value_survives_the_round_trip(value: object) -> None:
    """The contract SLICES §V2a states, at the encoder seam.

    Equality of *data*, not of bytes: TOON drops the quotes JSON needs, so "the same document" is
    the wrong claim and "the same data" is the right one.
    """
    assert decode(encode(value)) == value


def test_the_decoder_is_not_written_against_the_encoder() -> None:
    """Stated as an assertion so the property does not rely on a docstring nobody re-reads.

    A decoder that imported the encoder's tables — its quoting predicate, its field classifier —
    would agree with any bug in them. This one imports nothing from the package at all, so the two
    halves of the round trip are genuinely independent implementations of the same grammar.
    """
    source = (Path(__file__).parent / "toon_decode.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    assert not [name for name in imported if name.startswith("kaya_client")]
    assert imported == {"re", "typing"}


# ------------------------------------------------- the two formats describe one thing


@pytest.mark.parametrize("value", ROUND_TRIP, ids=range(len(ROUND_TRIP)))
def test_toon_and_compact_json_carry_the_same_data(value: object) -> None:
    """ADR 0005 §contract 1's "so formats cannot drift", checked value by value rather than claimed.

    The two encoders share a shaped dict and nothing else, so this is the assertion that would fail
    if one of them ever learned a rule about the payload the other did not.
    """
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    assert decode(encode(value)) == json.loads(encoded)


def test_a_value_json_cannot_serialize_is_refused_here_too() -> None:
    """Deviation 1 in `kaya_client.toon`'s docstring, and the reason it is a deviation.

    ``_as_json`` has no ``default=``, so ``json.dumps`` raises on a value outside JSON's data model.
    An encoder that stringified it instead would *succeed* where its sibling raised — drift arriving
    as a success, which is the hardest kind to notice.
    """
    with pytest.raises(TypeError, match="not JSON serializable"):
        encode({"when": object()})

    with pytest.raises(TypeError, match="not JSON serializable"):
        json.dumps({"when": object()})


def test_a_key_json_cannot_serialize_is_refused_here_too() -> None:
    with pytest.raises(TypeError, match="keys must be"):
        encode({(1, 2): "x"})


def test_an_integer_key_becomes_a_string_in_both_formats() -> None:
    """``json.dumps`` coerces it; so does this. The quoting is the encoder's, because a bare ``1``
    would read back as a number where JSON gives a string."""
    assert encode({1: "x"}) == '"1": x'
    assert json.loads(json.dumps({1: "x"})) == {"1": "x"}


def test_a_non_finite_float_is_null() -> None:
    """Deviation 2, pinned rather than left to a docstring.

    This is the one value the two formats genuinely disagree about: ``json.dumps`` writes the
    non-standard ``Infinity``, and JSON's *specification* has no such literal, so a TOON document
    containing it would read back as the string ``"Infinity"``. ``null`` is the spec-legal answer.
    Unreachable through ``KayaClient`` unless the API emits a non-standard JSON literal.
    """
    assert encode({"a": math.inf, "b": math.nan}) == "a: null\nb: null"


# --------------------------------------------------------------- through `render`


def test_render_toon_parses_back_to_the_shaped_dict(notes: Payload, note: Payload) -> None:
    """SLICES §V2a's headline: one payload, three shapes, one serializer.

    ``data`` is the shaped dict itself, so this is the strongest available statement that ``toon``
    is a *rendering* of the same thing ``json`` renders and not a second opinion about it.
    """
    for payload in (notes, note):
        encoded = render(payload, fmt="toon")
        assert isinstance(encoded, str)
        assert decode(encoded) == render(payload, fmt="data")


def test_the_three_published_formats_agree_about_the_data(notes: Payload) -> None:
    structured = render(notes, fmt="json")
    assert isinstance(structured, str)
    tabular = render(notes, fmt="toon")
    assert isinstance(tabular, str)

    assert decode(tabular) == json.loads(structured)


def test_toon_is_shorter_than_compact_json_on_a_note_list(notes: Payload) -> None:
    """The direction of the win, asserted; the size of it is measured, not asserted.

    A test that pinned a percentage would fail the first time a note in `conftest` grew a character,
    which is why `scripts/measure_toon_delta.py` reports the number into the PR body and this only
    checks the sign. On a *single* note there is no such assertion in either direction — that is the
    shape pandan measured as a small loss, and inventing a corpus where it wins would be tuning the
    measurement until it agreed.
    """
    tabular = render(notes, fmt="toon")
    structured = render(notes, fmt="json")
    assert isinstance(tabular, str) and isinstance(structured, str)

    assert len(tabular) < len(structured)
