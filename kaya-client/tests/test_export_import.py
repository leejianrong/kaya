"""`KayaClient.export_note`/`export_all`/`import_note`/`import_dir` against an
``httpx.MockTransport`` and a real filesystem (``tmp_path``). No network, no live backend.

R12's headline finding — kaya's ``[[Title]]`` wikilinks are already Obsidian-native — means export
never rewrites a body, so most of what is worth pinning here is that the file on disk and the note
on the wire agree byte for byte, that import tries `claim_note` (``PUT``) first whenever the file
names a ``kaya_ref`` and falls back to the ordinary `create_note` (``POST``) only when that is
refused or absent, and that neither request is anything bespoke (no reconciliation logic lives
here — KAN-563 runs identically either way, per BREADBOARD.md's R12).
"""

import json
from pathlib import Path

import httpx
import pytest
from conftest import GROCERIES, NOTE_LIST_BODY, READING_LIST
from test_client import client_over, responder

from kaya_client import ApiError, UsageError
from kaya_client.frontmatter import parse_document


def body_of(request: httpx.Request) -> dict:
    return json.loads(request.content)


# ------------------------------------------------------------------------- export_note


def test_export_note_writes_the_note_as_front_matter_plus_body(tmp_path) -> None:
    target = tmp_path / "out.md"
    with client_over(responder(200, GROCERIES)) as client:
        payload = client.export_note("NOTE-12", target)

    assert payload.record["ref"] == "NOTE-12"
    assert payload.record["file"] == str(target)
    doc = parse_document(target.read_text(encoding="utf-8"))
    assert doc.get("kaya_ref") == "NOTE-12"
    assert doc.get("title") == "Groceries"
    assert doc.body == GROCERIES["body"]


def test_export_note_defaults_to_the_canonical_ref_as_a_filename(tmp_path, monkeypatch) -> None:
    """``12`` is typed; the file is named after the ref the API returned, not the spelling used."""
    monkeypatch.chdir(tmp_path)
    with client_over(responder(200, GROCERIES)) as client:
        payload = client.export_note("12")

    assert payload.record["file"] == "NOTE-12.md"
    assert (tmp_path / "NOTE-12.md").exists()


def test_export_note_creates_parent_directories(tmp_path) -> None:
    target = tmp_path / "a" / "b" / "out.md"
    with client_over(responder(200, GROCERIES)) as client:
        client.export_note("NOTE-12", target)
    assert target.exists()


def test_export_note_uses_the_ordinary_get_note_request() -> None:
    """No new route: the same ``GET /api/v1/notes/{ref}`` `note get` makes."""
    handler = responder(200, GROCERIES)
    with client_over(handler) as client:
        client.export_note("NOTE-12", "/dev/null")
    seen = handler.seen  # type: ignore[attr-defined]
    assert (seen.method, seen.url.path) == ("GET", "/api/v1/notes/NOTE-12")


def test_export_note_a_missing_note_is_an_api_error(tmp_path) -> None:
    body = {"error": {"code": "note_not_found", "message": "no such note"}}
    with client_over(responder(404, body)) as client, pytest.raises(ApiError) as excinfo:
        client.export_note("NOTE-999", tmp_path / "x.md")
    assert excinfo.value.status == 404


# --------------------------------------------------------------------------- export_all


def test_export_all_writes_one_file_per_note_at_its_path(tmp_path) -> None:
    with client_over(responder(200, NOTE_LIST_BODY)) as client:
        payload = client.export_all(tmp_path)

    assert (tmp_path / "home" / "groceries.md").exists()
    assert (tmp_path / "NOTE-3.md").exists()  # READING_LIST has an empty path
    assert {record["ref"] for record in payload.records} == {"NOTE-12", "NOTE-3"}


def test_export_all_bodies_match_the_api_response(tmp_path) -> None:
    with client_over(responder(200, NOTE_LIST_BODY)) as client:
        client.export_all(tmp_path)

    doc = parse_document((tmp_path / "home" / "groceries.md").read_text(encoding="utf-8"))
    assert doc.body == GROCERIES["body"]


