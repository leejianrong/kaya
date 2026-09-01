"""`note export`/`note import`/`export-all`/`import-all` end to end: argv → parser → verb →
client → stdout → exit code (R12, KAN-1060..1063).

Everything below the socket is the shipped code path, same as `test_write_verbs.py` — the file
path, the ref and the front matter all reach `kaya_client` unchanged, with nothing this package
formats itself.
"""

import json

import httpx
from conftest import GROCERIES

from kaya_cli.__main__ import main

# ------------------------------------------------------------------------------ note export


def test_note_export_writes_a_file_and_reports_it(capsys, answering, tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    seen = answering(200, GROCERIES)

    assert main(["note", "export", "NOTE-12"]) == 0
    assert (seen[0].method, seen[0].url.path) == ("GET", "/api/v1/notes/NOTE-12")
    assert (tmp_path / "NOTE-12.md").exists()
    assert "NOTE-12.md" in capsys.readouterr().out


def test_note_export_takes_an_explicit_out_path(answering, tmp_path) -> None:
    answering(200, GROCERIES)
    target = tmp_path / "somewhere" / "note.md"

    assert main(["note", "export", "NOTE-12", "--out", str(target)]) == 0
    assert target.exists()


def test_note_export_fields_is_a_usage_error_on_the_entity(capsys, answering, tmp_path) -> None:
    """ADR 0005 §contract 2: `--fields` on a single-entity verb is refused, never silently ignored
    — inherited automatically since `export_note` returns a `Kind.ENTITY` payload."""
    answering(200, GROCERIES)
    out = tmp_path / "x.md"

    assert main(["note", "export", "NOTE-12", "--out", str(out), "--fields", "ref"]) == 2
    assert capsys.readouterr().out.startswith("error\tusage\t")


def test_note_export_a_missing_note_is_exit_five(capsys, answering, tmp_path) -> None:
    body = {"error": {"code": "note_not_found", "message": "no such note"}}
    answering(404, body)

    assert main(["note", "export", "NOTE-999", "--out", str(tmp_path / "x.md")]) == 5
    assert not (tmp_path / "x.md").exists()


# ------------------------------------------------------------------------------ note import


def test_note_import_posts_the_files_title_and_body(answering, tmp_path) -> None:
    source = tmp_path / "in.md"
    source.write_text('---\ntitle: "Groceries"\n---\nmilk\neggs', encoding="utf-8")
    seen = answering(201, GROCERIES)

    assert main(["note", "import", str(source)]) == 0
    body = json.loads(seen[0].content)
    assert body == {"title": "Groceries", "body": "milk\neggs"}
    assert (seen[0].method, seen[0].url.path) == ("POST", "/api/v1/notes")


def test_note_import_a_missing_file_is_a_usage_error(capsys, answering) -> None:
    answering(201, GROCERIES)  # a session has to open before the verb can refuse the file
    assert main(["note", "import", "/nope/missing.md"]) == 2
    assert capsys.readouterr().out.startswith("error\tusage\t")


def test_note_import_prints_the_created_note(capsys, answering, tmp_path) -> None:
    source = tmp_path / "in.md"
    source.write_text('---\ntitle: "Groceries"\n---\nmilk', encoding="utf-8")
    answering(201, GROCERIES)

    main(["note", "import", str(source), "--json"])
    rendered = json.loads(capsys.readouterr().out)
    assert rendered["ref"] == "NOTE-12"
    assert rendered["imported_from_ref"] is None


def test_note_import_reclaims_a_free_ref_end_to_end(capsys, fake_api, tmp_path) -> None:
    """R12/KAN-1061's headline, through the real CLI: a file naming a free ``kaya_ref`` gets that
    exact ref back via ``PUT``, not a fresh one from ``POST`` — proven at the argv-to-stdout layer,
    the same way `test_write_verbs.py` proves every other verb end to end."""
    source = tmp_path / "in.md"
    source.write_text('---\nkaya_ref: "NOTE-12"\ntitle: "Groceries"\n---\nmilk', encoding="utf-8")

    seen = fake_api(lambda request: httpx.Response(201, json=GROCERIES))

    assert main(["note", "import", str(source), "--json"]) == 0
    assert (seen[0].method, seen[0].url.path) == ("PUT", "/api/v1/notes/NOTE-12")

    rendered = json.loads(capsys.readouterr().out)
    assert rendered["ref"] == "NOTE-12"
    assert rendered["imported_from_ref"] == "NOTE-12"
    assert rendered["ref_reused"] is True


# --------------------------------------------------------------------------------- export-all


def test_export_all_requires_a_directory(capsys) -> None:
    assert main(["export-all"]) == 2
    assert "directory" in capsys.readouterr().err


def test_export_all_writes_every_note(answering, tmp_path) -> None:
    answering(200, {"notes": [GROCERIES]})

    assert main(["export-all", str(tmp_path)]) == 0
    assert (tmp_path / "home" / "groceries.md").exists()


# --------------------------------------------------------------------------------- import-all


def test_import_all_requires_a_directory(capsys) -> None:
    assert main(["import-all"]) == 2
    assert "directory" in capsys.readouterr().err


def test_import_all_walks_every_markdown_file(fake_api, tmp_path) -> None:
    (tmp_path / "a.md").write_text('---\ntitle: "A"\n---\nbody a', encoding="utf-8")
    (tmp_path / "b.md").write_text('---\ntitle: "B"\n---\nbody b', encoding="utf-8")

    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "GET":
            return httpx.Response(404, json={"error": {"code": "note_not_found", "message": ""}})
        return httpx.Response(201, json=GROCERIES)

    fake_api(handle)

    assert main(["import-all", str(tmp_path)]) == 0
    posts = [r for r in seen if r.method == "POST"]
    assert len(posts) == 2


def test_import_all_a_missing_directory_is_a_usage_error(capsys, answering, tmp_path) -> None:
    answering(201, GROCERIES)  # a session has to open before the verb can refuse the directory
    missing = tmp_path / "nope"

    assert main(["import-all", str(missing)]) == 2
    assert capsys.readouterr().out.startswith("error\tusage\t")
