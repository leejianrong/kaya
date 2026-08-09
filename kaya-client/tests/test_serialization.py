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
from conftest import GROCERIES, READING_LIST, note_collection

from kaya_client import (
    CLI_FORMATS,
    AdapterFormat,
    Format,
    Payload,
    Shaped,
    UnknownFormat,
    render,
    serialize,
)
from kaya_client.serialization import _SERIALIZERS

STRING_FORMATS = ["human", "json", "toon"]


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


@pytest.mark.parametrize("fmt", ["yaml", "HUMAN", "TOON", "", "csv"])
def test_an_unknown_format_names_what_it_knows(notes: Payload, fmt: str) -> None:
    """The message lists the published vocabulary, which is now three names.

    ``HUMAN`` and ``TOON`` are in the list on purpose: ``Format`` is a ``StrEnum`` of lowercase
    values and the lookup is exact, so a shouted format is a typo and must be refused like one
    rather than quietly matched.
    """
    with pytest.raises(UnknownFormat) as raised:
        render(notes, fmt=fmt)
    assert "human, json, toon" in str(raised.value)


def test_the_unknown_format_message_does_not_advertise_an_adapter_format(notes: Payload) -> None:
    """A suggestion in an error message is a contract too, and this message reaches a shell.

    A CLI user who typed ``--format hunan`` must not be told ``data`` is something they may ask for.
    That would publish an adapter-only value as a user-facing one *before* KAN-541 has written the
    flag it appears to describe, and ADR 0005's whole lesson is that an early contract cannot be
    cheaply withdrawn — pandan spent card KAN-442 withdrawing a `pdn` alias.
    """
    with pytest.raises(UnknownFormat) as raised:
        render(notes, fmt="hunan")
    assert "data" not in str(raised.value)


def test_unknown_format_is_a_value_error(notes: Payload) -> None:
    """So an adapter maps it to ADR 0005's exit `2` (usage) without importing this package's base.
    """
    with pytest.raises(ValueError, match="unknown format"):
        render(notes, fmt="hunan")


def test_data_is_registered_but_not_user_facing() -> None:
    """The split, stated as one assertion. ``data`` renders; ``data`` is not offered.

    It exists for V6's MCP adapter, which hands a host ``structuredContent``. It is not a
    ``--format`` value, and SLICES §V2a publishes exactly ``{human, json, toon}``.
    """
    assert AdapterFormat.DATA in _SERIALIZERS
    assert AdapterFormat.DATA not in CLI_FORMATS
    assert "data" not in CLI_FORMATS


def test_the_published_cli_vocabulary_is_pinned() -> None:
    """A literal, so publishing a format is a **conscious edit** rather than a side effect.

    It did its job for KAN-541: adding ``toon`` to ``Format`` reddened this line, and 541 had to
    write the tuple below out by hand and check it against SLICES §V2a's published
    ``{human, json, toon}``. Making ``data`` user-facing by accident reddens it too.

    ``human`` first: it is ``render``'s default and argparse prints ``choices`` in order.
    """
    assert CLI_FORMATS == ("human", "json", "toon")


def test_every_user_facing_format_actually_renders(notes: Payload) -> None:
    """Catches KAN-541 adding ``toon`` to ``Format`` but forgetting ``_SERIALIZERS``.

    That is the dangerous direction: argparse would accept ``--format toon`` and the render would
    then raise ``UnknownFormat`` from inside the client, which reads as a client bug rather than as
    a missing encoder.
    """
    for name in CLI_FORMATS:
        assert name in _SERIALIZERS
        assert render(notes, fmt=name) is not None


def test_every_adapter_format_actually_renders(notes: Payload) -> None:
    """The mirror image, so an ``AdapterFormat`` member cannot outrun its serializer either."""
    for member in AdapterFormat:
        assert member in _SERIALIZERS
        assert render(notes, fmt=member) is not None


def test_the_two_vocabularies_do_not_overlap() -> None:
    """One format, one audience. A value in both would make "is this published?" unanswerable."""
    assert not set(CLI_FORMATS) & {member.value for member in AdapterFormat}


def test_the_registry_is_exactly_the_two_vocabularies() -> None:
    """No format may be renderable without belonging to one audience or the other.

    A serializer registered under neither enum is reachable by string and governed by nothing — it
    would have no test above asking whether it should be advertised.
    """
    declared = {member.value for member in Format} | {member.value for member in AdapterFormat}
    assert set(_SERIALIZERS) == declared


def test_the_empty_payload_still_renders_in_every_format() -> None:
    """A zero-row list is the payload most likely to trip a width or aggregate computation.

    From the retired `test_passthrough_is_a_no_op.py`. It is a claim about ``fmt`` rather than about
    either shaping parameter, which is why it landed here and not in `test_truncation.py`.
    """
    empty = note_collection()
    for fmt in [*STRING_FORMATS, AdapterFormat.DATA.value]:
        assert render(empty, fmt=fmt) is not None


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
