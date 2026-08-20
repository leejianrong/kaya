"""``KayaClient.links`` / ``.backlinks`` and what ``render`` does with what they return — KAN-566.

Two methods, one file, because the interesting thing about them is the *difference*: they are the
first pair in this package where one call gets a new noun and the other deliberately reuses an
existing one. So the assertions come in matching halves — the URL, the payload's identity, and what
falls out of that identity when the four shaping steps run over it.

The payloads' own rules (which lookup a kind reads, what unresolved looks like) are the backend's
and are asserted in `backend/tests/unit/test_link_queries.py`. What is asserted here is everything
ADR 0004 says belongs to this package: the noun, the envelope, the columns, the prose allow-list,
and the fact that `--fields`, `--full`, the aggregate and the hints all arrive without a line
written for them.
"""

import json
from typing import Any

import httpx
import pytest
from conftest import NOTE_LIST_BODY, without_help

from kaya_client import Kind, UsageError, render
from kaya_client.client import (
    LINK_COLUMNS,
    LINK_ENVELOPE,
    LINK_NOUN,
    NOTE_ENVELOPE,
    NOTE_LIST_COLUMNS,
    NOTE_NOUN,
    NOTE_PROSE_FIELDS,
    KayaClient,
)
from kaya_client.hints import HINTS

BASE_URL = "https://kaya.example"
TOKEN = "kanban_pat_notarealtokenatall"

RESOLVED_CARD: dict[str, Any] = {
    "target_kind": "KAN",
    "target_ref": "KAN-501",
    "resolved_ref": "KAN-501",
    "title": "MCP read tools: add a fields argument",
    "column": "in_progress",
}

UNRESOLVED_CARD: dict[str, Any] = {
    "target_kind": "KAN",
    "target_ref": "KAN-999",
    "resolved_ref": None,
    "title": None,
    "column": None,
}

RENAMED_NOTE: dict[str, Any] = {
    "target_kind": "NOTE",
    "target_ref": "Old Name",
    "resolved_ref": "NOTE-7",
    "title": "New Name",
    "column": None,
}

LINKS_BODY: dict[str, Any] = {"links": [RESOLVED_CARD, UNRESOLVED_CARD, RENAMED_NOTE]}


def client_over(handler: object) -> KayaClient:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    return KayaClient(BASE_URL, TOKEN, client=httpx.Client(transport=transport))


def responder(status: int, json_body: object = None):
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=json_body)

    handle.seen = seen  # type: ignore[attr-defined]
    return handle


# --- the requests -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "body", "suffix"),
    [("links", LINKS_BODY, "/links"), ("backlinks", NOTE_LIST_BODY, "/backlinks")],
)
def test_the_sub_resource_hangs_off_the_shared_note_path(
    method: str, body: dict[str, Any], suffix: str
) -> None:
    handler = responder(200, body)
    with client_over(handler) as client:
        getattr(client, method)("NOTE-12")

    [request] = handler.seen  # type: ignore[attr-defined]
    assert request.method == "GET"
    assert request.url.raw_path.decode() == f"/api/v1/notes/NOTE-12{suffix}"


@pytest.mark.parametrize("method", ["links", "backlinks"])
@pytest.mark.parametrize(
    ("ref", "encoded"),
    [("NOTE-12", "NOTE-12"), ("note-12", "note-12"), ("12", "12"), ("#NOTE-12", "%23NOTE-12")],
)
def test_the_ref_reaches_the_api_untouched_and_encoded_as_one_segment(
    method: str, ref: str, encoded: str
) -> None:
    """Both new methods go through ``_note_path``, so they inherit KAN-541's fix rather than
    re-deriving it. ``#NOTE-12`` is the spelling that must *fail*, and it must fail at the API — a
    raw interpolation would turn it into an empty segment plus a fragment that is never sent, so the
    request would reach a different endpoint and ADR 0008's `400` would never happen.

    The suffix is what makes this worth asserting twice rather than trusting the shared helper: a
    ref encoded correctly and then concatenated wrongly is a URL neither test alone would catch.
    """
    handler = responder(200, {"links": [], "notes": []})
    with client_over(handler) as client:
        getattr(client, method)(ref)

    [request] = handler.seen  # type: ignore[attr-defined]
    assert request.url.raw_path.decode().startswith(f"/api/v1/notes/{encoded}/")


@pytest.mark.parametrize("method", ["links", "backlinks"])
def test_each_verb_makes_exactly_one_request(method: str) -> None:
    """No pre-flight read of the note itself. `/links` and `/backlinks` both answer for a ref the
    API resolves on their own behalf (ADR 0008), so fetching the note first would be a request made
    only to find out something the second request already refuses correctly."""
    handler = responder(200, {"links": [], "notes": []})
    with client_over(handler) as client:
        getattr(client, method)("NOTE-12")

    assert len(handler.seen) == 1  # type: ignore[attr-defined]


