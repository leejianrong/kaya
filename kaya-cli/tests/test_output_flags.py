"""``--format {human,json,toon}``, ``--json``, and which one wins. ADR 0005 §contract 1.

The contract is two sentences and one of them is a precedence rule: "``--json`` is a documented
alias for ``--format json``; **``--format`` wins if both are given**". A precedence rule that is
never exercised with both flags present is a rule nobody has checked, so it is exercised here in
both argv orders — because the tempting implementation, `--format`'s default being ``"human"``, gets
one order right by accident.
"""

import json

import pytest
from conftest import GROCERIES, NOTES
from kaya_client import CLI_FORMATS

from kaya_cli.__main__ import build_parser, main

LIST_ROWS = "NOTE-12  Groceries       home/groceries.md\nNOTE-3   A reading list\n\n2 notes"
"""`kaya-client/tests/test_human_row_is_pinned.py`'s literal, footer included since KAN-548."""

LISTED = {**NOTES, "summary": {"count": 2}}
"""What a structured `note list` carries: the API's own envelope plus ADR 0005 §contract 5's
aggregate beside it. The `notes` array is untouched — the summary is a sibling key, not a
wrapper — so anything written against `/api/v1/notes` still reads it from the same place."""

TOON_FIRST_LINE = "notes[2]{ref,id,title,body,path,created_at,updated_at}:"


# ------------------------------------------------------------------ the vocabulary


def test_the_flag_offers_exactly_the_published_vocabulary() -> None:
    """SLICES §V2a publishes ``{human, json, toon}``. ``choices`` comes from ``CLI_FORMATS``, which
    is derived from the client's ``Format`` enum, so this asserts the whole chain rather than a
    tuple this package wrote down for itself."""
    action = _flag(build_parser(), "--format")

    assert tuple(action.choices) == ("human", "json", "toon")
    assert tuple(action.choices) == CLI_FORMATS


def test_the_adapter_only_format_is_not_offered() -> None:
    """``data`` renders and is never advertised — it is for V6's MCP ``structuredContent``, asked
    for in code and not by a value a person typed. A CLI that offered it would be publishing a
    contract ADR 0005 says cannot be cheaply withdrawn."""
    assert "data" not in _flag(build_parser(), "--format").choices


@pytest.mark.parametrize("verb", [["note", "list"], ["note", "get", "NOTE-12"]])
def test_every_verb_carries_both_flags(verb: list[str]) -> None:
    """Contract 1 is a promise about *every* verb, and the way it breaks is one verb added in V2b
    without the flags. `parsing.output_flags` is a parent parser precisely so that cannot happen;
    this is the assertion that would notice if someone stopped using it."""
    args = build_parser().parse_args(verb)

    assert hasattr(args, "format")
    assert hasattr(args, "json")


def _flag(parser, name: str):
    """The ``--format`` action as the *verb* parsers see it, since that is where it is declared."""
    import argparse

    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for child in action.choices.values():
                found = _flag(child, name)
                if found is not None:
                    return found
        if name in getattr(action, "option_strings", ()):
            return action
    return None


# --------------------------------------------------------------------- the precedence


@pytest.mark.parametrize(
    "argv",
    [
        ["note", "list", "--format", "human", "--json"],
        ["note", "list", "--json", "--format", "human"],
    ],
    ids=["--format first", "--json first"],
)
def test_format_wins_over_the_alias_in_either_order(capsys, answering, argv: list[str]) -> None:
    """The rule ADR 0005 states, in the case it exists for: both flags, disagreeing.

    Both orders, because argparse hands ``main`` a namespace rather than a sequence of events — the
    later flag does not "win" by being later, and an implementation that read them as a sequence
    would pass one of these two and fail the other.

    The mechanism is that ``--format``'s default is ``None``: with a default of ``"human"``, "the
    user typed ``--format human``" and "the user typed nothing" become the same value, and the alias
    would overrule the explicit flag it is an alias *for*.
    """
    answering(200, NOTES)

    assert main(argv) == 0
    assert capsys.readouterr().out == f"{LIST_ROWS}\n"


