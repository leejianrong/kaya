"""``--fields`` from argv to stdout (KAN-546), and the line this package is not allowed to cross.

Everything asserted here is decided in `kaya_client.projection`. What is asserted *here* rather than
there is that argv reaches it intact and that its refusals come back out as ADR 0005's structured
row with ADR 0005's exit number — the two things an adapter genuinely owns. `kaya-client`'s
`test_projection.py` is where the vocabulary, the ordering and the entity refusal are specified;
duplicating those assertions in this package would be the beginning of this package having an
opinion about them.

The division shows up most clearly in the two usage errors below. `--format hunan` is refused by
argparse, so it prints `usage:` on stderr *and* the row on stdout; `--fields nope` is refused by the
client, so stderr stays empty and only the row appears. Same exit `2`, same four fields, different
layer — and a consumer reading stdout cannot tell, which is the point.
"""

import json

import pytest
from conftest import NOTES

from kaya_cli.__main__ import build_parser, main
from kaya_cli.parsing import resolve_fields

DEFAULT_ROW = "NOTE-12  Groceries       home/groceries.md\nNOTE-3   A reading list\n\n2 notes"
"""Copied from `kaya-client/tests/test_human_row_is_pinned.py`, like `test_verbs.py`'s. The two
literals disagreeing is how this package would find out it had grown a formatting rule.

The footer arrived with KAN-548 and belongs to the *client*. What "byte-identical" protects is that
omitting ``--fields`` leaves the row ``render`` produces alone — not that the row can never change
for any reason: KAN-546 and KAN-547 both landed without touching this literal, which was their
evidence, and ADR 0005 §contract 5 is what required this one to move."""


# ------------------------------------------------------------------ what it selects


def test_the_named_columns_reach_the_human_row(capsys, answering) -> None:
    answering(200, NOTES)

    assert main(["note", "list", "--fields", "ref,title"]) == 0
    assert capsys.readouterr().out == "NOTE-12  Groceries\nNOTE-3   A reading list\n\n2 notes\n"


def test_the_order_typed_is_the_order_printed(capsys, answering) -> None:
    """The permutation, end to end: ``split`` preserves order and nothing downstream re-sorts."""
    answering(200, NOTES)

    assert main(["note", "list", "--fields", "path,ref"]) == 0
    assert capsys.readouterr().out.splitlines()[0] == "home/groceries.md  NOTE-12"


def test_the_structured_output_narrows_too(capsys, answering) -> None:
    """ADR 0004's saving, reachable from a shell. ``--fields`` is one parameter through one seam, so
    what the CLI's table shows and what its JSON carries are the same selection."""
    answering(200, NOTES)

    assert main(["note", "list", "--fields", "ref,title", "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "notes": [
            {"ref": "NOTE-12", "title": "Groceries"},
            {"ref": "NOTE-3", "title": "A reading list"},
        ],
        "summary": {"count": 2},
    }


def test_omitting_it_leaves_the_default_row_byte_identical(capsys, answering) -> None:
    """SLICES §V2b's e2e line, and the half V2a's pin exists to protect.

    Stated here as well as in the client because this is the invocation a person actually types, and
    because the flag now exists on the parser — a default that leaked in through argparse rather
    than through ``render`` would show up here and nowhere else.
    """
    answering(200, NOTES)
    main(["note", "list"])

    assert capsys.readouterr().out == f"{DEFAULT_ROW}\n"


def test_projection_does_not_change_the_request(capsys, answering) -> None:
    """``--fields`` is an *adapter* concern (ADR 0004): the API stays the complete surface.

    A ``?fields=`` query parameter would be the shaping decision migrating into the API, which ADR
    0004 §Alternatives rejects by name — the SPA wants the whole record, and narrowing is the
    adapter's job.
    """
    seen = answering(200, NOTES)
    main(["note", "list", "--fields", "ref"])

    assert len(seen) == 1
    assert seen[0].url.path == "/api/v1/notes"
    assert seen[0].url.query == b""


# ----------------------------------------------------------------- what it refuses


