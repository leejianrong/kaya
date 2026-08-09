"""``--full`` and ``KAYA_MAX_TEXT_CHARS`` from argv to stdout (KAN-547), and nothing more.

The same division `test_fields.py` draws. What truncation *is* — the allow-list, the cut, the true
total, the hint's wording, the multi-byte guarantee — is specified in `kaya-client`'s
`test_truncation.py`, and duplicating any of it here would be the beginning of this package having
an opinion about it. What is asserted *here* is the three things an adapter genuinely owns:

- **the flag reaches the seam**, so ``--full`` is ``text_limit=0`` end to end rather than in a unit
  test of a resolver nobody calls,
- **the precedence**, which is the only decision `resolve_text_limit` makes: the flag beats the
  environment,
- **a bad ``KAYA_MAX_TEXT_CHARS`` is ADR 0005's exit `2` on stdout**, because a refusal that came
  from configuration has to look like every other refusal to whatever is reading.

The last one is where the adapter's share is visible: the refusal is raised in
`kaya_client.config`, which has no parser and no stderr, so — exactly like ``--fields nope`` — the
structured row is the whole of the output and stderr stays empty.
"""

import json

import pytest
from conftest import GROCERIES, NOTES
from kaya_client import config
from kaya_client.truncation import hint

from kaya_cli.__main__ import build_parser, main
from kaya_cli.parsing import resolve_text_limit

LONG_BODY = "x" * 1200

LONG_NOTE = {**GROCERIES, "body": LONG_BODY}

DEFAULT_ROW = "NOTE-12  Groceries       home/groceries.md\nNOTE-3   A reading list\n\n2 notes"
"""Copied from `kaya-client/tests/test_human_row_is_pinned.py`, like `test_fields.py`'s. Truncation
must not move it: both bodies in that corpus are far under 500 characters."""


# -------------------------------------------------------------- the default, from a shell


def test_a_long_note_is_truncated_with_a_true_total(capsys, answering) -> None:
    """SLICES §V2b's demo line, as a person types it."""
    answering(200, LONG_NOTE)

    assert main(["note", "get", "NOTE-12"]) == 0
    out = capsys.readouterr().out

    assert out.rstrip("\n").endswith(hint(1200, "body"))
    assert "x" * 500 in out
    assert "x" * 501 not in out


def test_the_default_list_row_is_untouched(capsys, answering) -> None:
    """The pin, reached the way a user reaches it. Under-limit prose changes nothing at all, which
    is the property ADR 0005 says kept pandan's V45 to two rewritten assertions."""
    answering(200, NOTES)
    main(["note", "list"])

    assert capsys.readouterr().out == f"{DEFAULT_ROW}\n"


def test_a_short_note_gains_no_hint(capsys, answering) -> None:
    answering(200, GROCERIES)
    main(["note", "get", "NOTE-12"])

    assert "truncated" not in capsys.readouterr().out


# ------------------------------------------------------------------------------- --full


def test_full_prints_the_whole_body(capsys, answering) -> None:
    answering(200, LONG_NOTE)

    assert main(["note", "get", "NOTE-12", "--full"]) == 0
    out = capsys.readouterr().out

    assert LONG_BODY in out
    assert "truncated" not in out


def test_full_reaches_the_structured_formats_too(capsys, answering) -> None:
    """"Everywhere it applies" (SLICES §V2b). ``--full`` is a ``text_limit``, not a human-mode flag,
    so a JSON consumer opts out with the same word."""
    answering(200, LONG_NOTE)
    main(["note", "get", "NOTE-12", "--full", "--json"])

    assert json.loads(capsys.readouterr().out)["body"] == LONG_BODY


def test_the_hint_survives_into_json(capsys, answering) -> None:
    """The in-band decision, from a shell. Without it an agent on ``--format json`` could not tell a
    500-char note from a truncated 3,000-char one, and the true total would be a promise kept only
    to the audience that could have counted."""
    answering(200, LONG_NOTE)
    main(["note", "get", "NOTE-12", "--json"])

    body = json.loads(capsys.readouterr().out)["body"]
    assert body.endswith(hint(1200, "body"))
    assert isinstance(body, str)


@pytest.mark.parametrize("verb", [["note", "list"], ["note", "get", "NOTE-12"]])
def test_every_verb_carries_the_flag(verb: list[str]) -> None:
    """Declared once in `output_flags`, so a verb cannot be added without it — the same argument
    ADR 0005 §contract 1 makes for ``--format``."""
    assert hasattr(build_parser().parse_args(verb), "full")


# ------------------------------------------------------------------ KAYA_MAX_TEXT_CHARS


def test_the_environment_tightens_the_limit(capsys, answering, monkeypatch) -> None:
    monkeypatch.setenv(config.MAX_TEXT_CHARS_ENV, "50")
    answering(200, LONG_NOTE)
    main(["note", "get", "NOTE-12"])

    out = capsys.readouterr().out
    assert "x" * 50 in out
    assert "x" * 51 not in out
    assert hint(1200, "body") in out


def test_zero_in_the_environment_disables_truncation(capsys, answering, monkeypatch) -> None:
    """SLICES §V2b's integration line. The same state ``--full`` names, set once for a deployment
    instead of typed every time."""
    monkeypatch.setenv(config.MAX_TEXT_CHARS_ENV, "0")
    answering(200, LONG_NOTE)
    main(["note", "get", "NOTE-12"])

    assert LONG_BODY in capsys.readouterr().out


