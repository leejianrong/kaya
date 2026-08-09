"""The ``summary`` (KAN-548): what it counts, what it costs, and what it refuses to know.

This file is what `test_shaping_order.py`'s ``test_v2a_attaches_no_aggregate`` used to say. V2a
pinned that this step attached ``None`` so its arrival would be a diff somebody could date; the diff
is that assertion becoming a count and this file appearing.

Three claims, in the order ADR 0005 §contract 5 makes them:

1. **the returned set, never a corpus.** Asserted twice, at two different strengths — once on data
   (a payload built from a slice of a larger corpus counts the slice) and once structurally (the
   function takes one parameter, so there is nowhere for a corpus to enter). The second is the one
   that survives a refactor.
2. **one dict, two renderings.** The human footer is parsed back out and compared with the number a
   structured consumer receives, for every corpus size, so a second computation could not hide.
3. **attached after truncation, and unaffected by it.** The type chain in `test_shaping_order.py` is
   why this is structural; the tests here are why it is also observable.
"""

import inspect
import json
from typing import Any

import pytest
from conftest import GROCERIES, READING_LIST, note_collection, note_entity, without_help
from toon_decode import decode as decode_toon

from kaya_client import (
    COUNT_KEY,
    Payload,
    Shaped,
    UsageError,
    attach_summary,
    render,
    serialize,
    summary_line,
)

CORPUS: list[dict[str, Any]] = [
    {**GROCERIES, "ref": f"NOTE-{index}", "id": index, "title": f"Note {index}"}
    for index in range(1, 41)
]
"""Forty notes standing in for what a caller *has*, so a test can hand `render` three of them and
assert the summary describes the three. Nothing in this package can see this list, which is the
point: the only way a `40` could reach a summary is if somebody put it there on purpose."""


# ----------------------------------------------------------- the returned set, not the corpus


@pytest.mark.parametrize("size", [1, 2, 3, 17, 40])
def test_the_summary_counts_the_returned_slice_and_not_the_corpus(size: int) -> None:
    """SLICES §V2b: "the aggregate matches the rows actually returned … rather than the whole
    corpus". ``CORPUS`` has forty notes in it and the payload has ``size``; a summary reporting
    anything but ``size`` is describing something it was never handed.
    """
    rendered = render(note_collection(*CORPUS[:size]), fmt="data")
    assert isinstance(rendered, dict)
    assert rendered["summary"] == {COUNT_KEY: size}


def test_a_total_has_nowhere_to_enter_from(notes: Payload) -> None:
    """The structural half, and the one the ``[mutate]`` line is really about.

    "Describes the returned set" is only a promise while a corpus total is *unreachable* from inside
    the function. ``attach_summary`` takes exactly one parameter, so a summary that reported a total
    would have to widen this signature first — a visible thing to do in review, and something
    `render` cannot supply anyway without ADR 0005's frozen signature moving. Asserted on the
    signature rather than on a number, because a number can be made to agree by coincidence.
    """
    parameters = list(inspect.signature(attach_summary).parameters)
    assert parameters == ["payload"]
    assert attach_summary(notes).summary == {COUNT_KEY: 2}


def test_the_count_is_not_a_constant() -> None:
    """The cheapest mutation this pins: ``{"count": 2}`` written out instead of computed.

    The fixture corpus has two notes in it, so an implementation that hard-codes the fixture's own
    answer passes every test written against ``notes`` alone.
    """
    counts = {len(CORPUS[:size]): _count(render(note_collection(*CORPUS[:size]), fmt="data"))
              for size in (1, 5, 40)}
    assert counts == {1: 1, 5: 5, 40: 40}


# -------------------------------------------------------------------- one dict, two renderings


@pytest.mark.parametrize("size", [1, 2, 3, 40])
def test_the_human_footer_and_the_structured_object_report_one_number(size: int) -> None:
    """Contract 5's "both from the same dict", asserted as the number a reader would compare.

    The footer is parsed back to an integer and checked against ``summary.count``. Two computations
    could agree on the two-note fixture by luck; they cannot agree across four corpus sizes without
    being the same computation, which they are — `aggregates.summary_line` reads the mapping.
    """
    payload = note_collection(*CORPUS[:size])
    # KAN-550 put a `help:` block under the footer, so the last block is no longer the footer.
    human = without_help(render(payload))

    footer = human.split("\n\n")[-1]
    assert int(footer.split()[0]) == _count(render(payload, fmt="data")) == size


