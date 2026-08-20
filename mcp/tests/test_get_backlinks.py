"""`get_backlinks` reads `/backlinks` through `render()`, like every other read tool.

**Every assertion in this file inverted in KAN-964, and the inversion is the card landing rather
than a pin being edited away.** CLAUDE.md §Conventions is explicit that a pin quietly edited is a
pin destroyed, so what moved and why is written down here, the same way
`frontend/tests/shell.test.ts` records KAN-553's one-line inversion.

What this file used to say, and why it was right at the time: KAN-569 registered `get_backlinks`
because ADR 0006 froze it as one of the six, but `/links`/`/backlinks` had landed at **no** layer —
no route in `backend/`, no method on `KayaClient`, no CLI verb — so every call raised
`kaya_mcp.errors.BacklinksNotAvailable`, and these tests asserted the refusal by name. The
alternative, `{"notes": []}`, is indistinguishable from "this note genuinely has no backlinks" and
would have been a fabricated answer.

What changed: KAN-566 landed all three layers (`backend/app/api/links.py`, `KayaClient.backlinks`,
`kaya backlinks <ref>`). At that moment the refusal stopped being an honest sequencing gap and
became a false statement about the repository — the exact failure ADR 0006 §4 and CLAUDE.md §Docs
warn about, one layer down from the prose. So the refusal assertions could not stay green and could
not simply be deleted either: a suite that lost them would no longer say anything about the tool
that used to be the one broken member of the frozen six. They are the tests below, pointed the
other way — "refuses, and no request is made" became "returns the shaped payload, and the request
went to `/backlinks`", with the two things that used to be irrelevant (`fields`, and whether a
transport was installed at all) now load-bearing.

What is *not* asserted here any more, deliberately: nothing references
`kaya_mcp.errors.BacklinksNotAvailable`, because that module is deleted. It existed for this one
refusal and nothing else in the repository ever imported it, so leaving the class behind would have
left `mcp/` inventing a failure it can no longer raise.

`test_protocol_e2e.py::test_get_backlinks_reaches_a_real_client_with_structured_content` is this
file's companion, inverted for the same reason: it used to prove the refusal reached a real MCP
client as `CallToolResult(is_error=True)`, and now proves the notes do.
"""

import anyio
import pytest
from conftest import GROCERIES, NOTES, READING_LIST
from mcp.server.mcpserver.exceptions import ToolError

from kaya_mcp.server import server


def call(name: str, **arguments):
    return anyio.run(lambda: server.call_tool(name, arguments))


def test_get_backlinks_is_registered() -> None:
    """The frozen name is real and callable. This is the one assertion in the file that did *not*
    invert — it was true while the tool refused and it is true now, which is exactly why it was
    never sufficient on its own."""
    names = {tool.name for tool in anyio.run(server.list_tools)}
    assert "get_backlinks" in names


def test_get_backlinks_returns_the_notes_linking_to_the_ref(answering) -> None:
    """Inverted from `test_get_backlinks_refuses_rather_than_returning_an_empty_result`.

    The old test installed **no** transport at all, as proof that the refusal happened before any
    request could be made. This one installs a transport and asserts the request *was* made, at the
    URL `KayaClient.backlinks` builds — the same fact read from the other side.
    """
    seen = answering(200, NOTES)
    result = call("get_backlinks", ref="NOTE-12")

    assert result.is_error is False
    assert [n["ref"] for n in result.structured_content["notes"]] == ["NOTE-12", "NOTE-3"]
    assert seen[0].url.path == "/api/v1/notes/NOTE-12/backlinks"
    assert seen[0].method == "GET"


def test_get_backlinks_honours_fields(answering) -> None:
    """Inverted from `test_get_backlinks_refuses_regardless_of_fields`.

    `fields` used to change nothing, because the tool refused before it could reach the transport.
    ADR 0006 §1 requires it on every read, so now it has to narrow — and it does with no line
    written for it in `mcp/`, because `KayaClient.backlinks` attaches the note columns at the call
    and `render()` does the rest (ADR 0004).
    """
    answering(200, NOTES)
    result = call("get_backlinks", ref="NOTE-12", fields=["ref", "title"])

    notes = result.structured_content["notes"]
    assert all(set(note) == {"ref", "title"} for note in notes)
    assert [note["title"] for note in notes] == [GROCERIES["title"], READING_LIST["title"]]


def test_get_backlinks_is_a_collection_and_so_carries_the_aggregate(answering) -> None:
    """The payload is a *note collection*, which is a `KayaClient` fact this package never states.

    `/backlinks` answers with the very same `NoteList` a plain list does, so the `{"count": n}`
    aggregate KAN-548 built arrives here uninvited. Worth asserting because ADR 0004 forbids `mcp/`
    from counting anything itself, so a missing count could only ever be fixed in the wrong place.
    """
    answering(200, NOTES)
    result = call("get_backlinks", ref="NOTE-12")
    assert result.structured_content["summary"] == {"count": 2}


def test_a_note_with_no_backlinks_is_an_empty_collection_rather_than_a_failure(answering) -> None:
    """The answer the refusal was careful not to fake is now the honest one.

    `{"notes": [], "summary": {"count": 0}}` means "this note genuinely has no backlinks" — which
    is exactly why KAN-569 refused instead of returning it, and exactly what it has to mean now.
    """
    answering(200, {"notes": []})
    result = call("get_backlinks", ref="NOTE-12")

    assert result.is_error is False
    assert result.structured_content["notes"] == []
    assert result.structured_content["summary"] == {"count": 0}


def test_an_unresolvable_ref_reaches_the_caller_as_the_apis_own_refusal(answering) -> None:
    """The failure path belongs to the API now, not to this package.

    ADR 0008 decides what a ref means in `backend/app/api/refs.py` and nowhere else, so a missing
    note is a `404` and `get_backlinks` forwards the ref untouched. What a caller sees is that
    refusal — never `not_yet_available`, the code `kaya_mcp/errors.py` used to own, and never a
    KAN-566 pointer, which is the string this suite most needs to stop containing.
    """
    answering(404, {"error": {"code": "note_not_found", "message": "no such note"}})
    with pytest.raises(ToolError) as excinfo:
        call("get_backlinks", ref="NOTE-999")

    text = str(excinfo.value)
    assert "note_not_found" in text
    assert "not_yet_available" not in text
    assert "KAN-566" not in text