def test_the_flag_beats_the_environment(capsys, answering, monkeypatch) -> None:
    """The whole of `resolve_text_limit`'s decision, and the only one this package makes about a
    number. An explicit thing typed on this command line outranks a shell profile."""
    monkeypatch.setenv(config.MAX_TEXT_CHARS_ENV, "10")
    answering(200, LONG_NOTE)
    main(["note", "get", "NOTE-12", "--full"])

    assert LONG_BODY in capsys.readouterr().out


def test_a_bad_limit_is_exit_two_on_stdout_with_empty_stderr(capsys, answering, monkeypatch):
    """Four fields, the variable in ``arg``, and **nothing on stderr**.

    The refusal comes from `kaya_client.config`, which has no argparse — so unlike ``--format
    hunan`` there is no ``usage:`` block, and unlike a traceback there is something a program can
    read. A consumer parsing stdout cannot tell which layer refused, which is the point.
    """
    monkeypatch.setenv(config.MAX_TEXT_CHARS_ENV, "lots")
    answering(200, NOTES)

    code = main(["note", "list"])
    captured = capsys.readouterr()
    row = captured.out.rstrip("\n").split("\t")

    assert code == 2
    assert row[0] == "error"
    assert row[1] == "usage"
    assert len(row) == 4
    assert row[3] == config.MAX_TEXT_CHARS_ENV
    assert captured.err == ""


def test_a_bad_limit_is_refused_and_nothing_is_printed(answering, monkeypatch) -> None:
    """A misconfigured limit refuses the read rather than silently rendering it untruncated.

    **This test used to assert the refusal came before the request** — KAN-547 resolved the limit
    eagerly in `main`, so a bad value cost no round trip. KAN-551's review withdrew that: the eager
    call made *every* verb pay for a setting most of them never use, including `config path`, whose
    entire job is to answer the "which config file?" question that this very refusal asks the
    caller to go and fix. That was a lockout, so the limit is now resolved from the payload and
    only when there is prose to cut (see `main`).

    What survives is what the guarantee was actually for: the caller gets exit `2` and a row naming
    the variable, and never a rendering that quietly ignored their setting. What is given up is one
    read request against a misconfigured shell, which is the cheaper half by a wide margin.
    """
    monkeypatch.setenv(config.MAX_TEXT_CHARS_ENV, "-5")
    answering(200, NOTES)

    assert main(["note", "list"]) == 2


def test_a_verb_with_no_prose_never_resolves_the_limit(capsys, monkeypatch) -> None:
    """The other side of that trade, and the reason it is a payload fact rather than a verb list.

    `config path` renders no prose, so there is no limit for it to need — and it must answer
    whatever the configuration says, because it is the escape hatch from a configuration nobody can
    resolve. A verb added later inherits this by having an empty ``prose_fields``, not by being
    remembered.
    """
    monkeypatch.setenv(config.MAX_TEXT_CHARS_ENV, "lots")

    assert main(["config", "path"]) == 0
    assert "path" in capsys.readouterr().out


def test_a_bad_limit_does_not_stop_the_cli_identifying_itself(capsys, monkeypatch) -> None:
    """``--version`` is answered before anything reads the environment. A build that could not say
    which build it is because of an unrelated typo would make every other guarantee unverifiable at
    exactly the moment somebody is debugging."""
    monkeypatch.setenv(config.MAX_TEXT_CHARS_ENV, "lots")

    assert main(["--version"]) == 0
    assert capsys.readouterr().out.startswith("kaya ")


# ----------------------------------------------------------------------- the list path


def test_a_truncated_body_in_a_table_stays_one_row(capsys, answering, monkeypatch) -> None:
    """``--fields ref,body`` puts prose in a cell, which KAN-546 made reachable and this card had to
    meet. `serialization._cell` collapses the hint's blank line, so the grid holds."""
    monkeypatch.setenv(config.MAX_TEXT_CHARS_ENV, "5")
    answering(200, {"notes": [LONG_NOTE]})
    main(["note", "list", "--fields", "ref,body"])

    table, footer = capsys.readouterr().out.rstrip("\n").split("\n\n")
    assert table.splitlines() == [f"NOTE-12  xxxxx {hint(1200, 'body')}"]
    assert footer == "1 note"  # KAN-548's, and not this card's business beyond staying off the row


# ------------------------------------------------------------------ the resolver itself


def test_resolve_text_limit_is_a_precedence_and_nothing_more(monkeypatch) -> None:
    """The whole of this package's truncation logic, asserted so it stays that size.

    The default and the parse are `kaya_client.config.max_text_chars`'s, so V6's MCP server started
    from the same shell gets both without importing this module; ``0`` is `kaya_client.truncation`'s
    spelling of "do not truncate", so ``--full`` names a state rather than carrying a second one.
    """
    parser = build_parser()

    assert resolve_text_limit(parser.parse_args(["note", "list"])) == 500
    assert resolve_text_limit(parser.parse_args(["note", "list", "--full"])) == 0

    monkeypatch.setenv(config.MAX_TEXT_CHARS_ENV, "42")
    assert resolve_text_limit(parser.parse_args(["note", "list"])) == 42
    assert resolve_text_limit(parser.parse_args(["note", "list", "--full"])) == 0
