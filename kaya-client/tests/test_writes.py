"""The four write methods (KAN-551), against an ``httpx.MockTransport``. No network, no PAT.

What this file is about is **what goes on the wire**, because that is where every one of this
card's rules lives: an omitted field must be absent rather than ``null``, a ref must reach the API
in the spelling the caller used, ADR 0009's precondition must survive to the microsecond, and
`move` must be indistinguishable from `edit --path`. Each of those is invisible in the returned
payload and obvious in the request.
"""

import json

import httpx
import pytest
from conftest import GROCERIES

from kaya_client import ApiError, Kind, UsageError
from kaya_client.client import NOTE_COLUMNS, NOTES_PATH, KayaClient

BASE_URL = "https://kaya.example"
TOKEN = "kanban_pat_notarealtokenatall"

PRECISE = "2026-08-09T11:02:33.123456+00:00"
"""``updated_at`` with microseconds, which is the whole precision budget ADR 0009 has. A round
number here would pass against a client that truncated to the second."""


def recorder(status: int = 200, body: object = GROCERIES):
    """A handler keeping every request, so a test asserts on the bytes rather than on the call."""
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if status == 204:
            return httpx.Response(204)
        return httpx.Response(status, json=body)

    handle.seen = seen  # type: ignore[attr-defined]
    return handle


def client_over(handler: object) -> KayaClient:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    return KayaClient(BASE_URL, TOKEN, client=httpx.Client(transport=transport))


def sent(handler) -> dict:
    return json.loads(handler.seen[0].content)


# ------------------------------------------------------------------------------ create


def test_create_posts_to_the_collection() -> None:
    handler = recorder(201)
    with client_over(handler) as client:
        client.create_note("Groceries")

    assert (handler.seen[0].method, handler.seen[0].url.path) == ("POST", NOTES_PATH)


def test_create_sends_only_what_was_supplied() -> None:
    """``{"title": "…"}`` is a complete creation — ``body`` and ``path`` have server defaults, and
    letting the database supply them is not the same as this client guessing ``""``."""
    handler = recorder(201)
    with client_over(handler) as client:
        client.create_note("Groceries")

    assert sent(handler) == {"title": "Groceries"}


def test_create_sends_a_body_and_a_path_when_given() -> None:
    handler = recorder(201)
    with client_over(handler) as client:
        client.create_note("Groceries", body="milk\neggs", path="home/groceries.md")

    assert sent(handler) == {
        "title": "Groceries",
        "body": "milk\neggs",
        "path": "home/groceries.md",
    }


def test_an_empty_string_is_a_value_and_is_sent() -> None:
    """``""`` clears a field and ``None`` omits it. `NoteUpdate` documents that distinction and
    refuses a literal ``null``, so a client that collapsed the two would produce a `422` for the
    caller who meant to clear something."""
    handler = recorder(201)
    with client_over(handler) as client:
        client.create_note("Groceries", body="")

    assert sent(handler) == {"title": "Groceries", "body": ""}


def test_no_write_ever_sends_a_null() -> None:
    """The one thing `NoteUpdate._reject_explicit_nulls` is guaranteed to `422`."""
    handler = recorder(201)
    with client_over(handler) as client:
        client.create_note("Groceries")
        client.update_note("NOTE-12", title="New")

    assert all(None not in json.loads(request.content).values() for request in handler.seen)


def test_create_returns_the_note_as_an_entity() -> None:
    handler = recorder(201)
    with client_over(handler) as client:
        payload = client.create_note("Groceries")

    assert payload.kind is Kind.ENTITY
    assert payload.columns == NOTE_COLUMNS
    assert payload.record["ref"] == "NOTE-12"


def test_create_without_a_title_is_a_usage_error() -> None:
    """Reachable in code (an MCP call), not from argv, where argparse refuses first."""
    with client_over(recorder(201)) as client, pytest.raises(UsageError):
        client.create_note(None)  # type: ignore[arg-type]


def test_create_sends_a_team_id_when_given() -> None:
    """ADR 0011/R16.6. The same omit-rather-than-null rule as `body`/`path`."""
    handler = recorder(201)
    with client_over(handler) as client:
        client.create_note("Groceries", team_id=501)

    assert sent(handler) == {"title": "Groceries", "team_id": 501}


