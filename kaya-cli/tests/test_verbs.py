"""`kaya note list` and `kaya note get <ref>`: the wiring, and only the wiring.

SLICES §V2a step 5 is deliberately two verbs. What this file asserts is that argv reaches the right
client method, that the identifier arrives untouched, and that what comes back is printed by
``render`` — nothing about *how* it is printed, because that is `kaya-client`'s and is pinned there.

The one assertion that looks like a formatting test is
`test_the_default_row_matches_the_clients_pin`, and it is the opposite of one: it exists to prove
this package added no formatting of its own between ``render`` and stdout.
"""

import argparse
import json

import httpx
import pytest
from conftest import ENTITY_HELP, GROCERIES, LIST_HELP, NOTES, READING_LIST

from kaya_cli import verbs
from kaya_cli.__main__ import build_parser, main

LIST_ROWS = (
    "NOTE-12  Groceries       home/groceries.md\nNOTE-3   A reading list\n\n2 notes\n\n"
    + LIST_HELP
)
"""`kaya-client/tests/test_human_row_is_pinned.py`'s literal, character for character.

The trailing ``2 notes`` is ADR 0005 §contract 5's summary line, which KAN-548 added **in the
client**, and the two ``help:`` lines under it are §contract 8's templates, which KAN-550 added in
the client too. They are here for the same reason every other byte is: if this package ever computed
a footer or a next-step line of its own, the two literals would still agree and nothing would
notice — so what the assertion below really checks is that the adapter is still printing what
``render`` returned and nothing more."""

SINGLE_NOTE = (
    "ref         NOTE-12\n"
    "title       Groceries\n"
    "path        home/groceries.md\n"
    "created_at  2026-08-01T09:15:00+00:00\n"
    "updated_at  2026-08-09T11:02:33.123456+00:00\n"
    "\n"
    "milk\n"
    "eggs\n"
    "\n" + ENTITY_HELP
)

LISTED = {**NOTES, "summary": {"count": 2}}
"""A structured `note list`: the API's envelope plus the aggregate beside it (KAN-548). The
``notes`` array is untouched, so a consumer written against `/api/v1/notes` reads it unchanged."""

NOTE_LIST_TOON = (
    "notes[2]{ref,id,title,body,path,created_at,updated_at}:\n"
    '  NOTE-12,12,Groceries,"milk\\neggs",home/groceries.md,'
    '"2026-08-01T09:15:00+00:00","2026-08-09T11:02:33.123456+00:00"\n'
    '  NOTE-3,3,A reading list,"","",'
    '"2026-07-14T18:00:00+00:00","2026-07-14T18:00:00+00:00"\n'
    "summary:\n"
    "  count: 2"
)
"""KAN-548 turned this into a **mixed** TOON document: a tabular array and then a keyed object.
That is a shape the note payloads never produced before, which is why
`kaya-client/tests/test_aggregates.py` re-asserts the round trip over it."""


# ------------------------------------------------------------------- what argv reaches


def test_note_list_calls_the_list_endpoint(capsys, answering) -> None:
    seen = answering(200, NOTES)
    code = main(["note", "list"])

    assert code == 0
    assert [(r.method, r.url.path) for r in seen] == [("GET", "/api/v1/notes")]
    assert capsys.readouterr().out == f"{LIST_ROWS}\n"


def test_note_list_with_q_forwards_it_as_a_query_parameter(answering) -> None:
    """KAN-559: ``--q`` reaches `KayaClient.list_notes` and from there the wire, untouched."""
    seen = answering(200, NOTES)
    code = main(["note", "list", "--q", "reading list"])

    assert code == 0
    assert len(seen) == 1
    assert seen[0].url.path == "/api/v1/notes"
    assert dict(seen[0].url.params) == {"q": "reading list"}


def test_note_list_with_no_q_is_the_same_request_as_before(answering) -> None:
    """Omitting ``--q`` must change nothing about the request `note list` already made."""
    seen = answering(200, NOTES)
    main(["note", "list"])

    assert seen[0].url.query == b""


