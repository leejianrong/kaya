"""The banner, the slice, and the two properties that keep them out of ``render`` (KAN-549).

ADR 0005 §contract 7 asks for "live state", and SLICES §V2b spells it as "the executable path, a
one-line description, recent notes and the aggregate". Two of those four are a payload and go
through the one seam; two are prose about the tool and do not. This file is about the seam *between*
those halves, and it asserts three things in descending order of how easily they could rot:

1. **`overview` cannot format a result.** Its signature takes three ``str``s and no ``Payload``, so
   "``render`` is called in exactly one place in `kaya-cli`" is a claim about what is *possible*
   rather than about what somebody remembered. Asserted on the signature, the same device
   `test_aggregates.py` uses for ``attach_summary``'s arity — a number can be made to agree by
   coincidence and a parameter list cannot.
2. **The slice is the client's**, expressed as `Payload.limited_to` and applied by
   `KayaClient.recent_notes`, so what reaches `render` is an ordinary payload and ADR 0005
   §contract 5's "the returned set, not the whole corpus" is true of it without a new rule.
3. **The third banner line is static.** It names the limit and the verb that lifts it and carries no
   value taken from a payload, which is what stops a banner from becoming a second renderer one
   helpful edit at a time.
"""

import inspect

import httpx
import pytest
from conftest import GROCERIES, READING_LIST, note_collection, without_help

from kaya_client import COUNT_KEY, RECENT_NOTES, KayaClient, Kind, Payload, overview, render
from kaya_client.client import NOTE_LIST_COLUMNS, NOTE_PROSE_FIELDS
from kaya_client.overview import DESCRIPTION
from kaya_client.provenance import version_line

CORPUS = [
    {**GROCERIES, "ref": f"NOTE-{index}", "id": index, "title": f"Note {index}"}
    for index in range(1, 41)
]
"""Forty notes: what a caller *has*, against the five a bare invocation shows."""

EXECUTABLE = "/usr/local/bin/kaya"


def client(records: list[dict]) -> KayaClient:
    """A real ``KayaClient`` over a transport that answers `/api/v1/notes` with ``records``."""
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"notes": records}))
    return KayaClient(
        "https://kaya.example",
        "kanban_pat_notarealtokenatall",
        client=httpx.Client(transport=transport),
    )


# ----------------------------------------------------------------- it cannot format a payload


def test_overview_takes_three_strings_and_no_payload() -> None:
    """The structural claim, and the one this card is really about.

    A banner is the obvious place for a second rendering to appear: it is output, it sits next to a
    payload, and "show the first note's title in the header" is a reasonable-sounding request. It
    cannot be implemented here without widening this signature, which is a visible thing to do in
    review — the same argument `attach_summary`'s one parameter makes about a corpus total.
    """
    parameters = inspect.signature(overview).parameters

    assert list(parameters) == ["program", "version", "executable"]
    assert {name: parameter.annotation for name, parameter in parameters.items()} == {
        "program": str,
        "version": str,
        "executable": str,
    }


def test_the_banner_is_three_lines_and_leads_with_the_version_line() -> None:
    """ADR 0007's line first, so provenance is reachable from a mistyped command, then the path.

    "Which build" and "which copy" are one diagnostic: a sha with no path cannot tell a user which
    of two installed kayas printed it, and a path with no sha cannot tell them whether it is stale.
    """
    lines = overview("kaya", "1.2.3", EXECUTABLE).splitlines()

    assert len(lines) == 3
    assert lines[0] == version_line("kaya", "1.2.3")
    assert lines[1] == f"{EXECUTABLE} — {DESCRIPTION}."


def test_the_third_line_names_the_limit_and_the_verb_that_lifts_it() -> None:
    """Otherwise ADR 0005 §contract 5's ``5 notes`` footer reads as "you have five notes"."""
    third = overview("kaya", "1.2.3", EXECUTABLE).splitlines()[2]

    assert str(RECENT_NOTES) in third
    assert "kaya note list" in third


def test_the_banner_carries_nothing_from_any_payload() -> None:
    """The static half of claim 3, asserted as a property rather than as a reading of the string.

    Two calls with the same three arguments are byte-identical whatever notes exist, because there
    is no payload in scope for either of them. A banner that interpolated a title or a count would
    fail this the moment the corpus differed — which is exactly when a reader would be misled.
    """
    assert overview("kaya", "1.2.3", EXECUTABLE) == overview("kaya", "1.2.3", EXECUTABLE)
    assert GROCERIES["title"] not in overview("kaya", "1.2.3", EXECUTABLE)


def test_the_program_name_reaches_both_lines_that_need_it() -> None:
    """``program`` is a parameter for the same reason it is one on ``version_line``: `kaya-client`
    may not read a name out of `kaya-cli` (ADR 0004 points the arrow the other way), and V6's server
    will pass its own."""
    rendered = overview("kaya-mcp", "0.1.0", "/opt/kaya-mcp")

    assert rendered.startswith("kaya-mcp 0.1.0 (")
    assert "kaya-mcp note list" in rendered


def test_the_description_has_no_trailing_stop_so_callers_punctuate_it() -> None:
    """`kaya_cli.__main__.DESCRIPTION` appends one for argparse and the banner appends one here; a
    period baked into the constant would produce ``API-first..`` in whichever of the two lost."""
    assert not DESCRIPTION.endswith(".")


