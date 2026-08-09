"""``--fields`` (KAN-546): what it selects, in what order, and what it refuses.

This file is what `test_passthrough_is_a_no_op.py` used to say about ``fields`` and no longer does.
V2a pinned the parameter as a no-op precisely so that its arrival would be a diff somebody could
date; the diff is that file losing its ``fields`` assertions and this one appearing.

**The claim under test is that projection is uniform across formats.** ADR 0004 §Decision wants the
shaped dict narrowed (pandan's 44,902 tokens → 7,204); ADR 0005 §contract 2 wants the human row
widened. One operation satisfies both, because the default human row is narrower than the record —
so the same ``fields=["ref", "title", "path", "updated_at"]`` adds a column to the table *and*
removes three keys from the JSON. Anything conditional on ``fmt`` here would be a behavioural
difference between the CLI and MCP living inside the seam they share, which is the drift ADR 0004
exists to prevent. See ADR 0005's amendment of 2026-08-09 (KAN-546).

What is *not* here is the byte-identity of the default row with ``--fields`` omitted. That is
`test_human_row_is_pinned.py`, untouched by this card on purpose: a pin restated by the slice it is
supposed to constrain is not a pin.
"""

import json

import pytest
from conftest import GROCERIES, READING_LIST, note_collection, note_entity
from toon_decode import decode as decode_toon

from kaya_client import Payload, UsageError, error_payload, project, render

NARROW = ["ref", "title"]

WIDE = ["ref", "title", "path", "updated_at"]


# ------------------------------------------------------------------ the human row


def test_fields_widens_the_human_row(notes: Payload) -> None:
    """ADR 0005 §contract 2's own word for what this does, on the payload it was written about."""
    first, second = _lines(render(notes, fields=WIDE))

    assert first == "NOTE-12  Groceries       home/groceries.md  2026-08-09T11:02:33.123456+00:00"
    assert second.startswith("NOTE-3   A reading list")
    assert second.endswith("2026-07-14T18:00:00+00:00")


def test_fields_can_narrow_the_human_row_too(notes: Payload) -> None:
    """"Widens" is ADR 0005 describing the common case, not a constraint on the argument.

    ``--fields ref,title`` is a perfectly reasonable thing to ask a list verb for, and refusing to
    drop ``path`` because the ADR used the word "widens" would be reading a description as a rule.
    """
    assert render(notes, fields=NARROW) == "NOTE-12  Groceries\nNOTE-3   A reading list"


def test_the_order_asked_for_is_the_order_rendered(notes: Payload) -> None:
    """A permutation, because "in the order given" is invisible in any subset of the default row.

    ``path`` first also exercises the empty-value case at the *left* of a row: the second note's
    ``path`` is ``""``, so its line is padding followed by a ref, and the alignment still has to
    hold. Trailing whitespace is still forbidden — that property is `test_human_row_is_pinned`'s and
    is asserted here again over a row it never sees.
    """
    rendered = render(notes, fields=["path", "ref"])

    assert rendered == "home/groceries.md  NOTE-12\n" + " " * 19 + "NOTE-3"
    assert all(line == line.rstrip() for line in rendered.splitlines())


def test_one_field_is_a_single_column(notes: Payload) -> None:
    """The narrowest useful projection, and the one an agent asking "which notes exist?" writes."""
    assert render(notes, fields=["ref"]) == "NOTE-12\nNOTE-3"


# ---------------------------------------------------------- the structured formats


def test_json_carries_exactly_the_named_keys(notes: Payload) -> None:
    """ADR 0004's measurement, in the format it was measured on. The keys are gone, not blanked."""
    assert render(notes, fields=NARROW, fmt="json") == (
        '{"notes":[{"ref":"NOTE-12","title":"Groceries"},'
        '{"ref":"NOTE-3","title":"A reading list"}]}'
    )


def test_the_data_format_narrows_identically(notes: Payload) -> None:
    """V6's MCP ``structuredContent`` gets the projection without the adapter doing anything.

    This is the assertion that makes ADR 0004's promise concrete: `mcp/` will pass ``fields``
    straight through to ``render`` and inherit the saving, rather than filing it as a follow-up the
    way pandan's KAN-501 had to.
    """
    assert render(notes, fields=NARROW, fmt="data") == {
        "notes": [
            {"ref": "NOTE-12", "title": "Groceries"},
            {"ref": "NOTE-3", "title": "A reading list"},
        ]
    }