def test_no_team_id_is_the_pre_r16_request_byte_for_byte() -> None:
    handler = recorder(201)
    with client_over(handler) as client:
        client.create_note("Groceries")

    assert sent(handler) == {"title": "Groceries"}, "team_id must not appear at all when omitted"


def test_a_created_notes_team_id_reaches_the_payload_record() -> None:
    """`_note` passes the API's response through unchanged — no transformation drops or renames a
    field, `team_id` included. `field_names()` (kaya_client.payloads) is what turns this into a
    `--fields team_id` a caller can actually ask for."""
    handler = recorder(201, body={**GROCERIES, "team_id": 501})
    with client_over(handler) as client:
        payload = client.create_note("Groceries", team_id=501)

    assert payload.record["team_id"] == 501
    assert "team_id" not in payload.columns, "default row stays narrow; ask for it with --fields"


# -------------------------------------------------------------------------------- edit


def test_edit_patches_the_named_note() -> None:
    handler = recorder()
    with client_over(handler) as client:
        client.update_note("NOTE-12", title="New")

    assert (handler.seen[0].method, handler.seen[0].url.path) == ("PATCH", f"{NOTES_PATH}/NOTE-12")


def test_edit_sends_only_the_fields_it_was_given() -> None:
    """Omitted means unchanged. A `PATCH` that helpfully resent the whole note would blank whatever
    the caller had not read — the silent prose loss ADR 0009 exists to close, from the other end."""
    handler = recorder()
    with client_over(handler) as client:
        client.update_note("NOTE-12", body="new body")

    assert sent(handler) == {"body": "new body"}


def test_edit_with_nothing_to_change_is_a_usage_error_and_makes_no_request() -> None:
    """The API would accept it as a legal no-op and answer `200`, which from a CLI is a write that
    reports success for an edit nobody made. Refused here so both adapters inherit the refusal."""
    handler = recorder()
    with client_over(handler) as client, pytest.raises(UsageError, match="title, body, path"):
        client.update_note("NOTE-12")

    assert handler.seen == []


def test_the_precondition_is_forwarded_as_the_caller_wrote_it() -> None:
    """ADR 0009's token is compared exactly, to the microsecond. Nothing in this client parses it,
    which is what makes "no precision is lost" a property of the code rather than of a format."""
    handler = recorder()
    with client_over(handler) as client:
        client.update_note("NOTE-12", body="new", if_updated_at=PRECISE)

    assert sent(handler)["if_updated_at"] == PRECISE


def test_omitting_the_precondition_omits_the_key() -> None:
    """A write without one is a plain overwrite *by specification*, and ``"if_updated_at": null``
    is refused by the schema rather than read as "no precondition" — so the key must be absent."""
    handler = recorder()
    with client_over(handler) as client:
        client.update_note("NOTE-12", body="new")

    assert "if_updated_at" not in sent(handler)


def test_a_stale_precondition_arrives_as_a_409_carrying_both_versions() -> None:
    """ADR 0009's `409` puts two whole notes in the error object, and `ApiError` forwards the body
    unflattened so an adapter can diff them. An exception that kept only code and message would
    drop the half of the response the caller acts on."""
    conflict = {
        "error": {
            "code": "note_conflict",
            "message": "NOTE-12 has changed since you read it. Nothing was written.",
            "attempted": {**GROCERIES, "body": "mine"},
            "stored": {**GROCERIES, "body": "theirs"},
        }
    }
    with client_over(recorder(409, conflict)) as client, pytest.raises(ApiError) as raised:
        client.update_note("NOTE-12", body="mine", if_updated_at=PRECISE)

    assert raised.value.status == 409
    assert raised.value.payload["error"]["attempted"]["body"] == "mine"
    assert raised.value.payload["error"]["stored"]["body"] == "theirs"


# -------------------------------------------------------------------------------- move