def test_note_list_composes_with_fields_and_the_summary(capsys, answering) -> None:
    """The card's own acceptance line: `--q` composes with `--fields` and the aggregate describes
    the *matched* set, not the corpus — true here by construction (`attach_summary` takes one
    payload) but CLAUDE.md's rule is that a structural guard does not cover a behavioural claim, so
    it is asserted end to end rather than cited.
    """
    answering(200, NOTES)
    main(["note", "list", "--q", "reading", "--fields", "ref,title", "--format", "json"])

    printed = json.loads(capsys.readouterr().out)
    assert printed["notes"] == [
        {"ref": "NOTE-12", "title": "Groceries"},
        {"ref": "NOTE-3", "title": "A reading list"},
    ]
    assert printed["summary"] == {"count": 2}


def test_a_blank_q_is_the_apis_refusal_not_a_silent_list(capsys, answering) -> None:
    """`kaya note list --q "$TERM"` with ``TERM`` unset must not quietly return the whole corpus —
    it is the API's `400 empty_search_query`, which ADR 0005's table already maps to exit `2`.
    """
    answering(
        400,
        {"error": {"code": "empty_search_query", "message": "q was empty"}},
    )
    code = main(["note", "list", "--q", ""])

    assert code == 2
    out = capsys.readouterr().out
    assert out.startswith("error\tempty_search_query\t")


def test_note_get_calls_the_single_note_endpoint(capsys, answering) -> None:
    seen = answering(200, GROCERIES)
    code = main(["note", "get", "NOTE-12"])

    assert code == 0
    assert [(r.method, r.url.path) for r in seen] == [("GET", "/api/v1/notes/NOTE-12")]
    assert capsys.readouterr().out == f"{SINGLE_NOTE}\n"


@pytest.mark.parametrize(
    ("ref", "sent"),
    [
        ("NOTE-12", "/api/v1/notes/NOTE-12"),
        ("note-12", "/api/v1/notes/note-12"),
        ("12", "/api/v1/notes/12"),
        ("#NOTE-12", "/api/v1/notes/%23NOTE-12"),
    ],
)
def test_the_ref_reaches_the_api_untouched(answering, ref: str, sent: str) -> None:
    """ADR 0008 puts every spelling through one resolver in `backend/app/api/refs.py`, so a missing
    note is the same `404` byte for byte whichever spelling asked for it, and ``#NOTE-12`` is a
    `400`. Normalising in an adapter would be a second resolver, and the first thing a second
    resolver does is disagree — ``#NOTE-12`` would become a silent success against a client that
    stripped the ``#``. So the list includes the spelling that must *fail*, and it must fail at the
    API rather than here: the encoding is the client's (see `KayaClient.get_note`), and what this
    asserts is that the CLI added no opinion of its own on top of it.
    """
    seen = answering(200, GROCERIES)
    main(["note", "get", ref])

    assert seen[0].url.raw_path.decode() == sent


def test_the_bearer_is_forwarded_and_not_parsed(answering) -> None:
    """ADR 0002: kaya has no token format. The CLI is one more layer that must not learn one."""
    seen = answering(200, NOTES)
    main(["note", "list"])

    assert seen[0].headers["Authorization"] == "Bearer kanban_pat_notarealtokenatall"


def test_an_empty_list_is_a_definitive_zero_state(capsys, answering) -> None:
    """Not an empty stdout, which is indistinguishable from a crashed pipe. The wording is the
    client's; what this checks is that the CLI prints it rather than short-circuiting on falsiness —
    ``if payload:`` above the print would swallow exactly this case."""
    answering(200, {"notes": []})

    assert main(["note", "list"]) == 0
    assert capsys.readouterr().out == "no notes\n\nhelp: kaya note create <title>\n"


# ------------------------------------------------------ the ADR 0004 boundary, asserted


def test_the_default_row_matches_the_clients_pin(capsys, answering) -> None:
    """The whole point of this package existing as a thin adapter.

    ``LIST_ROWS`` is copied from `kaya-client/tests/test_human_row_is_pinned.py`, so if `kaya-cli`
    ever grew a formatting rule — a header, a sort, a widened column, a trailing summary — the two
    literals would disagree and this is the test that would say so. A projection rule appearing in
    this package is a bug, not a local optimisation (ADR 0004).
    """
    answering(200, NOTES)
    main(["note", "list"])

    assert capsys.readouterr().out.rstrip("\n") == LIST_ROWS


def test_the_structured_output_is_the_apis_own_envelope(capsys, answering) -> None:
    """``{"notes": [...]}``, with every field the API returned, unprojected, plus KAN-548's
    ``summary`` as a sibling key. V2a's job was to prove nothing is being *dropped*, and the
    envelope is still the API's own — the aggregate sits beside it rather than wrapping it."""
    answering(200, NOTES)
    main(["note", "list", "--format", "json"])

    assert json.loads(capsys.readouterr().out) == LISTED