# --- links: a new noun --------------------------------------------------------------------------


def test_links_returns_a_link_collection_with_the_apis_own_envelope() -> None:
    with client_over(responder(200, LINKS_BODY)) as client:
        payload = client.links("NOTE-12")

    assert payload.kind is Kind.COLLECTION
    assert (payload.noun, payload.envelope_key) == (LINK_NOUN, LINK_ENVELOPE)
    assert payload.columns == LINK_COLUMNS
    assert [record["target_ref"] for record in payload.records] == [
        "KAN-501",
        "KAN-999",
        "Old Name",
    ]


def test_links_preserves_the_apis_order() -> None:
    """``(target_kind, target_ref)`` is the backend's order and it is deterministic there for a
    reason insertion order could not be (see ``outbound_edges``). Re-sorting here would be a second
    opinion only one of the two adapters could stay consistent with."""
    reversed_body = {"links": list(reversed(LINKS_BODY["links"]))}
    with client_over(responder(200, reversed_body)) as client:
        payload = client.links("NOTE-12")

    assert [record["target_ref"] for record in payload.records] == [
        "Old Name",
        "KAN-999",
        "KAN-501",
    ]


def test_a_link_payload_has_no_prose_fields() -> None:
    """ADR 0005's allow-list, empty because nothing in a link record is unbounded ``TEXT``. It is
    load-bearing twice: ``truncate`` returns the payload untouched at any limit, and
    `kaya_cli.__main__` skips resolving ``KAYA_MAX_TEXT_CHARS`` entirely for a payload with none —
    so a broken value in the config file cannot lock a caller out of `kaya links`."""
    with client_over(responder(200, LINKS_BODY)) as client:
        payload = client.links("NOTE-12")

    assert payload.prose_fields == frozenset()


def test_a_long_card_title_is_not_truncated_at_any_limit() -> None:
    """The behavioural half of the assertion above: a structural claim about ``prose_fields`` stays
    green while something else cuts the string, so the title is checked whole through ``render``."""
    long_title = "x" * 900
    body = {"links": [{**RESOLVED_CARD, "title": long_title}]}
    with client_over(responder(200, body)) as client:
        payload = client.links("NOTE-12")

    rendered = json.loads(str(render(payload, text_limit=10, fmt="json")))

    assert rendered["links"][0]["title"] == long_title
    assert "truncated" not in str(rendered)


def test_a_link_collection_carries_the_count_aggregate_with_the_links_plural() -> None:
    """KAN-548 for free: ``attach_summary`` reads ``len(records)`` and ``summary_line`` reads the
    payload's own ``noun``/``envelope_key``, so the wording is right without any English here."""
    with client_over(responder(200, LINKS_BODY)) as client:
        payload = client.links("NOTE-12")

    structured = json.loads(str(render(payload, fmt="json")))
    assert structured["summary"] == {"count": 3}
    assert without_help(render(payload, fmt="human")).endswith("3 links")


def test_one_link_is_the_singular() -> None:
    with client_over(responder(200, {"links": [RESOLVED_CARD]})) as client:
        payload = client.links("NOTE-12")

    assert without_help(render(payload, fmt="human")).endswith("1 link")


def test_a_note_with_no_links_is_a_definitive_zero_state() -> None:
    """``no links``, not an empty string — the same argument `serialization._rows` makes for
    ``no notes``: an empty stdout is indistinguishable from a crashed pipe."""
    with client_over(responder(200, {"links": []})) as client:
        payload = client.links("NOTE-12")

    assert render(payload, fmt="human") == "no links"
    assert json.loads(str(render(payload, fmt="json"))) == {
        "links": [],
        "summary": {"count": 0},
    }


def test_a_link_payload_gets_no_help_templates() -> None:
    """`hints.py` predicted this by name: an unknown ``(kind, noun)`` emits nothing, so a new
    envelope arrives silent rather than carrying a note's next steps. See ``KayaClient.links`` for
    why no row was added — ``note get <ref>`` would apply to some rows and not others."""
    with client_over(responder(200, LINKS_BODY)) as client:
        payload = client.links("NOTE-12")

    assert (Kind.COLLECTION, LINK_NOUN) not in HINTS
    assert "help:" not in str(render(payload, fmt="human"))


