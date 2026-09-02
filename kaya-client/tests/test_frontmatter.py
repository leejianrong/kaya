"""`compose_document`/`parse_document`: the R12 file format, with no I/O and no ``KayaClient``.

A note's body carries its ``[[Title]]`` wikilinks verbatim — R12's headline finding is that no
rewriting is needed — so every round-trip assertion here is really an assertion that the body
crossed the boundary untouched.
"""

from kaya_client.frontmatter import compose_document, parse_document

GROCERIES = {
    "ref": "NOTE-12",
    "id": 12,
    "title": "Groceries",
    "body": "milk\neggs\n\nSee [[Recipes]] for ideas.",
    "path": "home/groceries.md",
    "created_at": "2026-08-01T09:15:00+00:00",
    "updated_at": "2026-08-09T11:02:33.123456+00:00",
}


def test_compose_document_writes_the_five_front_matter_fields_and_the_fence() -> None:
    text = compose_document(GROCERIES)
    lines = text.splitlines()
    assert lines[0] == "---"
    assert lines[1] == 'kaya_ref: "NOTE-12"'
    assert lines[2] == 'title: "Groceries"'
    assert lines[3] == 'path: "home/groceries.md"'
    assert lines[4] == 'created_at: "2026-08-01T09:15:00+00:00"'
    assert lines[5] == 'updated_at: "2026-08-09T11:02:33.123456+00:00"'
    assert lines[6] == "---"


def test_compose_document_never_writes_id() -> None:
    """ADR 0008: a note's identity is its ref, never the internal surrogate. Publishing ``id``
    beside ``kaya_ref`` in a file would hand a reader two identifiers and no rule for which one to
    keep."""
    assert "id:" not in compose_document(GROCERIES)
    assert "\n12\n" not in compose_document(GROCERIES)


def test_compose_document_writes_the_body_verbatim_with_no_link_rewriting() -> None:
    text = compose_document(GROCERIES)
    assert text.endswith(GROCERIES["body"])
    assert "[[Recipes]]" in text


def test_parse_document_is_the_inverse_of_compose_document() -> None:
    text = compose_document(GROCERIES)
    doc = parse_document(text)
    assert doc.get("kaya_ref") == "NOTE-12"
    assert doc.get("title") == "Groceries"
    assert doc.get("path") == "home/groceries.md"
    assert doc.get("created_at") == GROCERIES["created_at"]
    assert doc.get("updated_at") == GROCERIES["updated_at"]
    assert doc.body == GROCERIES["body"]


def test_parse_document_round_trips_a_title_containing_a_colon() -> None:
    """Unquoted, a YAML reader would truncate ``"Design: notes"`` at the colon. This module always
    quotes on the way out, so the round trip is unambiguous regardless."""
    record = {**GROCERIES, "title": "Design: notes for the sprint"}
    doc = parse_document(compose_document(record))
    assert doc.get("title") == "Design: notes for the sprint"


def test_parse_document_round_trips_embedded_quotes_and_backslashes() -> None:
    record = {**GROCERIES, "title": 'A "quoted" \\ title'}
    doc = parse_document(compose_document(record))
    assert doc.get("title") == 'A "quoted" \\ title'


def test_a_file_with_no_front_matter_is_read_as_all_body() -> None:
    """The corpus-import case: an arbitrary markdown file, no kaya shape at all."""
    text = "# Just a heading\n\nSome prose with a [[Wikilink]].\n"
    doc = parse_document(text)
    assert doc.front_matter == {}
    assert doc.body == text


def test_an_unclosed_fence_is_read_as_all_body() -> None:
    """A note body that itself opens with a horizontal rule and never closes one — treated as no
    front matter at all rather than as a parse error, per this module's safe-default rule."""
    text = "---\nnot actually front matter, just a rule\nand more prose\n"
    doc = parse_document(text)
    assert doc.front_matter == {}
    assert doc.body == text


def test_front_matter_lines_this_module_does_not_understand_are_skipped_not_refused() -> None:
    """A real Obsidian vault's front matter (tags, lists) is read past rather than rejected."""
    text = (
        "---\n"
        "title: Reading list\n"
        "tags: [books, 2026]\n"
        "kaya_ref: NOTE-9\n"
        "---\n"
        "Body text.\n"
    )
    doc = parse_document(text)
    assert doc.get("title") == "Reading list"
    assert doc.get("kaya_ref") == "NOTE-9"
    assert doc.body == "Body text.\n"


def test_a_bare_unquoted_scalar_is_read_as_is() -> None:
    """A hand-written or Obsidian-authored file need not quote its scalars for this module to read
    them — only this module's own *output* is always quoted."""
    text = "---\ntitle: Groceries\n---\nmilk\n"
    assert parse_document(text).get("title") == "Groceries"


def test_compose_document_omits_a_missing_field_rather_than_writing_none() -> None:
    record = {"ref": "NOTE-1", "title": "x", "body": ""}
    text = compose_document(record)
    assert "path" not in text
    assert "None" not in text
