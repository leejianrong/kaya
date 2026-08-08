"""``Payload`` carries the three facts V2b needs and ``render``'s signature has no room for.

ADR 0005's sequencing rule is the whole test here: if any of these were missing, V2b would have to
add a parameter to ``render`` and that is the signal the sequencing broke. So each one gets an
assertion naming the V2b requirement it unblocks.
"""

import pytest
from conftest import GROCERIES, READING_LIST, note_collection, note_entity

from kaya_client import Kind, Payload


def test_a_collection_knows_it_is_one(notes: Payload) -> None:
    """V2b: "``--fields`` … a usage error on single-entity verbs, never a silent no-op"."""
    assert notes.kind is Kind.COLLECTION


def test_an_entity_knows_it_is_one(note: Payload) -> None:
    assert note.kind is Kind.ENTITY


def test_a_one_row_collection_is_still_a_collection() -> None:
    """Not derived from ``len(records)``.

    A `list` verb that returned one note must not start behaving like `get` — which is exactly what
    a ``len(records) == 1`` heuristic would do, on the smallest board, once.
    """
    assert note_collection(GROCERIES).kind is Kind.COLLECTION


def test_the_field_vocabulary_comes_from_the_records(notes: Payload) -> None:
    """V2b: ``--fields``' vocabulary is "derived from the payload's own keys so it cannot drift".

    Order is first-seen, so an error message listing the options reads in the API's own order rather
    than alphabetically, which is how a caller would have seen them.
    """
    assert notes.field_names() == tuple(GROCERIES)


def test_the_vocabulary_is_the_union_across_rows() -> None:
    """A key present on only some rows is still askable for. Sparse rows are the API's business."""
    payload = note_collection({"ref": "NOTE-1"}, {"ref": "NOTE-2", "title": "t"})
    assert payload.field_names() == ("ref", "title")


def test_the_vocabulary_is_wider_than_the_default_row(notes: Payload) -> None:
    """The precondition for ADR 0005's "``--fields`` **widens** the human row" meaning anything."""
    assert set(notes.columns) < set(notes.field_names())


def test_the_prose_allow_list_travels_with_the_payload(notes: Payload) -> None:
    """V2b truncates over named fields, "never a length heuristic" (ADR 0005).

    Supplied by the client because it is knowledge of the API's schema — ``body`` is the one
    unbounded ``TEXT`` column in migration ``0001``.
    """
    assert notes.prose_fields == frozenset({"body"})


def test_with_columns_is_where_fields_will_land(notes: Payload) -> None:
    """V2b's widening, expressible today without touching ``render``'s signature."""
    widened = notes.with_columns(("ref", "title", "path", "updated_at"))
    assert widened.columns == ("ref", "title", "path", "updated_at")
    assert widened.records == notes.records
    assert notes.columns == ("ref", "title", "path")


def test_record_is_refused_on_a_collection(notes: Payload) -> None:
    """"The one note" is not a question a list payload can be asked."""
    with pytest.raises(ValueError, match="not a single entity"):
        _ = notes.record


def test_a_payload_copies_the_records_it_is_given() -> None:
    """The caller's dict is not the payload's dict; a later edit to one must not reach the other."""
    source = dict(READING_LIST)
    payload = note_entity(source)
    source["title"] = "clobbered"
    assert payload.record["title"] == "A reading list"
