"""`note {create,edit,move,delete}` end to end: argv → parser → verb → client → stdout → exit code.

Everything below the socket is the shipped code path. What this file is about is that the CLI added
**no opinion** between the two — the ref it was given, the fields it was told about and the
precondition it was handed all reach the API unchanged, and the payload comes back through
``render`` with nothing this package formatted itself.
"""

import json

import httpx
import pytest
from conftest import GROCERIES

from kaya_cli.__main__ import main

PRECISE = "2026-08-09T11:02:33.123456+00:00"

CONFLICT = {
    "error": {
        "code": "note_conflict",
        "message": "NOTE-12 has changed since you read it. Nothing was written.",
        "attempted": {**GROCERIES, "body": "mine"},
        "stored": {**GROCERIES, "body": "theirs"},
    }
}

MALFORMED_REF = {
    "error": {
        "code": "invalid_note_ref",
        "message": "not a note reference",
        "ref": "#NOTE-12",
    }
}


def body_of(request: httpx.Request) -> dict:
    return json.loads(request.content)


# ------------------------------------------------------------------------------ create


def test_create_posts_the_title(capsys, answering) -> None:
    seen = answering(201, GROCERIES)

    assert main(["note", "create", "Groceries"]) == 0
    assert (seen[0].method, seen[0].url.path) == ("POST", "/api/v1/notes")
    assert body_of(seen[0]) == {"title": "Groceries"}
    assert capsys.readouterr().out.startswith("ref         NOTE-12")


def test_create_takes_a_body_and_a_path(answering) -> None:
    seen = answering(201, GROCERIES)
    main(["note", "create", "Groceries", "--body", "milk", "--path", "home/groceries.md"])

    assert body_of(seen[0]) == {"title": "Groceries", "body": "milk", "path": "home/groceries.md"}


def test_create_reads_a_body_from_a_file(answering, tmp_path) -> None:
    """A note body is prose: long, multi-line, and quite likely to start with a dash. A path is how
    argv carries one, and reading it is the whole of what this package does with it."""
    note = tmp_path / "note.md"
    note.write_text("# Groceries\n\n- milk\n- eggs\n", encoding="utf-8")
    seen = answering(201, GROCERIES)

    assert main(["note", "create", "Groceries", "--body-file", str(note)]) == 0
    assert body_of(seen[0])["body"] == "# Groceries\n\n- milk\n- eggs\n"


def test_a_body_file_that_is_not_there_is_a_usage_error(capsys, answering) -> None:
    answering(201, GROCERIES)

    assert main(["note", "create", "Groceries", "--body-file", "/nope/missing.md"]) == 2
    assert capsys.readouterr().out.startswith("error\tusage\t")


def test_a_body_and_a_body_file_together_are_refused(capsys) -> None:
    """Two sources for one field is the sort of ambiguity resolved differently by the person writing
    the script and the person reading it, so the parser refuses rather than picking one."""
    assert main(["note", "create", "Groceries", "--body", "x", "--body-file", "y"]) == 2
    assert "not allowed with" in capsys.readouterr().err


def test_create_without_a_title_is_a_usage_error(capsys) -> None:
    assert main(["note", "create"]) == 2
    assert "title" in capsys.readouterr().err


# -------------------------------------------------------------------------------- edit


def test_edit_patches_only_what_it_was_told_about(answering) -> None:
    seen = answering(200, GROCERIES)
    main(["note", "edit", "NOTE-12", "--title", "Shopping"])

    assert (seen[0].method, seen[0].url.path) == ("PATCH", "/api/v1/notes/NOTE-12")
    assert body_of(seen[0]) == {"title": "Shopping"}


def test_edit_with_nothing_to_change_is_a_usage_error_and_sends_nothing(capsys, answering) -> None:
    """The API would take it as a legal no-op and answer `200` — a write reporting success for an
    edit nobody made, which is the failure an agent cannot detect."""
    seen = answering(200, GROCERIES)

    assert main(["note", "edit", "NOTE-12"]) == 2
    assert seen == []
    assert capsys.readouterr().out.startswith("error\tusage\t")


