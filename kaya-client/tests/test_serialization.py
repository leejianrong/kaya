"""The ``fmt`` dimension — the one V2a actually implements — and what ``-> str | dict`` means.

ADR 0004 types the seam ``str | dict`` and names three formats, all of them strings, which leaves
the ``dict`` arm unspelled. It is spelled ``data``, and both halves of the union are pinned here so
an adapter can rely on the type without an ``isinstance`` at every call site.

The formats prove themselves by **round-trip equality against the same payload** rather than by
golden strings wherever that is possible (PLAN §Testing approach, seam 1). ``human`` is the
exception, and its golden strings live in `test_human_row_is_pinned.py` because that pin is the
slice's deliverable rather than a convenience.
"""

import json

import pytest
from conftest import GROCERIES, READING_LIST

from kaya_client import Format, Payload, Shaped, UnknownFormat, render, serialize

STRING_FORMATS = ["human", "json"]


def test_data_returns_the_shaped_dict_itself(notes: Payload) -> None:
    """The ``dict`` arm of the union, and the reason V6's MCP adapter never needs ``json.loads``."""
    assert render(notes, fmt="data") == {"notes": [GROCERIES, READING_LIST]}


def test_data_reproduces_the_api_envelope(notes: Payload, note: Payload) -> None:
    """A collection keeps ``{"notes": [...]}``; a single read is the bare object.

    That is PLAN §Implementation decisions' fixed shape, not a choice made in this package, and
    keeping it means `--format json` output can be read by anything already written against the
    API's own contract.
    """
    assert set(render(notes, fmt="data")) == {"notes"}  # type: ignore[arg-type]
    assert render(note, fmt="data") == GROCERIES


def test_no_summary_key_exists_yet(notes: Payload) -> None:
    """V2a attaches no aggregate. When V2b does, this assertion is the one that says so."""
    assert "summary" not in render(notes, fmt="data")  # type: ignore[operator]


@pytest.mark.parametrize("fmt", STRING_FORMATS)
def test_every_other_format_returns_a_string(notes: Payload, fmt: str) -> None:
    assert isinstance(render(notes, fmt=fmt), str)


def test_only_data_returns_a_dict(notes: Payload) -> None:
    assert isinstance(render(notes, fmt="data"), dict)


def test_json_parses_back_to_exactly_the_shaped_dict(notes: Payload, note: Payload) -> None:
    """One serializer, so the string format and the structured format cannot drift (ADR 0005 §1)."""
    for payload in (notes, note):
        encoded = render(payload, fmt="json")
        assert isinstance(encoded, str)
        assert json.loads(encoded) == render(payload, fmt="data")


def test_json_is_compact(notes: Payload) -> None:
    """No ``indent``, no space after a separator.

    Pandan measured pretty-printing at 16% of a 44,902-token payload. ``human`` is what a person
    reads; ``json`` goes to `jq` or to a parser, and 16% for whitespace nobody looks at is the wrong
    trade in the package whose whole purpose is that number.
    """
    encoded = render(notes, fmt="json")
    assert isinstance(encoded, str)
    assert '", "' not in encoded
    assert "\n" not in encoded


def test_json_does_not_escape_non_ascii() -> None:
    """A note is prose. Escaping a CJK title triples its cost in the format meant to be cheap."""
    payload = Payload.collection(
        noun="note",
        envelope_key="notes",
        records=[{"ref": "NOTE-1", "title": "咖椰吐司", "path": ""}],
        columns=("ref", "title", "path"),
    )
    encoded = render(payload, fmt="json")
    assert isinstance(encoded, str)
    assert "咖椰吐司" in encoded


@pytest.mark.parametrize("fmt", ["toon", "yaml", "HUMAN", "", "csv"])
def test_an_unknown_format_names_what_it_knows(notes: Payload, fmt: str) -> None:
    """Including ``toon``, which is KAN-541's and is deliberately not registered as a raising stub.

    Two ways for a format to be unavailable would mean two branches in every adapter. There is one:
    it is not in the registry until 541 puts it there.
    """
    with pytest.raises(UnknownFormat) as raised:
        render(notes, fmt=fmt)
    assert "data, human, json" in str(raised.value)


def test_unknown_format_is_a_value_error(notes: Payload) -> None:
    """So an adapter maps it to ADR 0005's exit `2` (usage) without importing this package's base.
    """
    with pytest.raises(ValueError, match="unknown format"):
        render(notes, fmt="toon")


def test_the_enum_and_the_registry_agree(notes: Payload) -> None:
    """A ``Format`` member that nothing serializes would be a promise the registry does not keep."""
    for member in Format:
        assert render(notes, fmt=member) is not None


def test_serialize_refuses_an_unshaped_payload(notes: Payload) -> None:
    """The last link in the type chain that puts the aggregate out of the truncator's reach."""
    with pytest.raises(TypeError, match="attach_summary"):
        serialize(notes, "human")  # type: ignore[arg-type]


def test_a_summary_reaches_the_structured_dict_when_one_exists(notes: Payload) -> None:
    """V2b's forward compatibility, checked now while it is free.

    ``attach_summary`` returns ``None`` today, so this constructs a ``Shaped`` by hand — the point
    is that `Shaped.as_dict` already knows where an aggregate goes, so V2b computes counts and
    changes nothing about serialization.
    """
    shaped = Shaped(payload=notes, summary={"count": 2})
    assert serialize(shaped, "data") == {
        "notes": [GROCERIES, READING_LIST],
        "summary": {"count": 2},
    }
