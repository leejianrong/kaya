"""`kaya note format` and the format hint on create/edit, end to end (KAN-1816).

argv -> parser -> verb -> client -> stdout -> exit code, with only the socket faked. The fake is the
KAN-1814 contract (see `kaya-client/tests/test_format.py`): `PATCH` takes `format`, and
`GET .../format-check` answers `{"changed", "changed_lines"}` and writes nothing.
"""

import json
import shlex

import httpx
import pytest
from kaya_client.hints import FORMAT_COMMAND, PROG

from kaya_cli.__main__ import build_parser, main

UNFORMATTED = "*  milk\n*  eggs\n"
FORMATTED = "- milk\n- eggs\n"


class Store:
    def __init__(self, body: str) -> None:
        self.body = body
        self.version = 1
        self.requests: list[httpx.Request] = []

    @property
    def updated_at(self) -> str:
        return f"2026-10-02T10:00:0{self.version}.000000+00:00"

    def note(self) -> dict:
        return {
            "ref": "NOTE-12",
            "id": 12,
            "title": "Groceries",
            "path": "",
            "body": self.body,
            "created_at": "2026-10-02T10:00:00+00:00",
            "updated_at": self.updated_at,
        }

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith("/format-check"):
            after = self.body.replace("*  ", "- ").splitlines()
            changed = sum(a != b for a, b in zip(self.body.splitlines(), after, strict=True))
            return httpx.Response(200, json={"changed": changed > 0, "changed_lines": changed})
        if request.method == "GET":
            return httpx.Response(200, json=self.note())
        sent = json.loads(request.content)
        if request.method == "PATCH":
            guard = sent.get("if_updated_at")
            if guard is not None and guard != self.updated_at:
                body = {"error": {"code": "note_conflict", "message": "stale"}}
                return httpx.Response(409, json=body)
            self.body = sent.get("body", self.body)
            if sent.get("format"):
                self.body = self.body.replace("*  ", "- ")
        else:
            self.body = sent.get("body", "")
        self.version += 1
        return httpx.Response(201 if request.method == "POST" else 200, json=self.note())


@pytest.fixture
def store(fake_api) -> Store:
    s = Store(UNFORMATTED)
    fake_api(s.handle)
    return s


def test_format_writes_once_and_prints_the_formatted_note(store, capsys) -> None:
    assert main(["note", "format", "NOTE-12", "--format", "json"]) == 0
    assert store.body == FORMATTED
    [patch] = store.requests
    assert patch.method == "PATCH" and json.loads(patch.content) == {"format": True}
    assert json.loads(capsys.readouterr().out)["body"] == FORMATTED


def test_check_reports_and_writes_nothing(store, capsys) -> None:
    before = store.updated_at
    assert main(["note", "format", "NOTE-12", "--check", "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"changed": True, "changed_lines": 2}
    assert [r.method for r in store.requests] == ["GET"]
    assert store.updated_at == before and store.body == UNFORMATTED


def test_a_stale_precondition_exits_6_and_writes_nothing(store) -> None:
    assert main(["note", "format", "NOTE-12", "--if-updated-at", "2020-01-01T00:00:00+00:00"]) == 6
    assert store.body == UNFORMATTED and store.version == 1


def test_a_current_precondition_is_accepted(store) -> None:
    assert main(["note", "format", "NOTE-12", "--if-updated-at", store.updated_at]) == 0
    assert store.body == FORMATTED


def test_check_with_a_precondition_is_a_usage_error(store) -> None:
    assert main(["note", "format", "NOTE-12", "--check", "--if-updated-at", store.updated_at]) == 2
    assert store.requests == []


# ------------------------------------------------------------------------------------- the hint


def test_an_unformatted_create_prints_the_hint_and_stores_the_body_as_sent(store, capsys) -> None:
    assert main(["note", "create", "Groceries", "--body", UNFORMATTED]) == 0
    out = capsys.readouterr().out
    assert f"help: {FORMAT_COMMAND}  # 2 lines would change" in out
    assert store.body == UNFORMATTED


def test_a_formatted_create_prints_no_format_hint(store, capsys) -> None:
    assert main(["note", "create", "Groceries", "--body", FORMATTED]) == 0
    assert "note format" not in capsys.readouterr().out


def test_an_unformatted_edit_hints_and_a_formatted_one_does_not(store, capsys) -> None:
    assert main(["note", "edit", "NOTE-12", "--body", UNFORMATTED]) == 0
    assert "2 lines would change" in capsys.readouterr().out
    assert main(["note", "edit", "NOTE-12", "--body", FORMATTED]) == 0
    assert "note format" not in capsys.readouterr().out


def test_the_hint_reaches_structured_output_too(store, capsys) -> None:
    assert main(["note", "edit", "NOTE-12", "--body", UNFORMATTED, "--format", "json"]) == 0
    hint = f"{FORMAT_COMMAND}  # 2 lines would change"
    assert json.loads(capsys.readouterr().out)["help"] == [hint]


def test_the_hinted_command_parses_as_a_real_command() -> None:
    """ADR 0005 §contract 8: every hint parses. The count rides after a shell `#` comment."""
    command = FORMAT_COMMAND
    words = shlex.split(command)
    assert words[0] == PROG
    parsed = build_parser().parse_args(words[1:])
    assert (parsed.command, parsed.subcommand, parsed.ref) == ("note", "format", "<ref>")
