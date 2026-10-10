"""`kaya note history` and `kaya note diff`: argv reaches the right client call — KAY-138."""

import json

from kaya_cli.__main__ import main

VERSIONS = {
    "versions": [
        {
            "id": 2,
            "body": "one\ntwo",
            "created_at": "2026-10-02T00:00:00+00:00",
            "actor": {
                "user_id": "u",
                "email": "a@example.com",
                "channel": "token",
                "token": {"id": 1, "prefix": "kaya_pat_ab12", "name": "ci-bot", "kind": None},
            },
        },
        {"id": 1, "body": "one", "created_at": "2026-10-01T00:00:00+00:00", "actor": None},
    ]
}


def test_history_shows_the_actor_and_before_tracking(capsys, answering) -> None:
    seen = answering(200, VERSIONS)
    assert main(["note", "history", "NOTE-4"]) == 0
    out = capsys.readouterr().out
    assert [(r.method, r.url.path) for r in seen] == [("GET", "/api/v1/notes/NOTE-4/versions")]
    assert "ci-bot (kaya_pat_ab12)" in out
    assert "before tracking" in out


def test_diff_defaults_to_previous_vs_latest(capsys, answering) -> None:
    answering(200, VERSIONS)
    assert main(["note", "diff", "NOTE-4", "--json"]) == 0
    record = json.loads(capsys.readouterr().out)
    assert (record["from"], record["to"], record["added"]) == (1, 2, 1)


def test_diff_of_an_unknown_version_exits_2(answering) -> None:
    answering(200, VERSIONS)
    assert main(["note", "diff", "NOTE-4", "1", "7"]) == 2