def test_export_all_never_writes_outside_the_destination_directory(tmp_path) -> None:
    escaping = {**READING_LIST, "path": "../../../etc/passwd"}
    with client_over(responder(200, {"notes": [escaping]})) as client:
        payload = client.export_all(tmp_path)

    written = Path(payload.records[0]["file"]).resolve()
    assert written.is_relative_to(tmp_path.resolve())


def test_export_all_a_path_that_is_only_traversal_segments_falls_back_to_the_ref(tmp_path) -> None:
    escaping = {**READING_LIST, "path": "../.."}
    with client_over(responder(200, {"notes": [escaping]})) as client:
        payload = client.export_all(tmp_path)

    assert payload.records[0]["file"] == str(tmp_path / "NOTE-3.md")


# ----------------------------------------------------------------------------- claim_note


def test_claim_note_puts_to_the_ref_and_returns_the_note() -> None:
    handler = responder(201, {**GROCERIES, "ref": "NOTE-42"})
    with client_over(handler) as client:
        payload = client.claim_note("NOTE-42", title="Groceries", body="milk", path="x.md")

    seen = handler.seen  # type: ignore[attr-defined]
    assert (seen.method, seen.url.path) == ("PUT", "/api/v1/notes/NOTE-42")
    assert body_of(seen) == {"title": "Groceries", "body": "milk", "path": "x.md"}
    assert payload.record["ref"] == "NOTE-42"


def test_claim_note_omits_body_and_path_when_not_given() -> None:
    """The same ``None``-means-omitted rule `create_note`/`update_note` follow — see `_content`."""
    handler = responder(201, GROCERIES)
    with client_over(handler) as client:
        client.claim_note("NOTE-42", title="Groceries")

    assert body_of(handler.seen) == {"title": "Groceries"}  # type: ignore[attr-defined]


def test_claim_note_a_taken_ref_raises_api_error() -> None:
    body = {"error": {"code": "ref_taken", "message": "taken", "ref": "NOTE-42"}}
    with client_over(responder(409, body)) as client, pytest.raises(ApiError) as excinfo:
        client.claim_note("NOTE-42", title="x")
    assert excinfo.value.status == 409
    assert excinfo.value.code == "ref_taken"


def test_claim_note_percent_encodes_the_ref() -> None:
    """The same `_note_path` every other ref-taking method shares (KAN-541) — no second URL
    builder to forget the fix in."""
    handler = responder(201, GROCERIES)
    with client_over(handler) as client:
        client.claim_note("#NOTE-1", title="x")
    assert handler.seen.url.raw_path.decode() == "/api/v1/notes/%23NOTE-1"  # type: ignore[attr-defined]


# ------------------------------------------------------------- the round trip, chained for real


def test_export_then_import_round_trips_the_ref_when_it_is_free(tmp_path) -> None:
    """The literal round trip, and this card's headline claim made true: `export_note` writes a
    file; the note is deleted (its ref is now free); `import_note` reads the same file back and
    gets the *same* ref, via `claim_note`'s `PUT` — not a fresh one.
    """
    exported: list[httpx.Request] = []

    def export_handler(request: httpx.Request) -> httpx.Response:
        exported.append(request)
        return httpx.Response(200, json=GROCERIES)

    target = tmp_path / "NOTE-12.md"
    with client_over(export_handler) as client:
        client.export_note("NOTE-12", target)

    reimported: list[httpx.Request] = []

    def import_handler(request: httpx.Request) -> httpx.Response:
        reimported.append(request)
        assert request.method == "PUT", "the free-ref path never falls back to POST"
        return httpx.Response(201, json=GROCERIES)  # the same ref, reclaimed

    with client_over(import_handler) as client:
        payload = client.import_note(target)

    [put] = reimported
    assert put.url.path == "/api/v1/notes/NOTE-12"
    assert body_of(put) == {
        "title": GROCERIES["title"],
        "body": GROCERIES["body"],
        "path": GROCERIES["path"],
    }
    assert payload.record["ref"] == GROCERIES["ref"]
    assert payload.record["imported_from_ref"] == GROCERIES["ref"]
    assert payload.record["ref_reused"] is True