def test_move_and_edit_put_identical_bytes_on_the_wire() -> None:
    """ADR 0008: moving a note **is** a `PATCH` to one column, so `move` is sugar and must stay
    sugar. This is the assertion that would redden the day somebody "backs it properly" with a
    second endpoint, which is the thing that ADR refuses.
    """
    moved = recorder()
    with client_over(moved) as client:
        client.move_note("NOTE-12", "archive/2026.md")

    edited = recorder()
    with client_over(edited) as client:
        client.update_note("NOTE-12", path="archive/2026.md")

    assert moved.seen[0].method == edited.seen[0].method
    assert moved.seen[0].url.raw_path == edited.seen[0].url.raw_path
    assert moved.seen[0].content == edited.seen[0].content


def test_move_sends_only_the_path() -> None:
    handler = recorder()
    with client_over(handler) as client:
        client.move_note("NOTE-12", "archive/2026.md")

    assert sent(handler) == {"path": "archive/2026.md"}


# ------------------------------------------------------------------------------ delete


def test_delete_calls_the_route_and_reports_the_deletion() -> None:
    """A `204` has no body, and an adapter printing nothing would emit the empty string — the same
    "indistinguishable from a crashed pipe" argument `serialization._rows` makes for ``no notes``.
    """
    handler = recorder(204)
    with client_over(handler) as client:
        payload = client.delete_note("NOTE-12")

    assert (handler.seen[0].method, handler.seen[0].url.path) == ("DELETE", f"{NOTES_PATH}/NOTE-12")
    assert payload.kind is Kind.ENTITY
    assert payload.record == {"ref": "NOTE-12", "deleted": True}


def test_delete_reports_the_ref_the_caller_used() -> None:
    """A `204` carries nothing to canonicalise from, and a second request made only to tidy the
    output would be a request. ``12`` is accepted back by the one resolver (ADR 0008)."""
    with client_over(recorder(204)) as client:
        payload = client.delete_note("12")

    assert payload.record["ref"] == "12"


# --------------------------------------------------------- the ref, on every method


@pytest.mark.parametrize(
    ("verb", "arguments"),
    [
        ("get_note", ()),
        ("update_note", ()),
        ("move_note", ("archive.md",)),
        ("delete_note", ()),
    ],
)
@pytest.mark.parametrize(
    ("ref", "raw_path"),
    [
        ("NOTE-12", f"{NOTES_PATH}/NOTE-12"),
        ("note-12", f"{NOTES_PATH}/note-12"),
        ("12", f"{NOTES_PATH}/12"),
        ("#NOTE-12", f"{NOTES_PATH}/%23NOTE-12"),
        ("a/b", f"{NOTES_PATH}/a%2Fb"),
    ],
)
def test_every_ref_taking_method_sends_one_encoded_segment(
    verb: str, arguments: tuple, ref: str, raw_path: str
) -> None:
    """KAN-541 fixed this on `get_note` alone; KAN-551 added three more methods that could each
    have re-broken it. They share ``_note_path``, and this is what says so.

    ``#NOTE-12`` is the spelling that must **fail**, and it must fail at the API: ADR 0008 makes it
    a `400` from the one resolver, and a client that interpolated the ref raw would send an empty
    segment plus a fragment that never leaves the machine — a `404`, or worse a success, where a
    designed `400` belongs. ``update_note`` gets a title so it has something to change.
    """
    handler = recorder(204 if verb == "delete_note" else 200)
    keywords = {"title": "x"} if verb == "update_note" else {}
    with client_over(handler) as client:
        getattr(client, verb)(ref, *arguments, **keywords)

    assert handler.seen[0].url.raw_path.decode() == raw_path


# ---------------------------------------------------------------- what must not leak


def test_no_write_puts_the_bearer_or_the_body_in_a_failure_message() -> None:
    """The bearer, because ADR 0002's whole bargain is that kaya holds no replayable credential and
    an exception string reaches stdout under the CLI's error contract. The body, for the weaker but
    real reason that it is the user's prose and a refusal is not a place to reprint it."""
    secret_body = "the quick brown fox jumped over the lazy dog"
    with client_over(recorder(500, {"nope": True})) as client, pytest.raises(ApiError) as raised:
        client.create_note("Groceries", body=secret_body)

    reported = f"{raised.value} {raised.value.payload}"
    assert TOKEN not in reported
    assert secret_body not in reported