def test_a_single_read_is_the_bare_object(capsys, answering) -> None:
    answering(200, GROCERIES)
    main(["note", "get", "12", "--format", "json"])

    assert json.loads(capsys.readouterr().out) == GROCERIES


def test_toon_reaches_stdout_as_the_client_encodes_it(capsys, answering) -> None:
    """The third format, through the real CLI. The literal is `kaya-client`'s corpus, so this is the
    same "did the adapter add anything?" question the human pin asks, in the format most likely to
    be post-processed by a well-meaning adapter."""
    answering(200, NOTES)
    main(["note", "list", "--format", "toon"])

    assert capsys.readouterr().out == f"{NOTE_LIST_TOON}\n"


def test_every_format_prints_exactly_one_trailing_newline(capsys, answering) -> None:
    """``print`` adds one and no serializer emits one. Two would put a blank line between a payload
    and the next thing a shell writes, and a consumer's ``.strip()`` is how that becomes permanent.
    """
    for fmt in ("human", "json", "toon"):
        answering(200, NOTES)
        main(["note", "list", "--format", fmt])
        out = capsys.readouterr().out

        assert out.endswith("\n")
        assert not out.endswith("\n\n")


# ------------------------------------------------------------- the table and the parser


def test_every_parser_word_has_a_verb_and_every_verb_has_a_parser_word() -> None:
    """`build_parser` and the dispatch tables cannot drift about which words exist.

    A subparser without a row is a ``KeyError`` at dispatch — a traceback where a structured refusal
    belongs. A row without a subparser is dead code that reads as a shipped feature. KAN-551 added
    seven words and this is what would have failed if it had added only one half of any of them.

    ``verbs.BARE`` is the one row with **no** parser word — ADR 0005 §contract 7's bare `kaya`,
    KAN-549 — so it is added to the left-hand side by name. Named rather than filtered out of the
    right, because "there is exactly one wordless verb" is the claim being made, and a filter would
    let a second one arrive unremarked.
    """
    assert _parser_words(build_parser()) | {verbs.BARE} == set(verbs.VERBS) | set(verbs.LOCAL_VERBS)


def test_the_two_dispatch_tables_are_disjoint() -> None:
    """A word in both tables would dispatch to whichever `run` happened to check first, and the
    other row would be dead code that reads as the implementation. The split is about the session
    (`config show` must answer with no token at all), so overlap is not a merge — it is two
    different answers to "does this verb talk to the API?"."""
    assert not set(verbs.VERBS) & set(verbs.LOCAL_VERBS)


def test_the_published_verb_set_is_pinned() -> None:
    """SLICES §V2b step 6's list plus §V5 step 6's two, written out so that adding a verb is a
    visible edit here.

    The same discipline as `kaya-client`'s pin on ``CLI_FORMATS``: a verb reaching a shell is a
    published contract, and the way one arrives unnoticed is as a side effect of a refactor that
    was about something else.
    """
    assert _parser_words(build_parser()) == {
        ("note", "list"),
        ("note", "get"),
        ("note", "create"),
        ("note", "edit"),
        ("note", "move"),
        ("note", "delete"),
        ("config", "set"),
        ("config", "show"),
        ("config", "path"),
        ("links", None),
        ("backlinks", None),
    }


def _parser_words(parser) -> set[tuple[str, str | None]]:
    """``{(command, subcommand)}`` as the parser actually accepts them, at either depth.

    **KAN-566 widened this, and the widening is the point rather than an accommodation.** Until
    then every word lived under a group, so "two levels deep" and "every word" were the same set
    and this helper could assume it. `links` and `backlinks` are top-level verbs (see
    ``__main__._add_link_verbs`` for why), and a top-level verb's key is ``(word, None)`` —
    argparse leaves ``subcommand`` at the top-level default because only the two groups declare
    that ``dest``.

    Written as "a command with subparsers contributes its children, a command without contributes
    itself" rather than as a union of two hard-coded shapes, so the guard covers a third shape
    nobody has thought of: a group that gains a sub-subcommand, or a top-level verb added later.
    The alternative — leaving the two-level walk alone and naming the new words on the other side of
    the assertion, the way ``verbs.BARE`` is named — would have made the drift guard blind to
    exactly the words it was widened for.
    """
    words: set[tuple[str, str | None]] = set()
    for command, child in _subparsers(parser).items():
        children = _subparsers(child)
        if children:
            words |= {(command, word) for word in children}
        else:
            words.add((command, None))
    return words