def test_the_precondition_reaches_the_api_to_the_microsecond(answering) -> None:
    """ADR 0009 compares exactly, so a round trip that lost one microsecond would refuse every
    correct write. Nothing between argv and the wire parses this value."""
    seen = answering(200, GROCERIES)
    main(["note", "edit", "NOTE-12", "--body", "new", "--if-updated-at", PRECISE])

    assert body_of(seen[0])["if_updated_at"] == PRECISE


def test_omitting_the_precondition_is_a_plain_overwrite(answering) -> None:
    """Opt-in *by specification* (ADR 0009): the key must be absent, not null, and there is no
    ``--force`` because not passing the flag already spells the unguarded write."""
    seen = answering(200, GROCERIES)
    main(["note", "edit", "NOTE-12", "--body", "new"])

    assert "if_updated_at" not in body_of(seen[0])


def test_a_stale_precondition_prints_a_conflict_a_caller_can_act_on(capsys, answering) -> None:
    """The `409` carries two whole notes and they survive to stdout unflattened, so "keep mine /
    keep theirs" is a decision the caller can make from one command's output.

    Exit `1`: `409` has no row in ADR 0005 §contract 4's table and the unmapped default is
    "something failed and no more specific meaning applies", which is true — the write can succeed
    after a re-read, unlike a `400`. Adding a number for it would be publishing a seventh exit code,
    which is an ADR amendment rather than a line in this card.
    """
    answering(409, CONFLICT)

    assert main(["note", "edit", "NOTE-12", "--body", "mine", "--if-updated-at", PRECISE]) == 1
    row = capsys.readouterr().out
    assert row.startswith("error\tnote_conflict\t")

    answering(409, CONFLICT)
    main(["note", "edit", "NOTE-12", "--body", "mine", "--if-updated-at", PRECISE, "--json"])
    reported = json.loads(capsys.readouterr().out)["error"]

    assert reported["attempted"]["body"] == "mine"
    assert reported["stored"]["body"] == "theirs"


# -------------------------------------------------------------------------------- move


def test_move_is_the_same_request_as_editing_the_path(answering) -> None:
    """ADR 0008: moving a note *is* a `PATCH` to one column, so `move` is a word and not a route."""
    moved = answering(200, GROCERIES)
    main(["note", "move", "NOTE-12", "archive/2026.md"])
    move_request = moved[0]

    edited = answering(200, GROCERIES)
    main(["note", "edit", "NOTE-12", "--path", "archive/2026.md"])
    edit_request = edited[-1]

    assert move_request.method == edit_request.method
    assert move_request.url.raw_path == edit_request.url.raw_path
    assert move_request.content == edit_request.content


def test_move_needs_both_a_ref_and_a_path(capsys) -> None:
    assert main(["note", "move", "NOTE-12"]) == 2
    assert "path" in capsys.readouterr().err


def test_move_has_no_precondition_flag() -> None:
    """A precondition on a path-only write is accepted and *ignored* by the API by design
    (`NoteUpdate.guards_the_body`), so offering the flag would offer a guarantee that is not there.
    """
    assert main(["note", "move", "NOTE-12", "x.md", "--if-updated-at", PRECISE]) == 2


# ------------------------------------------------------------------------------ delete


def test_delete_calls_the_route_and_says_so(capsys, answering) -> None:
    """A `204` has no body. Printing nothing would emit the empty string, which is indistinguishable
    from a crashed pipe — the argument `no notes` already exists for."""
    seen = answering(204, {})

    assert main(["note", "delete", "NOTE-12"]) == 0
    assert (seen[0].method, seen[0].url.path) == ("DELETE", "/api/v1/notes/NOTE-12")
    assert capsys.readouterr().out == "ref      NOTE-12\ndeleted  true\n"


def test_delete_is_structured_for_a_script(capsys, answering) -> None:
    answering(204, {})
    main(["note", "delete", "12", "--json"])

    assert json.loads(capsys.readouterr().out) == {"ref": "12", "deleted": True}


