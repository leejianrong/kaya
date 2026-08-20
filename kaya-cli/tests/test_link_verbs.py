"""`kaya links <ref>` and `kaya backlinks <ref>`: the wiring, and only the wiring — KAN-566.

The same brief as `test_verbs.py`'s: argv reaches the right client method, the identifier arrives
untouched, and what comes back is printed by ``render`` with nothing added. What is *not* asserted
here is how a link row looks — that is `kaya-client/tests/test_links.py`'s, and the two assertions
below that look like formatting tests are the opposite of ones, exactly as
`test_the_default_row_matches_the_clients_pin` is.

These two verbs carry one thing the other nine do not: they are top-level words, so they are the
first rows in ``verbs.VERBS`` keyed on ``(word, None)``. `test_verbs.py` owns the drift guard for
that; what this file adds is that the dispatch actually *works*, because a table that agrees with a
parser it never dispatches through would satisfy the guard and refuse every call.
"""

import json

from conftest import LIST_HELP, NOTES

from kaya_cli.__main__ import main

RESOLVED_CARD = {
    "target_kind": "KAN",
    "target_ref": "KAN-501",
    "resolved_ref": "KAN-501",
    "title": "MCP read tools",
    "column": "in_progress",
}
UNRESOLVED_CARD = {
    "target_kind": "KAN",
    "target_ref": "KAN-999",
    "resolved_ref": None,
    "title": None,
    "column": None,
}
RENAMED_NOTE = {
    "target_kind": "NOTE",
    "target_ref": "Old Name",
    "resolved_ref": "NOTE-7",
    "title": "New Name",
    "column": None,
}

LINKS = {"links": [RESOLVED_CARD, UNRESOLVED_CARD, RENAMED_NOTE]}


# ------------------------------------------------------------------- what argv reaches


def test_links_calls_the_links_sub_resource(capsys, answering) -> None:
    seen = answering(200, LINKS)
    code = main(["links", "NOTE-12"])

    assert code == 0
    assert [(r.method, r.url.path) for r in seen] == [("GET", "/api/v1/notes/NOTE-12/links")]
    assert capsys.readouterr().out


def test_backlinks_calls_the_backlinks_sub_resource(capsys, answering) -> None:
    seen = answering(200, NOTES)
    code = main(["backlinks", "NOTE-3"])

    assert code == 0
    assert [(r.method, r.url.path) for r in seen] == [("GET", "/api/v1/notes/NOTE-3/backlinks")]
    assert capsys.readouterr().out


def test_a_top_level_verb_dispatches_through_the_same_table(answering) -> None:
    """The claim `test_verbs.py`'s drift guard cannot make.

    That guard proves ``("links", None)`` is in ``VERBS`` and is a parser word. It stays green if
    argparse never actually leaves ``subcommand`` as ``None`` — a subgroup declared by accident, a
    ``set_defaults`` moved — at which point every call is a ``KeyError``. So this asserts the round
    trip: argv in, a request out, exit `0`.
    """
    seen = answering(200, LINKS)

    assert main(["links", "12"]) == 0
    assert len(seen) == 1


def test_each_link_verb_makes_exactly_one_request(answering) -> None:
    """No pre-flight read of the note itself: `/links` and `/backlinks` resolve the ref on their
    own behalf (ADR 0008), so fetching the note first would be a request made to learn something
    the real one already refuses correctly."""
    for verb, body in (("links", LINKS), ("backlinks", NOTES)):
        seen = answering(200, body)
        before = len(seen)
        main([verb, "NOTE-12"])
        assert len(seen) - before == 1


def test_the_ref_reaches_the_api_untouched_on_both_verbs(answering) -> None:
    """ADR 0008, over the four spellings `test_verbs.py` already uses for `note get`, including the
    one that must **fail**: ``#NOTE-12`` is a `400` from the API and would be a silent success
    against an adapter that stripped the ``#``."""
    for verb in ("links", "backlinks"):
        for ref, sent in (
            ("NOTE-12", f"/api/v1/notes/NOTE-12/{verb}"),
            ("note-12", f"/api/v1/notes/note-12/{verb}"),
            ("12", f"/api/v1/notes/12/{verb}"),
            ("#NOTE-12", f"/api/v1/notes/%23NOTE-12/{verb}"),
        ):
            seen = answering(200, {"links": [], "notes": []})
            main([verb, ref])
            assert seen[-1].url.raw_path.decode() == sent


def test_backlinks_of_a_ticket_ref_is_the_apis_refusal_and_not_a_second_ref_parser(
    capsys, answering
) -> None:
    """SLICES §V5's demo asks for `kaya backlinks KAN-501`. **This card ships the note case only**,
    and the refusal is the API's `400 invalid_note_ref` — which ADR 0005's table already maps to
    exit `2` — rather than anything this package noticed about the prefix.

    That is the assertion, not an admission: an adapter that saw ``KAN-`` and reached for a
    different endpoint would be a second ref parser in the one place ADR 0008 forbids one, and the
    first thing a second resolver does is disagree with the first. The `400`'s message names the
    spellings that work, which is a better answer than an empty list.
    """
    seen = answering(
        400,
        {
            "error": {
                "code": "invalid_note_ref",
                "message": "not a note reference: 'KAN-501'. Use NOTE-12, note-12 or 12.",
                "ref": "KAN-501",
            }
        },
    )
    code = main(["backlinks", "KAN-501"])
    out = capsys.readouterr().out

    assert code == 2
    assert out.startswith("error\tinvalid_note_ref\t")
    assert seen[0].url.raw_path.decode() == "/api/v1/notes/KAN-501/backlinks", (
        "the ref goes to the API verbatim; nothing here classifies it"
    )


