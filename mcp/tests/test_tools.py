"""Each of the six tools, called through `MCPServer.call_tool` — argument validation, the
`kaya_mcp.tools` body and `render()`. Nothing here mocks anything below the HTTP boundary: only
the socket is fake (`conftest.fake_api`/`answering`).

**`call_tool` is the SDK's convenience wrapper, not the JSON-RPC dispatch path** — read from the
installed package while writing this suite: `MCPServer._handle_call_tool` is what catches a raised
exception and returns `CallToolResult(is_error=True, ...)`, and `call_tool` is one layer below
that, so a failure here surfaces as a **raised** `ToolError` rather than a returned result. That
is still exactly what `kaya_mcp.server._fail` is supposed to produce — the SDK's own tool-error
type, carrying the JSON-encoded `error_payload` object as its message — so `call_error` below
asserts on that. `test_protocol_e2e.py` is the file that drives a real client/server session over
an in-memory transport and proves the thing SLICES §V6's demo actually describes: that the same
failure reaches an MCP *client* as `CallToolResult(is_error=True)`, not a raised exception a host
would have to catch specially.

One happy path and at least one failure path per tool (KAN-569's brief). `get_backlinks` keeps its
own file, `test_get_backlinks.py` — it had one because its behaviour was distinct (it refused every
call), and it keeps one because KAN-964 inverted those assertions rather than deleting them, and
that account is worth a docstring of its own.
"""

import json

import anyio
import pytest
from conftest import BASE_URL, GROCERIES, NOTES, TOKEN
from mcp.server.mcpserver.exceptions import ToolError

from kaya_mcp.server import server


def call(name: str, **arguments):
    return anyio.run(lambda: server.call_tool(name, arguments))


def call_error(name: str, **arguments) -> str:
    """Call a tool expected to fail; return the `ToolError`'s message text."""
    with pytest.raises(ToolError) as excinfo:
        call(name, **arguments)
    return str(excinfo.value)


# --------------------------------------------------------------------------------- list_notes


def test_list_notes_returns_the_shaped_payload(answering) -> None:
    answering(200, NOTES)
    result = call("list_notes")
    assert result.is_error is False
    assert [n["ref"] for n in result.structured_content["notes"]] == ["NOTE-12", "NOTE-3"]
    assert result.structured_content["summary"] == {"count": 2}


def test_list_notes_honours_fields(answering) -> None:
    answering(200, NOTES)
    result = call("list_notes", fields=["ref", "title"])
    notes = result.structured_content["notes"]
    assert all(set(note) == {"ref", "title"} for note in notes)


def test_list_notes_reports_a_missing_credential_as_a_tool_error() -> None:
    """No `fake_api` installed and no token in the environment: `open_client()` raises
    `MissingCredential` before any request is made, and it must still surface as a structured tool
    error rather than an unhandled exception reaching the host."""
    assert "no_credential" in call_error("list_notes")


def test_list_notes_surfaces_an_api_error_as_a_tool_error(answering) -> None:
    answering(401, {"error": {"code": "invalid_token", "message": "bad token"}})
    text = call_error("list_notes")
    assert "invalid_token" in text
    assert "bad token" in text


# ----------------------------------------------------------------------------------- get_note


def test_get_note_returns_one_note(answering) -> None:
    answering(200, GROCERIES)
    result = call("get_note", ref="NOTE-12")
    assert result.is_error is False
    assert result.structured_content["ref"] == "NOTE-12"
    assert "summary" not in result.structured_content


def test_get_note_reports_a_404_as_a_tool_error(answering) -> None:
    answering(404, {"error": {"code": "note_not_found", "message": "no such note"}})
    assert "note_not_found" in call_error("get_note", ref="NOTE-999")


def test_get_note_surfaces_team_id_with_no_code_change_here(answering) -> None:
    """ADR 0011/R16.6: `get_note`'s tool body is one `client.get_note(ref)` call
    (`kaya_mcp.tools`), and `KayaClient._note` passes the API's response through unchanged — so a
    field the backend added reaches this tool's structured output for free. Proves the card's own
    "no new tool needed" claim rather than just asserting it."""
    answering(200, {**GROCERIES, "team_id": 501})
    result = call("get_note", ref="NOTE-12")
    assert result.structured_content["team_id"] == 501