def test_toon_narrows_its_header_and_its_rows(notes: Payload) -> None:
    """TOON's field list *is* the projection, so a narrowed payload is a narrower header.

    Asserted through the decoder rather than as a golden string for the reason KAN-541 gave: the
    contract is that ``toon`` parses back to what ``json`` says, not that it looks a particular way.
    The header line is checked as well because it is the thing that makes TOON cheap, and a
    projected list is exactly the shape it is cheap on.
    """
    rendered = render(notes, fields=NARROW, fmt="toon")
    assert isinstance(rendered, str)

    assert rendered.splitlines()[0] == "notes[2]{ref,title}:"
    assert decode_toon(rendered) == json.loads(str(render(notes, fields=NARROW, fmt="json")))


def test_the_key_order_in_a_record_follows_the_caller(notes: Payload) -> None:
    """Not only the columns: the narrowed record's own key order is the caller's.

    A structured consumer that pretty-prints or diffs its input sees this, and a projection that
    re-imposed the API's ordering would make ``--fields title,ref`` and ``--fields ref,title``
    produce the same bytes while the human table disagreed with both.
    """
    rendered = render(notes, fields=["title", "ref"], fmt="json")
    assert isinstance(rendered, str)
    assert rendered.startswith('{"notes":[{"title":"Groceries","ref":"NOTE-12"}')


def test_projection_does_not_reach_back_into_the_payload(notes: Payload) -> None:
    """The complete records survive the projection that ignored them.

    ``--full`` (KAN-547) and ADR 0004 §Consequences both depend on the payload staying complete;
    a narrowing that edited records in place would make the untruncated text unrecoverable by the
    time anything asked for it.
    """
    render(notes, fields=NARROW, fmt="json")

    assert notes.records[0] == GROCERIES
    assert notes.columns == ("ref", "title", "path")


def test_the_prose_allow_list_survives_projection(notes: Payload) -> None:
    """KAN-547 truncates over ``prose_fields`` and KAN-550 reads it; neither runs before this step.

    It is a fact about the API's schema — which columns are unbounded ``TEXT`` — and not about what
    the caller asked to see, so narrowing it to the selection would be correct only by coincidence.
    """
    assert project(notes, ["ref"]).prose_fields == frozenset({"body"})


# ------------------------------------------------------------------- the vocabulary


def test_an_unknown_field_is_refused_by_name(notes: Payload) -> None:
    """SLICES §V2b: "unknown name → a clean error naming it".

    Both halves asserted: the name the caller got wrong, and the vocabulary they can choose from. A
    refusal carrying only "unknown field" would leave a caller guessing at exactly the thing this
    vocabulary is derived from the payload in order to be exact about.
    """
    with pytest.raises(UsageError) as refusal:
        render(notes, fields=["ref", "nope"])

    message = str(refusal.value)
    assert "'nope'" in message
    assert "a note has ref, id, title, body, path, created_at, updated_at" in message


def test_the_vocabulary_is_the_payloads_own_keys_and_not_the_default_row(notes: Payload) -> None:
    """``id`` is in no default row and is still askable for, because the API returned it.

    This is the anti-drift property stated as a test: a vocabulary written down in this package
    would have to list ``id``, and would omit whatever the next deploy adds.
    """
    assert render(notes, fields=["id"], fmt="data") == {"notes": [{"id": 12}, {"id": 3}]}


def test_the_refusal_carries_the_field_in_the_arg_slot(notes: Payload) -> None:
    """ADR 0005 §contract 3's fourth column, on the failure a caller is most likely to hit.

    ``arg`` is "the one scalar a refusal is about", and for a misspelled projection that is the
    misspelled name — so a script can correct it without parsing the message text, which contract 4
    tells consumers never to branch on.
    """
    with pytest.raises(UsageError) as refusal:
        render(notes, fields=["nope"])

    error = error_payload(refusal.value)["error"]
    assert error["code"] == "usage"
    assert error["arg"] == "nope"


def test_the_first_unknown_name_is_the_one_reported(notes: Payload) -> None:
    """One refusal names one field, in the order the caller wrote them.

    Reporting all of them would make ``arg`` ambiguous — contract 3's slot holds one scalar — and
    the caller is going to re-run the command after fixing the first anyway.
    """
    with pytest.raises(UsageError, match="'aaa'"):
        render(notes, fields=["aaa", "bbb"])