def _subparsers(parser) -> dict:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


def test_a_misspelt_verb_is_a_usage_error_not_a_traceback(capsys) -> None:
    """`kaya note lst`. The subparser is a ``StructuredParser`` through ``parser_class``, so it
    raises where a plain ``ArgumentParser`` would have called ``sys.exit`` — the asymmetry
    `kaya_cli.parsing` overrode ``exit`` to prevent."""
    code = main(["note", "lst"])
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out.startswith("error\tusage\t")
    assert "usage: kaya note" in captured.err


def test_a_bare_group_word_is_a_usage_error(capsys) -> None:
    """`kaya note` alone names nothing to do. ``required=True`` on the subparsers makes argparse say
    which words it accepts, rather than the CLI dispatching on ``None``."""
    code = main(["note"])
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out.startswith("error\tusage\t")
    assert "list" in captured.err and "get" in captured.err


def test_note_get_without_a_ref_is_a_usage_error(capsys) -> None:
    code = main(["note", "get"])
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out.startswith("error\tusage\t")
    assert "ref" in captured.err


def test_a_verb_that_has_not_landed_is_still_refused(capsys) -> None:
    """The shape of this test outlived the list it was written for.

    It began as "the write verbs have not landed" and passed for `create`/`edit`/`move`/`delete`
    until KAN-551 shipped them — at which point it would have gone on passing, because every one of
    those words now fails for a *different* reason (a missing positional). That is the failure mode
    it was written to catch, so the list is now the words that genuinely do not exist. `search` is
    KAN-558/559's and `archive` is nobody's.

    KAN-566 added `links` and `backlinks` to this list rather than removing anything from it,
    which reads backwards until you notice the group: they exist at the **top level**, so
    `kaya note links` is still a usage error and must stay one. A `note` subgroup that quietly
    accepted them would be a second spelling of a published verb, which is the class of thing
    `test_the_published_verb_set_is_pinned` exists to keep visible.
    """
    for word in ("search", "archive", "link", "links", "backlinks"):
        assert main(["note", word]) == 2
        assert capsys.readouterr().out.startswith("error\tusage\t")


def test_a_verb_makes_exactly_one_request(answering) -> None:
    """No retry, no pre-flight, no second call to warm anything. `KayaClient._request` is where a
    retry would land if KAN-666's measurement ever asks for one, and nothing retries today."""
    seen = answering(200, NOTES)
    main(["note", "list"])

    assert len(seen) == 1


def test_the_client_is_closed_even_when_the_verb_fails(fake_api) -> None:
    """`verbs.run` uses ``with``, so a `404` does not leak a connection pool. Asserted through the
    client's own lifecycle rather than by inspecting httpx internals."""
    closed: list[bool] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"code": "note_not_found", "message": "no"}})

    fake_api(handler)
    original = verbs.open_client

    def watching():
        client = original()
        real_close = client.close

        def close() -> None:
            closed.append(True)
            real_close()

        client.close = close  # type: ignore[method-assign]
        return client

    verbs.open_client = watching
    try:
        assert main(["note", "get", "NOTE-9999"]) == 5
    finally:
        verbs.open_client = original

    assert closed == [True]


def test_the_note_that_is_not_yours_is_a_403_not_an_empty_result(capsys, answering) -> None:
    """`app/auth/authorization.py` goes to real trouble to keep "not yours" and "not there" apart,
    and the CLI must not collapse them back into one outcome."""
    answering(403, {"error": {"code": "note_forbidden", "message": "not yours"}})

    assert main(["note", "get", "NOTE-1"]) == 4
    assert capsys.readouterr().out.startswith("error\tnote_forbidden\t")


def test_reading_a_note_with_a_missing_column_does_not_crash(capsys, answering) -> None:
    """A column the API stopped sending is a hole in a row, not a traceback — the client's rule,
    checked here because a deploy skew is the one way it happens in the field."""
    thin = {key: value for key, value in READING_LIST.items() if key != "path"}
    answering(200, {"notes": [thin]})

    assert main(["note", "list"]) == 0
    expected = f"NOTE-3  A reading list\n\n1 note\n\n{LIST_HELP}\n"
    assert capsys.readouterr().out == expected
