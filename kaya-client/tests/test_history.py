"""`KayaClient.history` / `.diff_versions` and the pure helpers behind them — KAY-138."""

from typing import Any

import httpx
import pytest

from kaya_client import UsageError
from kaya_client.client import KayaClient
from kaya_client.history import BEFORE_TRACKING, actor_label, unified_diff

TOKEN_ACTOR = {
    "user_id": "u1",
    "email": "alice@example.com",
    "channel": "token",
    "token": {"id": 3, "prefix": "kaya_pat_ab12", "name": "ci-bot", "kind": None},
}
SESSION_ACTOR = {
    "user_id": "u1",
    "email": "alice@example.com",
    "channel": "session",
    "token": None,
}
VERSIONS = {
    "versions": [
        {"id": 9, "body": "a\nB\nc", "created_at": "2026-10-03", "actor": SESSION_ACTOR},
        {"id": 8, "body": "a\nb\nc", "created_at": "2026-10-02", "actor": TOKEN_ACTOR},
        {"id": 7, "body": "a", "created_at": "2026-10-01", "actor": None},
    ]
}


def client_over(body: dict[str, Any]) -> tuple[KayaClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handle)
    return KayaClient("https://kaya.example", "t", client=httpx.Client(transport=transport)), seen


def test_actor_labels() -> None:
    assert actor_label(None) == BEFORE_TRACKING
    assert actor_label(SESSION_ACTOR) == "alice@example.com via web"
    assert actor_label(TOKEN_ACTOR) == "alice@example.com via token ci-bot (kaya_pat_ab12)"
    with_kind = {**TOKEN_ACTOR, "token": {**TOKEN_ACTOR["token"], "kind": "read-only"}}
    assert actor_label(with_kind).endswith("(kaya_pat_ab12) [read-only]")


def test_history_numbers_versions_oldest_first_and_labels_actors() -> None:
    client, seen = client_over(VERSIONS)
    payload = client.history("NOTE-5")
    assert seen[0].url.path == "/api/v1/notes/NOTE-5/versions"
    assert [r["version"] for r in payload.records] == [3, 2, 1]
    assert payload.records[2]["actor"] == BEFORE_TRACKING
    assert payload.records[1]["actor"] == "alice@example.com via token ci-bot (kaya_pat_ab12)"


def test_diff_defaults_to_previous_vs_latest() -> None:
    client, _ = client_over(VERSIONS)
    record = client.diff_versions("NOTE-5").record
    assert (record["from"], record["to"]) == (2, 3)
    assert (record["added"], record["removed"]) == (1, 1)
    assert "-b" in record["diff"] and "+B" in record["diff"]


def test_diff_with_explicit_versions() -> None:
    client, _ = client_over(VERSIONS)
    record = client.diff_versions("NOTE-5", 1, 2).record
    assert (record["from"], record["to"], record["added"], record["removed"]) == (1, 2, 2, 0)
    only_from = client.diff_versions("NOTE-5", 1).record
    assert (only_from["from"], only_from["to"]) == (1, 3)


def test_diff_of_a_missing_version_is_a_usage_error() -> None:
    client, _ = client_over(VERSIONS)
    with pytest.raises(UsageError):
        client.diff_versions("NOTE-5", 1, 9)


def test_diff_of_a_single_version_note_is_a_usage_error() -> None:
    client, _ = client_over({"versions": [VERSIONS["versions"][2]]})
    with pytest.raises(UsageError):
        client.diff_versions("NOTE-5")


def test_unified_diff_counts_ignore_the_file_headers() -> None:
    text, added, removed = unified_diff("x\n", "y\n", old_label="a", new_label="b")
    assert (added, removed) == (1, 1)
    assert text.startswith("--- a")