# -------------------------------------------------------------------------- import_note


def test_import_note_claims_the_files_own_ref_when_it_is_free(tmp_path) -> None:
    source = tmp_path / "in.md"
    source.write_text(
        '---\nkaya_ref: "NOTE-99"\ntitle: "Groceries"\npath: "home/groceries.md"\n---\n'
        "milk\neggs",
        encoding="utf-8",
    )
    handler = responder(201, {**GROCERIES, "ref": "NOTE-99"})
    with client_over(handler) as client:
        payload = client.import_note(source)

    seen = handler.seen  # type: ignore[attr-defined]
    assert (seen.method, seen.url.path) == ("PUT", "/api/v1/notes/NOTE-99")
    assert body_of(seen) == {
        "title": "Groceries",
        "body": "milk\neggs",
        "path": "home/groceries.md",
    }
    assert payload.record["ref"] == "NOTE-99"
    assert payload.record["imported_from_ref"] == "NOTE-99"
    assert payload.record["ref_reused"] is True


def test_import_note_with_no_front_matter_uses_the_filename_as_the_title(tmp_path) -> None:
    source = tmp_path / "Grocery List.md"
    source.write_text("just some prose, no front matter at all\n", encoding="utf-8")
    handler = responder(201, GROCERIES)
    with client_over(handler) as client:
        payload = client.import_note(source)

    assert body_of(handler.seen)["title"] == "Grocery List"  # type: ignore[attr-defined]
    assert payload.record["imported_from_ref"] is None


def test_import_note_prefers_an_h1_heading_over_the_filename(tmp_path) -> None:
    source = tmp_path / "Untitled.md"
    source.write_text("# Real Title\n\nSome prose.\n", encoding="utf-8")
    handler = responder(201, GROCERIES)
    with client_over(handler) as client:
        client.import_note(source)

    assert body_of(handler.seen)["title"] == "Real Title"  # type: ignore[attr-defined]


def test_import_note_a_file_that_does_not_exist_is_a_usage_error(tmp_path) -> None:
    with client_over(responder(201, GROCERIES)) as client, pytest.raises(UsageError):
        client.import_note(tmp_path / "nope.md")


# --------------------------------------------------------------- the ref-preservation finding


def test_import_note_falls_back_to_a_fresh_ref_when_the_files_own_ref_is_taken(tmp_path) -> None:
    """R12's 'taken' case: `claim_note`'s `PUT` gets a `409`, so `import_note` falls back to the
    ordinary `create_note` — a fresh, server-minted ref, exactly the "if taken or absent" half of
    BREADBOARD.md's R12 table.
    """
    source = tmp_path / "in.md"
    source.write_text('---\nkaya_ref: "NOTE-12"\ntitle: "Groceries"\n---\nmilk', encoding="utf-8")

    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "PUT":
            body = {"error": {"code": "ref_taken", "message": "taken", "ref": "NOTE-12"}}
            return httpx.Response(409, json=body)
        return httpx.Response(201, json={**GROCERIES, "ref": "NOTE-77", "id": 77})

    with client_over(handle) as client:
        payload = client.import_note(source)

    assert [r.method for r in seen] == ["PUT", "POST"], "PUT tried first, POST is the fallback"
    assert payload.record["ref"] == "NOTE-77"  # a fresh ref, never NOTE-12
    assert payload.record["imported_from_ref"] == "NOTE-12"
    assert payload.record["ref_reused"] is False