# -------------------------------------------------------------------------------- create_note


def test_create_note_sends_the_supplied_fields(answering) -> None:
    seen = answering(201, GROCERIES)
    result = call("create_note", title="Groceries", body="milk\neggs")
    assert result.is_error is False
    assert result.structured_content["ref"] == "NOTE-12"
    sent = json.loads(seen[0].content)
    assert sent == {"title": "Groceries", "body": "milk\neggs"}


def test_create_note_reports_a_422_as_a_tool_error(answering) -> None:
    answering(422, {"error": {"code": "validation_error", "message": "title required"}})
    assert "validation_error" in call_error("create_note", title="")


# ---------------------------------------------------------------------------------- edit_note


def test_edit_note_forwards_the_precondition(answering) -> None:
    seen = answering(200, GROCERIES)
    result = call(
        "edit_note", ref="NOTE-12", title="New title", if_updated_at="2026-08-01T00:00:00Z"
    )
    assert result.is_error is False
    sent = json.loads(seen[0].content)
    assert sent == {"title": "New title", "if_updated_at": "2026-08-01T00:00:00Z"}


def test_edit_note_surfaces_a_409_as_a_structured_tool_error_carrying_both_notes(answering) -> None:
    """SLICES §V6's demo, verbatim: `edit_note` on a stale `updated_at` returns the 409 as a
    structured tool error, with both `attempted` and `stored` still reachable."""
    attempted = {**GROCERIES, "body": "new body"}
    stored = {**GROCERIES, "body": "someone else's edit", "updated_at": "2026-08-09T12:00:00Z"}
    answering(
        409,
        {
            "error": {
                "code": "note_conflict",
                "message": "the note has changed",
                "attempted": attempted,
                "stored": stored,
            }
        },
    )
    text = call_error(
        "edit_note", ref="NOTE-12", body="new body", if_updated_at="2026-08-01T00:00:00Z"
    )
    assert "note_conflict" in text
    assert "new body" in text
    assert "someone else's edit" in text


def test_edit_note_with_nothing_to_change_is_a_tool_error(answering) -> None:
    """`KayaClient.update_note` refuses client-side before any request — a `UsageError`, still a
    `KayaError`, still caught the same way. A credential is configured so the refusal proven here
    is the client's own, not `MissingCredential` arriving first."""
    seen = answering(200, GROCERIES)
    assert "usage" in call_error("edit_note", ref="NOTE-12")
    assert seen == []


# -------------------------------------------------------------------------------- search_notes


def test_search_notes_forwards_q_as_a_query_parameter(answering) -> None:
    seen = answering(200, NOTES)
    result = call("search_notes", q="reading list")
    assert result.is_error is False
    assert seen[0].url.path == "/api/v1/notes"
    assert dict(seen[0].url.params) == {"q": "reading list"}


def test_search_notes_honours_fields(answering) -> None:
    answering(200, NOTES)
    result = call("search_notes", q="reading", fields=["ref"])
    notes = result.structured_content["notes"]
    assert all(set(note) == {"ref"} for note in notes)


def test_search_notes_reports_a_blank_query_refusal_as_a_tool_error(answering) -> None:
    answering(400, {"error": {"code": "empty_search_query", "message": "q must not be blank"}})
    assert "empty_search_query" in call_error("search_notes", q="   ")


def test_base_url_and_token_reach_the_request(answering) -> None:
    """A sanity check on the fixture itself: the fake API really is being asked, at the address
    and with the bearer the fixture configured — not a stub returning canned data unconditionally.
    """
    seen = answering(200, NOTES)
    call("list_notes")
    assert str(seen[0].url).startswith(BASE_URL)
    assert seen[0].headers["authorization"] == f"Bearer {TOKEN}"