def test_the_footer_is_a_block_under_the_table_and_not_another_row(notes: Payload) -> None:
    """A blank line, so a consumer splitting on newlines does not read ``2 notes`` as a third note.

    The same device `_entity` uses for a note's prose and `truncation` for its hint.
    """
    rendered = without_help(render(notes))
    table, footer = rendered.split("\n\n")

    assert len(table.splitlines()) == 2
    assert footer == "2 notes"


def test_one_note_is_singular_and_two_are_plural() -> None:
    """The wording comes from the payload's own ``noun`` and ``envelope_key``, not from an ``-s``.

    `KayaClient` attached both at the call, so a future envelope whose plural is irregular is right
    without this function learning any English.
    """
    assert without_help(render(note_collection(GROCERIES))).endswith("\n\n1 note")
    assert without_help(render(note_collection(GROCERIES, READING_LIST))).endswith("\n\n2 notes")


def test_the_summary_reaches_every_structured_format(notes: Payload) -> None:
    """json, toon and data carry the same object; only ``human`` renders it as a sentence."""
    as_json = render(notes, fmt="json")
    as_toon = render(notes, fmt="toon")
    assert isinstance(as_json, str) and isinstance(as_toon, str)

    assert json.loads(as_json)["summary"] == {COUNT_KEY: 2}
    assert decode_toon(as_toon)["summary"] == {COUNT_KEY: 2}
    assert _count(render(notes, fmt="data")) == 2


def test_toon_still_round_trips_with_a_summary_beside_the_rows(notes: Payload) -> None:
    """A mixed document — a tabular array *and* a keyed object — which the note payloads did not
    exercise before this card. SLICES §V2a's round-trip contract has to survive the new shape."""
    assert decode_toon(str(render(notes, fmt="toon"))) == json.loads(str(render(notes, fmt="json")))


# --------------------------------------------------------------------------- what it costs


def test_the_summary_is_exactly_one_key(notes: Payload) -> None:
    """A literal, so a second key is a **conscious edit** rather than a helpful addition.

    Every key here is paid for on every list read by every consumer — which is the cost this whole
    package exists to fight — so `aggregates`' docstring has to argue for one before it appears, the
    same way `test_the_published_cli_vocabulary_is_pinned` makes publishing a format deliberate.
    """
    summary = render(notes, fmt="data")["summary"]  # type: ignore[index]
    assert summary == {"count": 2}
    assert list(summary) == ["count"]


def test_the_summary_sits_beside_the_envelope_and_is_not_a_record_key(notes: Payload) -> None:
    """It is a fact about the response, not about a note, so no record gains a key.

    That is also why ``--fields summary`` is an unknown field: the vocabulary is derived from the
    records, and the summary is not in one.
    """
    rendered = render(notes, fmt="data")
    assert isinstance(rendered, dict)
    assert set(rendered) == {"notes", "summary"}
    assert all("summary" not in record for record in rendered["notes"])

    with pytest.raises(UsageError, match="unknown field 'summary'"):
        render(notes, fields=["summary"])


# ------------------------------------------------------------------------- the zero state


def test_an_empty_result_still_prints_a_definitive_zero_state() -> None:
    """SLICES §V2b, and unchanged by this card: ``no notes``, with no ``0 notes`` under it.

    That sentence *is* the rendering of ``count: 0`` — a definitive zero state rather than an empty
    string, which is indistinguishable from a crashed pipe — and a footer repeating it in digits
    would be the same fact twice in two spellings.
    """
    assert without_help(render(note_collection())) == "no notes"
    assert summary_line(attach_summary(note_collection())) is None


def test_the_structured_zero_state_still_carries_the_count() -> None:
    """An object has no room for a sentence, and a missing ``summary`` key is ambiguous: a consumer
    could not tell an empty result from a kaya that predates aggregates."""
    assert render(note_collection(), fmt="data") == {"notes": [], "summary": {COUNT_KEY: 0}}


# ------------------------------------------------------------------- an entity has no set


def test_a_single_note_gets_no_summary(note: Payload) -> None:
    """A summary describes a returned *set*, and one note is not a set of anything.

    ``count: 1`` on every `note get` ever made would be tokens spent to say nothing.
    `test_human_row_is_pinned.py`'s ``SINGLE_NOTE`` is the byte-level witness, deliberately
    untouched by this card.
    """
    assert attach_summary(note).summary is None
    assert "summary" not in render(note, fmt="data")  # type: ignore[operator]
    assert not str(render(note)).endswith("1 note")