def test_an_unknown_field_is_refused_by_the_client_not_the_parser(capsys, answering) -> None:
    """Exit `2`, on stdout, four fields, the name in ``arg`` — and **stderr empty**.

    The empty stderr is the load-bearing assertion. A `--format hunan` carries argparse's `usage:`
    block because argparse refused it; this refusal came from `kaya_client.projection`, which has no
    parser and no stderr, so the row on stdout is the whole of the output. A caller reading stdout
    gets the same four fields either way, which is what makes ADR 0005 §contract 3 a contract rather
    than a description of one code path.

    Note that a request *has* been made by the time this is refused: the payload is what carries the
    vocabulary. That is the cost of a vocabulary that cannot drift from the API, and it is the right
    trade — a list of field names maintained in this package would be free to check and wrong one
    deploy later.
    """
    answering(200, NOTES)

    code = main(["note", "list", "--fields", "nope"])
    captured = capsys.readouterr()
    row = captured.out.rstrip("\n").split("\t")

    assert code == 2
    assert row[0] == "error"
    assert row[1] == "usage"
    assert "nope" in row[2]
    assert row[3] == "nope"
    assert len(row) == 4
    assert captured.err == ""


def test_the_refusal_lists_the_vocabulary_the_api_returned(capsys, answering) -> None:
    """``id`` is in the message and in no default row, which is the vocabulary being the payload's
    own keys rather than a list this package could have written down."""
    answering(200, NOTES)
    main(["note", "list", "--fields", "nope"])

    assert "ref, id, title, body, path, created_at, updated_at" in capsys.readouterr().out


def test_fields_on_a_single_entity_verb_is_a_usage_error(capsys, answering) -> None:
    """ADR 0005 §contract 2 and SLICES §V2b's integration line: "not a silent no-op".

    `note get` inherits the flag from `parsing.output_flags`, so argparse accepts it and the client
    refuses it — see that function's docstring for why the refusal is not moved into the parser.
    """
    answering(200, NOTES["notes"][0])

    code = main(["note", "get", "12", "--fields", "ref"])
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out.startswith("error\tusage\t")
    assert captured.out.count("\t") == 3
    assert captured.err == ""


def test_an_empty_value_is_one_empty_field_name(capsys, answering) -> None:
    """``--fields ""``. The adapter splits and does not filter, so this is a vocabulary error.

    Not a no-op and not "the default row": a caller who typed an empty value made a mistake, and a
    CLI that quietly rendered the default row would hide it until they wondered why their projection
    had no effect.
    """
    answering(200, NOTES)

    assert main(["note", "list", "--fields", ""]) == 2
    assert "unknown field ''" in capsys.readouterr().out


def test_the_refusal_honours_the_requested_format(capsys, answering) -> None:
    """A projection failure is a failure like any other, so it renders through the same layer."""
    answering(200, NOTES)

    assert main(["note", "list", "--fields", "nope", "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["arg"] == "nope"


# ------------------------------------------------------------------- the flag itself


@pytest.mark.parametrize("verb", [["note", "list"], ["note", "get", "NOTE-12"]])
def test_every_verb_carries_the_flag(verb: list[str]) -> None:
    """Declared once in `output_flags`, so a verb cannot be added without it — the same argument
    ADR 0005 §contract 1 makes for ``--format``, and the reason `note get` can refuse it in the
    client rather than by not having it."""
    assert hasattr(build_parser().parse_args(verb), "fields")


def test_resolve_fields_is_a_split_and_nothing_more() -> None:
    """The whole of this package's projection logic, asserted so it stays that size.

    ``None`` when absent, so ``render`` can tell "did not ask" from "asked for something"; a plain
    ``split`` otherwise, with no stripping, no de-duplication and no validation — every one of which
    would be a decision the MCP adapter does not inherit (ADR 0004).

    The unstripped last case is deliberate rather than tolerated. ``--fields ' ref ,title'`` is
    refused by the client as ``unknown field ' ref '``, quotes and all, which shows the caller the
    spaces they typed. A ``strip()`` here would accept it silently and be a rule about field-name
    syntax living in an adapter — and the day the API grows a name this package guessed wrong about,
    it is a rule that has to be un-guessed in two places.
    """
    parser = build_parser()

    assert resolve_fields(parser.parse_args(["note", "list"])) is None
    assert resolve_fields(parser.parse_args(["note", "list", "--fields", "ref"])) == ["ref"]
    assert resolve_fields(parser.parse_args(["note", "list", "--fields", "ref,title"])) == [
        "ref",
        "title",
    ]
    assert resolve_fields(parser.parse_args(["note", "list", "--fields", " ref ,title"])) == [
        " ref ",
        "title",
    ]