# ------------------------------------------------------------------------------- the slice


def test_limited_to_keeps_the_first_records_in_order() -> None:
    """"Recent" is the API's ordering (``updated_at DESC, id DESC``), not a second sort here."""
    limited = note_collection(*CORPUS).limited_to(5)

    assert [record["ref"] for record in limited.records] == [f"NOTE-{n}" for n in range(1, 6)]


def test_limited_to_changes_nothing_but_the_rows() -> None:
    """Keeping fewer rows says nothing about which keys exist or which of them are prose, so
    ``columns``, ``kind``, ``noun``, ``envelope_key`` and ``prose_fields`` come through untouched
    and projection and truncation still compose with the result."""
    whole = note_collection(*CORPUS)
    limited = whole.limited_to(3)

    assert limited.columns == NOTE_LIST_COLUMNS == whole.columns
    assert limited.prose_fields == NOTE_PROSE_FIELDS == whole.prose_fields
    assert limited.kind is Kind.COLLECTION
    assert (limited.noun, limited.envelope_key) == (whole.noun, whole.envelope_key)


def test_limited_to_returns_a_new_payload_and_leaves_the_complete_one_alone() -> None:
    """The same rule `narrowed_to` and `with_records` follow: the response this was called on is
    still the complete one, because anything that wants the rest has nowhere else to get it."""
    whole = note_collection(*CORPUS)
    limited = whole.limited_to(2)

    assert len(whole.records) == 40
    assert len(limited.records) == 2
    assert limited is not whole


@pytest.mark.parametrize("count", [0, 1, 5, 40, 100])
def test_a_limit_at_or_beyond_the_corpus_is_the_corpus(count: int) -> None:
    """No padding, no error, and no special case at the boundary: a caller with three notes and a
    limit of five sees three."""
    assert len(note_collection(*CORPUS).limited_to(count).records) == min(count, 40)


def test_a_negative_limit_is_a_caller_bug_and_says_so() -> None:
    """Python's ``[: -1]`` is "all but the last", which is a plausible-looking wrong answer. A
    ``ValueError`` rather than a ``KayaError``: nothing in argv can produce this, so it is a bug in
    code and belongs as a traceback rather than in ``main``'s funnel."""
    with pytest.raises(ValueError, match="0 or more"):
        note_collection(*CORPUS).limited_to(-1)


# --------------------------------------------------------------- recent_notes, through the client


def test_recent_notes_makes_one_request_and_returns_at_most_the_limit() -> None:
    """`GET /api/v1/notes` has no ``?limit=`` — paging is deferred (SLICES) — so this fetches
    everything and keeps the first few. Stated in the method's docstring rather than hidden, and
    asserted here so the day a cursor lands, the test that changes is the one that has to."""
    payload = client(CORPUS).recent_notes()

    assert len(payload.records) == RECENT_NOTES
    assert [record["ref"] for record in payload.records] == [f"NOTE-{n}" for n in range(1, 6)]


def test_recent_notes_of_a_short_corpus_is_the_whole_corpus() -> None:
    payload = client([GROCERIES, READING_LIST]).recent_notes()

    assert [record["ref"] for record in payload.records] == ["NOTE-12", "NOTE-3"]


def test_recent_notes_is_a_collection_even_with_one_row() -> None:
    """A sliced list is still a list. A payload that started behaving like `note get` because the
    slice left one row would change the summary, the hints and the human layout all at once."""
    payload = client(CORPUS).recent_notes(limit=1)

    assert payload.kind is Kind.COLLECTION
    assert isinstance(payload, Payload)


def test_the_aggregate_over_a_sliced_read_counts_the_slice() -> None:
    """ADR 0005 §contract 5's "under a filter or ``--limit``, the returned set, not the whole
    corpus", at the one place in the shipped code where the two numbers actually differ.

    Nothing in `aggregates` learned about a limit: `attach_summary` counts the records it is handed
    and the slice happened before it was handed anything, so this is a consequence of *where*
    `limited_to` is called rather than of a rule anybody wrote down.
    """
    rendered = render(client(CORPUS).recent_notes(), fmt="data")

    assert isinstance(rendered, dict)
    assert rendered["summary"] == {COUNT_KEY: RECENT_NOTES}
    assert len(rendered["notes"]) == RECENT_NOTES


def test_the_human_footer_over_a_sliced_read_says_five_not_forty() -> None:
    """The same fact as a reader meets it. ``40 notes`` under five rows is the failure this pins."""
    human = without_help(render(client(CORPUS).recent_notes()))

    assert human.endswith(f"\n\n{RECENT_NOTES} notes")
    assert "40 notes" not in human


def test_a_sliced_read_still_takes_projection_and_truncation() -> None:
    """A limited payload is an ordinary ``Payload``, so the other three V2b dimensions apply to it
    unchanged — the whole reason the slice is a payload method and not a fifth parameter."""
    rendered = render(client(CORPUS).recent_notes(), fields=["ref"], text_limit=10, fmt="data")

    assert isinstance(rendered, dict)
    assert rendered["notes"] == [{"ref": f"NOTE-{n}"} for n in range(1, 6)]


def test_an_empty_corpus_is_still_the_zero_state() -> None:
    """Nothing about the slice changes what zero notes look like: `serialization._rows`' definitive
    sentence, and no ``0 notes`` footer under it."""
    assert without_help(render(client([]).recent_notes())) == "no notes"
