"""`format_note` and the conditional format hint (KAN-1816), against the KAN-1814 wire contract.

The contract (implemented server-side by KAN-1814, faked here at the transport):

- `PATCH /api/v1/notes/{ref}` takes an optional boolean `format`; true formats the body (supplied
  or stored) and saves once under the same `if_updated_at` guard (stale is a 409).
- `GET /api/v1/notes/{ref}/format-check` answers `{"changed": bool, "changed_lines": int}` and
  writes nothing.

`Store` is a stateful fake: the stored `updated_at` moves on every write, which is what lets a test
assert that `--check` changed nothing rather than that it "made a GET".
"""

import json

import httpx
import pytest

from kaya_client import ApiError, KayaClient, UsageError, render
from kaya_client.hints import FORMAT_COMMAND, format_help_lines

BASE_URL = "https://kaya.example"
UNFORMATTED = "*  milk\n*  eggs\n"
FORMATTED = "- milk\n- eggs\n"
CONFLICT = {"error": {"code": "note_conflict", "message": "stale"}}


class Store:
    """One note whose body "formats" by a trivial rule: bullets `*  ` become `- `."""

    def __init__(self, body: str) -> None:
        self.body = body
        self.version = 1
        self.requests: list[httpx.Request] = []
        self.check_status = 200

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

    @staticmethod
    def formatted(body: str) -> str:
        return body.replace("*  ", "- ")

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith("/format-check"):
            if self.check_status != 200:
                return httpx.Response(self.check_status, json=CONFLICT)
            after = self.formatted(self.body).splitlines()
            changed = sum(a != b for a, b in zip(self.body.splitlines(), after, strict=True))
            return httpx.Response(200, json={"changed": changed > 0, "changed_lines": changed})
        if request.method == "POST":
            self.body = json.loads(request.content).get("body", "")
            self.version += 1
            return httpx.Response(201, json=self.note())
        if request.method == "PATCH":
            sent = json.loads(request.content)
            guard = sent.get("if_updated_at")
            if guard is not None and guard != self.updated_at:
                return httpx.Response(409, json=CONFLICT)
            body = sent.get("body", self.body)
            self.body = self.formatted(body) if sent.get("format") else body
            self.version += 1
            return httpx.Response(200, json=self.note())
        return httpx.Response(200, json=self.note())


def client_for(store: Store) -> KayaClient:
    transport = httpx.MockTransport(store.handle)
    return KayaClient(BASE_URL, "tok", client=httpx.Client(transport=transport))


def probes(store: Store) -> list[httpx.Request]:
    return [r for r in store.requests if r.url.path.endswith("/format-check")]


def test_format_sends_one_patch_with_format_true_and_no_body() -> None:
    store = Store(UNFORMATTED)
    payload = client_for(store).format_note("NOTE-12")
    [patch] = store.requests
    assert patch.method == "PATCH" and patch.url.path == "/api/v1/notes/NOTE-12"
    assert json.loads(patch.content) == {"format": True}
    assert payload.record["body"] == FORMATTED
    assert payload.format_changed_lines is None  # just formatted: no hint


def test_format_is_the_update_request_plus_the_flag() -> None:
    """ADR 0008's `move` pattern: no endpoint of its own, byte-identical to update_note."""
    a, b = Store(UNFORMATTED), Store(UNFORMATTED)
    client_for(a).format_note("NOTE-12", if_updated_at=a.updated_at)
    client_for(b).update_note("NOTE-12", if_updated_at=b.updated_at, format=True)
    assert a.requests[0].content == b.requests[0].content
    assert a.requests[0].url == b.requests[0].url


def test_check_writes_nothing_and_leaves_updated_at_alone() -> None:
    store = Store(UNFORMATTED)
    before = store.updated_at
    payload = client_for(store).format_note("NOTE-12", check=True)
    assert [r.method for r in store.requests] == ["GET"]
    assert store.requests[0].url.path == "/api/v1/notes/NOTE-12/format-check"
    assert store.updated_at == before and store.body == UNFORMATTED
    assert render(payload, fmt="data") == {"changed": True, "changed_lines": 2}


def test_check_refuses_a_precondition_rather_than_ignoring_it() -> None:
    store = Store(UNFORMATTED)
    with pytest.raises(UsageError):
        client_for(store).format_note("NOTE-12", check=True, if_updated_at=store.updated_at)
    assert store.requests == []


def test_a_stale_precondition_is_a_409_and_nothing_is_written() -> None:
    store = Store(UNFORMATTED)
    with pytest.raises(ApiError) as refused:
        client_for(store).format_note("NOTE-12", if_updated_at="2020-01-01T00:00:00+00:00")
    assert refused.value.status == 409
    assert store.body == UNFORMATTED and store.version == 1


# ------------------------------------------------------------------------------------- the hint


def test_an_unformatted_write_carries_the_hint_naming_command_and_count() -> None:
    store = Store("")
    payload = client_for(store).create_note("Groceries", body=UNFORMATTED, format_hint=True)
    expected = f"{FORMAT_COMMAND}  # 2 lines would change"
    assert payload.format_changed_lines == 2
    assert store.body == UNFORMATTED  # writes are never formatted implicitly
    assert format_help_lines(payload) == (expected,)
    assert render(payload, fmt="data")["help"] == [expected]
    assert f"help: {expected}" in render(payload, fmt="human")


def test_a_formatted_write_carries_no_hint_anywhere() -> None:
    store = Store("")
    payload = client_for(store).create_note("Groceries", body=FORMATTED, format_hint=True)
    assert payload.format_changed_lines is None
    assert "help" not in render(payload, fmt="data")
    assert FORMAT_COMMAND not in render(payload, fmt="human")


def test_an_edit_hints_only_when_the_saved_body_would_change() -> None:
    store = Store(FORMATTED)
    unformatted = client_for(store).update_note("NOTE-12", body=UNFORMATTED, format_hint=True)
    assert unformatted.format_changed_lines == 2
    clean = client_for(store).update_note("NOTE-12", body=FORMATTED, format_hint=True)
    assert clean.format_changed_lines is None


def test_one_changed_line_is_singular() -> None:
    store = Store("")
    payload = client_for(store).create_note("t", body="*  only\n", format_hint=True)
    assert format_help_lines(payload) == (f"{FORMAT_COMMAND}  # 1 line would change",)


def test_no_probe_without_the_opt_in_or_a_body_or_after_formatting() -> None:
    store = Store(UNFORMATTED)
    client_for(store).create_note("t", body=UNFORMATTED)  # a bare client call, e.g. import
    client_for(store).update_note("NOTE-12", title="new title", format_hint=True)
    client_for(store).update_note("NOTE-12", format=True, format_hint=True)
    assert probes(store) == []


def test_a_failing_probe_is_silence_not_an_error() -> None:
    """The note is saved; an older server with no format-check route answers 404."""
    store = Store("")
    store.check_status = 404
    payload = client_for(store).create_note("t", body=UNFORMATTED, format_hint=True)
    assert payload.format_changed_lines is None
    assert store.body == UNFORMATTED


def test_the_hint_is_a_number_never_note_text() -> None:
    store = Store("")
    payload = client_for(store).create_note("t", body="*  secret-text\n", format_hint=True)
    assert all("secret-text" not in line for line in format_help_lines(payload))