def test_the_entity_has_no_footer_even_with_a_hand_built_summary(note: Payload) -> None:
    """`serialization._entity` never asks for one, so a `Shaped` built by hand cannot smuggle a
    footer onto a single note through the serializer."""
    rendered = serialize(Shaped(payload=note, summary={COUNT_KEY: 1}), "human")
    assert isinstance(rendered, str)
    assert not rendered.endswith("1 note")


# --------------------------------------------------------- after truncation, and unmoved by it


@pytest.mark.parametrize("text_limit", [0, 1, 10, 500])
def test_the_count_is_unaffected_by_truncation(text_limit: int) -> None:
    """ADR 0005: "``summary`` is attached **after** truncation, so its counts are structurally out
    of the truncator's reach". Every body here is far over every limit, so a count derived from
    truncated content — only the records that survived, only the ones still under the limit — would
    move with the limit. It does not.
    """
    long_notes = [{**note, "body": "x" * 4_000} for note in CORPUS[:6]]
    payload = note_collection(*long_notes)

    assert _count(render(payload, text_limit=text_limit, fmt="data")) == 6


def test_truncation_cannot_see_a_summary_to_count_from() -> None:
    """The structural statement of the line above, restated on this card's own payload.

    `test_shaping_order.py` owns the type chain; this asserts the consequence a reader cares about —
    that the truncated and untruncated renders of the same payload report the same number, and that
    the hint the truncator added is not itself counted as anything.
    """
    payload = note_collection(*[{**note, "body": "y" * 900} for note in CORPUS[:4]])
    cut = render(payload, text_limit=100, fmt="data")
    whole = render(payload, text_limit=0, fmt="data")
    assert isinstance(cut, dict) and isinstance(whole, dict)

    assert cut["summary"] == whole["summary"] == {COUNT_KEY: 4}
    assert "truncated" in cut["notes"][0]["body"]
    assert "truncated" not in whole["notes"][0]["body"]


# ------------------------------------------------------------------ the --fields interaction


def test_projection_does_not_change_the_count(notes: Payload) -> None:
    """``--fields`` narrows keys, not rows, so a summary counting rows is unaffected by it.

    Worth an assertion rather than an argument: the count is computed after projection as well as
    after truncation, so an implementation that counted *fields* — or that counted records whose
    projection came back non-empty — would be wrong here and nowhere else.
    """
    for fields in (["ref"], ["ref", "title"], ["id", "created_at"]):
        assert _count(render(notes, fields=fields, fmt="data")) == 2
        assert without_help(render(notes, fields=fields)).endswith("\n\n2 notes")


def test_a_narrowed_read_still_carries_the_summary_beside_the_envelope(notes: Payload) -> None:
    assert render(notes, fields=["ref"], fmt="data") == {
        "notes": [{"ref": "NOTE-12"}, {"ref": "NOTE-3"}],
        "summary": {COUNT_KEY: 2},
    }


def test_an_empty_narrowed_read_is_still_the_zero_state() -> None:
    """The composition of two rules from two cards: an empty payload validates no vocabulary
    (KAN-546) and its zero state is a sentence rather than a footer (this one)."""
    assert without_help(render(note_collection(), fields=["ref", "anything"])) == "no notes"


# --------------------------------------------------------------------------- the type chain


def test_attach_summary_refuses_anything_already_shaped(notes: Payload) -> None:
    """Step 3 accepts step 2's output and nothing else, so the pipeline cannot be re-entered."""
    with pytest.raises(TypeError, match="step 3"):
        attach_summary(attach_summary(notes))  # type: ignore[arg-type]


def test_summary_line_reads_the_mapping_rather_than_the_records(notes: Payload) -> None:
    """The mechanism behind "one dict, two renderings", asserted directly: hand `summary_line` a
    ``Shaped`` whose summary disagrees with its records and the *summary* is what is printed.

    Not a supported state — nothing constructs one — but it is the difference between a line
    derived from the dict and a line that recounts and happens to agree.
    """
    assert summary_line(Shaped(payload=notes, summary={COUNT_KEY: 9})) == "9 notes"
    assert summary_line(Shaped(payload=notes, summary=None)) is None


def test_an_entity_payload_never_reaches_the_plural(note: Payload) -> None:
    assert summary_line(attach_summary(note)) is None
    assert summary_line(attach_summary(note_entity(READING_LIST))) is None


def _count(rendered: object) -> int:
    assert isinstance(rendered, dict)
    return int(rendered["summary"][COUNT_KEY])