def test_import_note_falls_back_to_a_fresh_ref_when_the_files_own_ref_will_not_parse(
    tmp_path,
) -> None:
    """`claim_note` only accepts the canonical `NOTE-n` spelling (`backend/app/api/note_claim.py`),
    so a hand-typed `kaya_ref` that cannot even parse as a ref — a `400`, not a `409` — falls back
    exactly the same way a taken one does, rather than raising."""
    source = tmp_path / "in.md"
    source.write_text('---\nkaya_ref: "not-a-ref-at-all"\ntitle: "x"\n---\nmilk', encoding="utf-8")

    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "PUT":
            body = {"error": {"code": "invalid_note_ref", "message": "nope"}}
            return httpx.Response(400, json=body)
        return httpx.Response(201, json=GROCERIES)

    with client_over(handle) as client:
        payload = client.import_note(source)

    assert [r.method for r in seen] == ["PUT", "POST"]
    assert payload.record["ref_reused"] is False


def test_import_note_does_not_swallow_an_unrelated_failure_from_the_claim(tmp_path) -> None:
    """A `403`/`503`/anything else from `claim_note` is a real problem, not "this ref is
    unavailable" — the fallback exists for exactly two statuses, and only those two."""
    source = tmp_path / "in.md"
    source.write_text('---\nkaya_ref: "NOTE-12"\ntitle: "x"\n---\nmilk', encoding="utf-8")

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": {"code": "upstream_unavailable", "message": ""}})

    with client_over(handle) as client, pytest.raises(ApiError) as excinfo:
        client.import_note(source)
    assert excinfo.value.status == 503


# ---------------------------------------------------------------------------- import_dir


def test_import_dir_creates_a_note_per_markdown_file(tmp_path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.md").write_text('---\ntitle: "A"\n---\nbody a', encoding="utf-8")
    (tmp_path / "b.md").write_text('---\ntitle: "B"\n---\nbody b', encoding="utf-8")
    (tmp_path / "notes.txt").write_text("not markdown, skipped", encoding="utf-8")

    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "GET":
            return httpx.Response(404, json={"error": {"code": "note_not_found", "message": ""}})
        return httpx.Response(201, json=GROCERIES)

    with client_over(handle) as client:
        payload = client.import_dir(tmp_path)

    posts = [r for r in seen if r.method == "POST"]
    assert len(posts) == 2
    assert {body_of(r)["title"] for r in posts} == {"A", "B"}
    assert len(payload.records) == 2


def test_import_dir_sets_path_from_the_files_own_location(tmp_path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.md").write_text("no front matter here", encoding="utf-8")

    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json=GROCERIES)

    with client_over(handle) as client:
        client.import_dir(tmp_path)

    posts = [r for r in seen if r.method == "POST"]
    assert body_of(posts[0])["path"] == "sub/a.md"


def test_import_dir_a_path_that_is_not_a_directory_is_a_usage_error(tmp_path) -> None:
    missing = tmp_path / "nope"
    with client_over(responder(201, GROCERIES)) as client, pytest.raises(UsageError):
        client.import_dir(missing)


def test_import_dir_resolves_a_wikilink_once_its_target_lands_later_in_the_walk(tmp_path) -> None:
    """The unresolved-then-resolves case: a file naming ``[[Recipes]]`` is walked before
    ``recipes.md`` exists. This client makes one request per file in a fixed order and does no
    batching — the backend's own KAN-563 reconciliation (``resolve_pending_note_links``) is what
    closes the loop the moment the second file is created, in the same transaction. What this test
    pins is the **request order**: ``a.md`` (the linker) is created before ``recipes.md`` (the
    target), which is exactly the case a naive "create in dependency order" implementation would
    get wrong by trying to reorder the walk instead of trusting the server.
    """
    (tmp_path / "a.md").write_text(
        '---\ntitle: "Groceries"\n---\nSee [[Recipes]] for ideas.', encoding="utf-8"
    )
    (tmp_path / "recipes.md").write_text(
        '---\ntitle: "Recipes"\n---\nSome recipes.', encoding="utf-8"
    )

    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json=GROCERIES)

    with client_over(handle) as client:
        client.import_dir(tmp_path)

    posts = [r for r in seen if r.method == "POST"]
    titles = [body_of(r)["title"] for r in posts]
    # Sorted walk order: "a.md" sorts before "recipes.md", so the linker is created first — the
    # server, not this client, is what has to cope with that (and does, per KAN-563).
    assert titles == ["Groceries", "Recipes"]