def test_delete_takes_no_confirmation_flag(capsys, answering) -> None:
    """**Decided, not overlooked.** ADR 0005 §contract 9 forbids prompting, so the only available
    confirmation is a flag — and a flag that must always be passed is a prefix, not a confirmation:
    it does not catch the mistake it would exist for, which is typing the wrong ref. The blast
    radius is exactly one explicitly named note; there is no glob, no `--all`, no filtered delete.
    The day a bulk form arrives is the day a `--yes` earns its place, and that is that card's line.
    """
    answering(204, {})

    assert main(["note", "delete", "NOTE-12"]) == 0
    assert main(["note", "delete", "NOTE-12", "--yes"]) == 2
    assert "--yes" in capsys.readouterr().err


# ------------------------------------------------------------- the ref, on every verb


@pytest.mark.parametrize(
    "argv",
    [
        ["note", "get", "#NOTE-12"],
        ["note", "edit", "#NOTE-12", "--title", "x"],
        ["note", "move", "#NOTE-12", "x.md"],
        ["note", "delete", "#NOTE-12"],
    ],
    ids=["get", "edit", "move", "delete"],
)
def test_a_malformed_ref_reaches_the_api_and_exits_two(capsys, answering, argv) -> None:
    """ADR 0008 makes ``#NOTE-12`` a `400` **by design**, and KAN-718 makes a `400` exit `2`. Both
    halves have to hold on every ref-taking verb: a client that normalised the ``#`` away would turn
    a designed refusal into a silent success, and one that let httpx read it as a URL fragment would
    send a request the caller never made.
    """
    seen = answering(400, MALFORMED_REF)

    assert main(argv) == 2
    assert seen[0].url.raw_path.decode() == "/api/v1/notes/%23NOTE-12"
    assert capsys.readouterr().out.startswith("error\tinvalid_note_ref\t")


@pytest.mark.parametrize(
    "argv",
    [
        ["note", "edit", "note-12", "--title", "x"],
        ["note", "move", "12", "x.md"],
        ["note", "delete", "NOTE-12"],
    ],
    ids=["edit lower", "move bare", "delete canonical"],
)
def test_every_spelling_of_a_ref_is_passed_through_untouched(answering, argv) -> None:
    """One resolver, in the backend (ADR 0008). A second one in an adapter would disagree."""
    seen = answering(204 if argv[1] == "delete" else 200, GROCERIES)
    main(argv)

    assert seen[0].url.path == f"/api/v1/notes/{argv[2]}"


# -------------------------------------------------------------- the flags every verb has


@pytest.mark.parametrize("fmt", ["human", "json", "toon"])
def test_every_write_verb_honours_the_published_formats(capsys, answering, fmt: str) -> None:
    """ADR 0005 §contract 1 is a promise about *every* verb, and the way it breaks is a verb added
    later without the flags. `output_flags()` is a parent parser precisely so it cannot be."""
    answering(201, GROCERIES)
    assert main(["note", "create", "Groceries", "--format", fmt]) == 0
    assert capsys.readouterr().out.strip()


def test_full_restores_the_whole_body_on_a_write(capsys, answering) -> None:
    """Truncation applies to what a write returns, because a write returns a note like any read."""
    long_note = {**GROCERIES, "body": "x" * 900}
    answering(200, long_note)
    main(["note", "edit", "NOTE-12", "--body", "x", "--full"])

    assert "truncated" not in capsys.readouterr().out


def test_a_write_truncates_by_default(capsys, answering) -> None:
    long_note = {**GROCERIES, "body": "x" * 900}
    answering(200, long_note)
    main(["note", "edit", "NOTE-12", "--body", "x"])

    assert "(truncated, 900 chars total" in capsys.readouterr().out


def test_a_write_makes_exactly_one_request(answering) -> None:
    """No read-before-write. A client that fetched the precondition itself would look safer and
    would disable the guarantee — the token would name a version read microseconds ago rather than
    the version the caller's edit was based on."""
    seen = answering(200, GROCERIES)
    main(["note", "edit", "NOTE-12", "--body", "new"])

    assert len(seen) == 1