def test_fields_narrows_a_link_row_and_the_structured_keys_together() -> None:
    """KAN-546 for free. The vocabulary comes from the payload's own keys, so it is the API's five
    without a list maintained here."""
    with client_over(responder(200, LINKS_BODY)) as client:
        payload = client.links("NOTE-12")

    assert payload.field_names() == LINK_COLUMNS
    narrowed = json.loads(str(render(payload, fields=["target_ref", "resolved_ref"], fmt="json")))
    assert narrowed["links"][0] == {"target_ref": "KAN-501", "resolved_ref": "KAN-501"}


def test_an_unknown_field_on_links_is_a_usage_error_naming_it() -> None:
    """Including the one a caller would most plausibly guess: the column the payload deliberately
    does *not* publish."""
    with client_over(responder(200, LINKS_BODY)) as client:
        payload = client.links("NOTE-12")

    with pytest.raises(UsageError) as raised:
        render(payload, fields=["resolved_id"])

    assert "resolved_id" in str(raised.value)


def test_an_unresolved_row_renders_its_nulls_as_blanks_rather_than_the_word_none() -> None:
    """A `human` row is read by a person, and ``None`` in a table is Python leaking through the
    output layer. The blank is `serialization`'s existing rule for a missing column; this checks it
    covers a key that is present and ``null``, which is the shape Q26 makes routine."""
    with client_over(responder(200, {"links": [UNRESOLVED_CARD]})) as client:
        payload = client.links("NOTE-12")

    rendered = without_help(render(payload, fmt="human"))

    assert "KAN-999" in rendered
    assert "None" not in rendered


# --- backlinks: the note noun, on purpose -------------------------------------------------------


def test_backlinks_returns_a_note_collection_identical_to_a_plain_list() -> None:
    """The identity that buys everything else in this section. `/backlinks` answers with the same
    ``NoteList`` `/notes` does, so the payload is `list_notes`' payload at a different URL —
    asserted
    field by field rather than by rendering, because the point is the *shape* being the same one."""
    with client_over(responder(200, NOTE_LIST_BODY)) as client:
        backlinks = client.backlinks("NOTE-12")
    with client_over(responder(200, NOTE_LIST_BODY)) as client:
        listed = client.list_notes()

    assert backlinks.noun == NOTE_NOUN
    assert backlinks.envelope_key == NOTE_ENVELOPE
    assert backlinks.columns == NOTE_LIST_COLUMNS
    assert backlinks.prose_fields == NOTE_PROSE_FIELDS
    assert backlinks == listed


def test_a_backlinks_render_is_byte_identical_to_the_pinned_note_row() -> None:
    """The strongest form of the claim above, and the reason it is worth making: if `backlinks` ever
    grew a column, a noun or a footer of its own, this would disagree with
    `test_human_row_is_pinned.py`'s literal — which is the file that decides what a note list looks
    like."""
    with client_over(responder(200, NOTE_LIST_BODY)) as client:
        backlinks = client.backlinks("NOTE-12")
    with client_over(responder(200, NOTE_LIST_BODY)) as client:
        listed = client.list_notes()

    assert render(backlinks, fmt="human") == render(listed, fmt="human")
    assert render(backlinks, fmt="toon") == render(listed, fmt="toon")


def test_backlinks_truncates_a_body_because_a_note_has_prose() -> None:
    """The other half of inheriting the note noun: a backlinks list is a list of notes, bodies and
    all, so it pays for prose and gets KAN-547's cut and its in-band true total."""
    long_body = "y" * 900
    body = {"notes": [{**NOTE_LIST_BODY["notes"][0], "body": long_body}]}
    with client_over(responder(200, body)) as client:
        payload = client.backlinks("NOTE-12")

    rendered = json.loads(str(render(payload, fields=["ref", "body"], text_limit=100, fmt="json")))
    cut = rendered["notes"][0]["body"]

    assert cut.startswith("y" * 100)
    assert "900 chars total" in cut


def test_backlinks_carries_the_note_help_templates() -> None:
    """And it *should*: the rows are notes, so ``note get <ref>`` addresses one of them and
    ``note create <title>`` is the other thing a listing is a jumping-off point for. This is the one
    place `hints.py`'s "KAN-566 arrives with no hints" prediction does not hold, and it does not
    hold because the payload is not a new envelope at all."""
    with client_over(responder(200, NOTE_LIST_BODY)) as client:
        payload = client.backlinks("NOTE-12")

    rendered = render(payload, fmt="human")

    assert "help: kaya note get <ref>" in str(rendered)


def test_a_note_nobody_links_to_is_the_notes_zero_state() -> None:
    with client_over(responder(200, {"notes": []})) as client:
        payload = client.backlinks("NOTE-12")

    assert render(payload, fmt="human") == "no notes\n\nhelp: kaya note create <title>"