def test_the_alias_alone_selects_json(capsys, answering) -> None:
    answering(200, NOTES)

    assert main(["note", "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == LISTED


def test_the_alias_and_the_flag_produce_identical_bytes(capsys, answering) -> None:
    """"Alias" is a strong word. It means the same code path, not a similar one."""
    answering(200, NOTES)
    main(["note", "list", "--json"])
    aliased = capsys.readouterr().out

    answering(200, NOTES)
    main(["note", "list", "--format", "json"])

    assert capsys.readouterr().out == aliased


def test_format_wins_when_it_names_the_third_format(capsys, answering) -> None:
    """``--json`` is only an alias for one value, so a ``--format toon`` beside it must not be
    quietly downgraded to JSON by a resolver that checked the boolean first."""
    answering(200, NOTES)

    assert main(["note", "list", "--json", "--format", "toon"]) == 0
    assert capsys.readouterr().out.startswith(TOON_FIRST_LINE)


def test_no_flag_at_all_is_human(capsys, answering) -> None:
    """And byte-identical to the client's pin: ``--format`` omitted must not move one space."""
    answering(200, NOTES)
    main(["note", "list"])

    assert capsys.readouterr().out == f"{LIST_ROWS}\n"


@pytest.mark.parametrize("fmt", CLI_FORMATS)
def test_every_published_format_renders_both_shapes(capsys, answering, fmt: str) -> None:
    """A format that worked on a list and not on a single note would be found by a user, not us."""
    answering(200, NOTES)
    assert main(["note", "list", "--format", fmt]) == 0
    assert capsys.readouterr().out.strip()

    answering(200, GROCERIES)
    assert main(["note", "get", "NOTE-12", "--format", fmt]) == 0
    assert capsys.readouterr().out.strip()


# ------------------------------------------------------------------ a bad format value


@pytest.mark.parametrize("value", ["hunan", "yaml", "HUMAN", "data", "TOON", ""])
def test_an_unknown_format_value_is_a_usage_error(capsys, value: str) -> None:
    """SLICES §V2a, integration: "an unknown ``--format`` value is a usage error, exit `2`, in the
    structured shape". All three halves asserted together, because the way this breaks is one of
    them quietly taking the other's stream.

    ``data`` is in the list deliberately: it is a real key in ``_SERIALIZERS`` and must still be
    refused here, because argparse validates against ``CLI_FORMATS`` and not against the registry.
    """
    code = main(["note", "list", "--format", value])
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out.startswith("error\tusage\t")
    assert captured.out.endswith("\n")
    assert "usage: kaya note list" in captured.err
    assert "error\t" not in captured.err


def test_the_refusal_names_the_value_and_the_alternatives(capsys) -> None:
    """A row that said only "usage" would leave the caller with a code and no way to act on it.
    Argparse's own message lists the choices, which is the vocabulary the client publishes."""
    main(["note", "list", "--format", "hunan"])
    row = capsys.readouterr().out.rstrip("\n").split("\t")

    assert row[0] == "error"
    assert row[1] == "usage"
    assert "hunan" in row[2]
    assert "human" in row[2] and "json" in row[2] and "toon" in row[2]
    assert len(row) == 4


def test_a_bad_format_is_refused_before_any_request_is_made(fake_api) -> None:
    """argparse rejects it, so no session is opened and no token is even looked for. A CLI that
    validated the format after the call would make a bad flag cost a round trip — and, with no
    ``KAYA_TOKEN`` set, would report the *credential* as the problem."""

    def unreachable(request):  # pragma: no cover - the point is that it never runs
        raise AssertionError("a request was made for an invocation argparse should have refused")

    seen = fake_api(unreachable)

    assert main(["note", "list", "--format", "hunan"]) == 2
    assert seen == []


# ------------------------------------------------- the format reaches the failure path


def test_a_refusal_is_rendered_in_the_requested_format(capsys, answering) -> None:
    """ADR 0005 §contract 3's structured object, reached through the flag rather than through a
    ``report(fmt=…)`` call in a test. A consumer that asked for JSON and got a tab-separated row on
    the one line it most needed to parse would have to write a second parser for failures."""
    answering(404, {"error": {"code": "note_not_found", "message": "no such note"}})

    assert main(["note", "get", "NOTE-9999", "--format", "json"]) == 5
    assert json.loads(capsys.readouterr().out) == {
        "error": {"code": "note_not_found", "message": "no such note", "arg": ""}
    }


def test_a_refusal_renders_in_toon_too(capsys, answering) -> None:
    """The tripwire in `kaya-client`, seen from the user's end: a format that rendered a note list
    but not a `404` would fail exactly when the user most needs output."""
    answering(404, {"error": {"code": "note_not_found", "message": "no such note"}})

    assert main(["note", "get", "NOTE-9999", "--format", "toon"]) == 5
    assert capsys.readouterr().out == (
        "error:\n  code: note_not_found\n  message: no such note\n  arg: \"\"\n"
    )


def test_the_alias_reaches_the_failure_path_too(capsys, answering) -> None:
    answering(403, {"error": {"code": "note_forbidden", "message": "not yours"}})

    assert main(["note", "get", "NOTE-1", "--json"]) == 4
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "note_forbidden"


def test_a_usage_error_is_reported_in_human_whatever_came_after_it(capsys) -> None:
    """A parse that failed never produced a format to honour.

    `kaya note list --nope --format json` is one event, and argparse rejected it before ``--format``
    was resolved to anything. Reporting it as JSON would mean guessing at a flag from an argv the
    parser has already refused to interpret — and the row is still structured, on stdout, with the
    same four fields, so nothing is lost.
    """
    code = main(["note", "list", "--nope", "--format", "json"])
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out.startswith("error\tusage\t")
    assert captured.out.count("\t") == 3