# ---------------------------------------------------- the ADR 0004 boundary, asserted


def test_a_links_render_carries_no_footer_or_hint_this_package_invented(capsys, answering) -> None:
    """A `link` collection has no row in `kaya_client.hints`, so there are no ``help:`` lines — and
    the ``3 links`` footer is the client's ``summary_line``, built from the client's own noun and
    envelope. If this package ever computed either, this is the assertion that would disagree."""
    answering(200, LINKS)
    main(["links", "NOTE-12"])

    out = capsys.readouterr().out

    assert "help:" not in out
    assert out.rstrip("\n").endswith("3 links")


def test_a_backlinks_render_is_byte_identical_to_a_note_list(capsys, answering) -> None:
    """The strongest form of "`/backlinks` returns the same envelope a list does". Two invocations,
    one body, one expected string — so a column, a noun or a footer that diverged for one verb and
    not the other is a red test here rather than a discovery in the field."""
    answering(200, NOTES)
    main(["backlinks", "NOTE-3"])
    from_backlinks = capsys.readouterr().out

    answering(200, NOTES)
    main(["note", "list"])
    from_list = capsys.readouterr().out

    assert from_backlinks == from_list
    assert LIST_HELP in from_backlinks


def test_the_structured_output_is_the_apis_own_envelope_for_each_verb(capsys, answering) -> None:
    answering(200, LINKS)
    main(["links", "NOTE-12", "--format", "json"])
    assert json.loads(capsys.readouterr().out) == {**LINKS, "summary": {"count": 3}}

    answering(200, NOTES)
    main(["backlinks", "NOTE-3", "--json"])
    assert json.loads(capsys.readouterr().out) == {**NOTES, "summary": {"count": 2}}


def test_fields_and_format_are_available_on_both_verbs(capsys, answering) -> None:
    """ADR 0005 §contract 1 is a promise about *every* verb, and the way it breaks is a verb added
    later without the flags. These two are the first added outside a subcommand group, so they are
    the first that could have missed the shared parent parser."""
    answering(200, LINKS)
    main(["links", "NOTE-12", "--fields", "target_ref,resolved_ref", "--format", "json"])
    printed = json.loads(capsys.readouterr().out)

    assert printed["links"][0] == {"target_ref": "KAN-501", "resolved_ref": "KAN-501"}

    answering(200, NOTES)
    main(["backlinks", "NOTE-3", "--fields", "ref", "--format", "toon"])
    assert capsys.readouterr().out.startswith("notes[2]{ref}:")


def test_full_is_accepted_on_a_links_read_even_though_it_has_nothing_to_do(
    capsys, answering
) -> None:
    """``--full`` is on every verb because it applies to every verb, and a link payload has an empty
    prose allow-list — so this is a flag that is legal, harmless and changes nothing, which is the
    honest consequence of the flags living on one parent parser."""
    answering(200, LINKS)
    assert main(["links", "NOTE-12", "--full", "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["links"][0]["title"] == "MCP read tools"


def test_a_broken_text_limit_does_not_lock_a_caller_out_of_links(monkeypatch, answering) -> None:
    """KAN-551's lockout bug, checked at the verb that inherits the fix rather than earns it.

    `__main__` resolves ``KAYA_MAX_TEXT_CHARS`` only for a payload with prose fields, and a link
    payload has none, so an unparseable value in the environment cannot refuse this read. The guard
    is a fact about the payload rather than a list of verb names, which is exactly why a verb added
    two cards later gets it for nothing — asserted because "inherited for free" is the kind of claim
    that stops being true quietly.
    """
    from kaya_client import config

    monkeypatch.setenv(config.MAX_TEXT_CHARS_ENV, "not-a-number")
    answering(200, LINKS)

    assert main(["links", "NOTE-12"]) == 0


def test_the_broken_text_limit_still_refuses_a_backlinks_read(
    monkeypatch, capsys, answering
) -> None:
    """The positive control for the test above, and it points the other way on purpose.

    A backlinks payload *is* a note payload, prose fields and all, so the same broken value is exit
    `2` here — which is what proves the previous test passed because the limit was never resolved,
    rather than because a bad value is tolerated everywhere.
    """
    from kaya_client import config

    monkeypatch.setenv(config.MAX_TEXT_CHARS_ENV, "not-a-number")
    answering(200, NOTES)

    assert main(["backlinks", "NOTE-3"]) == 2
    assert capsys.readouterr().out.startswith("error\t")


# ------------------------------------------------------------------------- usage errors


def test_a_link_verb_without_a_ref_is_a_usage_error(capsys) -> None:
    for verb in ("links", "backlinks"):
        assert main([verb]) == 2
        captured = capsys.readouterr()
        assert captured.out.startswith("error\tusage\t")
        assert "ref" in captured.err


def test_the_client_is_closed_when_a_link_verb_fails(answering) -> None:
    """`verbs.run` opens the session with ``with`` for these two exactly as it does for the other
    seven, because they are rows in the same table and there is no second dispatch path."""
    answering(404, {"error": {"code": "note_not_found", "message": "no such note"}})

    assert main(["backlinks", "NOTE-9999"]) == 5


def test_another_users_note_is_403_on_both_verbs(capsys, answering) -> None:
    for verb in ("links", "backlinks"):
        answering(403, {"error": {"code": "note_forbidden", "message": "not yours"}})
        assert main([verb, "NOTE-1"]) == 4
        assert capsys.readouterr().out.startswith("error\tnote_forbidden\t")