def test_an_empty_result_accepts_any_field_and_still_says_so() -> None:
    """A `note list` that came back empty has no vocabulary, so it validates nothing.

    Refusing ``--fields ref`` here would report the caller's spelling as wrong on the evidence of
    somebody else's data — the corpus being empty is not information about the request — and the
    definitive zero state is the right answer to the question either way.
    """
    assert render(note_collection(), fields=["ref", "anything"]) == "no notes"


def test_a_field_missing_from_one_row_is_a_hole_rather_than_a_refusal() -> None:
    """The precedent is `test_a_missing_column_renders_blank_rather_than_raising`, one row over.

    ``field_names`` is the union across rows (sparse rows are the API's business), so a name that is
    legal for the payload may still be absent from an individual record. Blank cell, no key in the
    structured output, no traceback.
    """
    thin = {key: value for key, value in READING_LIST.items() if key != "path"}
    payload = note_collection(GROCERIES, thin)

    assert render(payload, fields=["ref", "path"]) == "NOTE-12  home/groceries.md\nNOTE-3"
    assert render(payload, fields=["ref", "path"], fmt="data") == {
        "notes": [{"ref": "NOTE-12", "path": "home/groceries.md"}, {"ref": "NOTE-3"}]
    }


# ----------------------------------------------------------------- what it refuses


def test_fields_on_a_single_entity_is_a_usage_error(note: Payload) -> None:
    """ADR 0005 §contract 2: "a usage error on single-entity verbs, **never a silent no-op**".

    The requirement `Payload.kind` exists to answer, and the one ADR 0004's amendment says would
    have forced a fifth parameter on ``render`` had the client returned a raw dict.
    """
    with pytest.raises(UsageError, match="single record"):
        render(note, fields=["ref"])


def test_the_entity_refusal_is_not_derived_from_the_row_count() -> None:
    """A one-note *list* is still a list, and ``--fields`` applies to it.

    The tempting implementation refuses whatever has one record, which works until the smallest
    account runs `note list` — the same trap `Payload.kind` is not derived from ``len(records)``
    for.
    """
    assert render(note_collection(GROCERIES), fields=["ref"]) == "NOTE-12"


def test_an_entity_is_refused_before_the_spelling_is_checked() -> None:
    """``note get 12 --fields nope`` has one thing wrong with it and it is not the spelling.

    Checking the vocabulary first would send the caller to fix a name on a verb that will refuse the
    parameter however it is spelled, which is two round trips to learn one thing.
    """
    with pytest.raises(UsageError, match="single record"):
        render(note_entity(GROCERIES), fields=["nope"])


def test_a_duplicated_name_selects_the_column_once(notes: Payload) -> None:
    """``--fields ref,ref`` is one column, first occurrence winning.

    A record is a dict and cannot hold ``ref`` twice, so the duplicate is unrepresentable in every
    structured format. Printing it twice under ``human`` would be the formats disagreeing about one
    argument — the drift the uniform rule is here to prevent — and refusing it outright would be a
    usage error over something with an obvious, harmless meaning.
    """
    assert render(notes, fields=["ref", "ref"]) == render(notes, fields=["ref"])
    assert render(notes, fields=["title", "ref", "title"], fmt="data") == render(
        notes, fields=["title", "ref"], fmt="data"
    )


def test_selecting_no_fields_at_all_is_a_usage_error(notes: Payload) -> None:
    """``fields=[]`` is "select nothing", which is a different request from "do not project".

    Unreachable from argv — splitting any string yields at least one segment — so this is the
    in-code caller, i.e. V6's MCP server. The alternative is a payload whose records have no keys,
    which renders as blank lines and carries no information at all; treating it as ``None`` instead
    would make an empty tool argument silently mean "the default row".
    """
    with pytest.raises(UsageError, match="no columns"):
        render(notes, fields=[])


def test_an_empty_name_is_an_unknown_field_rather_than_a_shrug(notes: Payload) -> None:
    """What ``--fields ""`` and ``--fields ref,,title`` reach the client as.

    The adapter splits and does not filter (ADR 0004 leaves it one job), so an empty segment arrives
    as an empty *name*. It is not in any vocabulary, so it is refused like any other unknown name —
    which is the behaviour that tells the caller their comma was wrong.
    """
    with pytest.raises(UsageError, match="unknown field ''"):
        render(notes, fields=[""])


def _lines(rendered: str | dict[str, object]) -> list[str]:
    assert isinstance(rendered, str)
    return rendered.splitlines()
