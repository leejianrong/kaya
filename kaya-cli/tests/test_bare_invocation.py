"""ADR 0005 §contract 7: bare `kaya` prints live state and exits `0`; `--help` still prints usage.

SLICES §V2b's end-to-end line for this card is two sentences and this file is written against both:

    Bare `kaya` exits `0` and prints rows, not usage.
    With no token it prints the structured auth error.

Four things it guards that are not obvious from that line:

- **rows, not usage.** Argparse's default for a command with subparsers and no word is a usage
  error, and it is one edit away — ``required=True`` on the top-level subparsers, which is exactly
  what `note`'s subparsers *do* have. `test_bare_kaya_prints_rows_and_never_usage` is the regression
  this card exists to prevent, from both streams.
- **the aggregate describes the five rows shown, not the corpus.** A bare invocation is the one
  place in the tool where a payload is deliberately smaller than the answer, so it is where ADR 0005
  §contract 5's "the returned set, not the whole corpus" is testable end to end rather than as a
  property of `attach_summary`'s arity.
- **``render`` is still called exactly once in this package.** Bare `kaya` prints a banner *and* a
  payload, which is the first invocation in the tool that needed two blocks on stdout. The banner is
  `kaya_client.overview` and takes no ``Payload``, so it cannot be a second rendering; the AST
  assertion at the bottom is what keeps that from quietly becoming untrue.
- **the banner carries no fragment of a credential.** It is built from a program name, a version and
  a path, and the sweep is here because "print something useful about the session" is exactly the
  sort of banner that grows a "logged in as …" line later.

The `answering` fixture puts a real ``KayaClient`` over an ``httpx.MockTransport``, so every one of
these runs the shipped path from argv to stdout with no network and no PAT.
"""

import ast
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from conftest import GROCERIES, LIST_HELP, NOTES, TOKEN
from kaya_client import RECENT_NOTES, overview

import kaya_cli
from kaya_cli import verbs
from kaya_cli.__main__ import PROG, executable_path, main, version_string
from kaya_cli.failures import EXIT_OK, EXIT_RUNTIME

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "kaya_cli"

LIST_ROWS = (
    "NOTE-12  Groceries       home/groceries.md\nNOTE-3   A reading list\n\n2 notes\n\n" + LIST_HELP
)
"""`test_verbs.py`'s literal, which is `kaya-client`'s pin. A bare invocation of a two-note corpus
renders **exactly** what `note list` renders, because the only difference between them is a slice
that two notes do not reach — which is the cheapest available demonstration that the banner is a
block *beside* the render and not a change to it."""

SECRET = "kanban_pat_FAKE0000aaaaBBBBccccDDDDeeee"
"""`test_config_verbs.py`'s placeholder, copied for the same reason its own docstring gives: the
``FAKE…`` shape is `.gitleaks.toml`'s, and the tail carries no English word that could collide with
this payload's own vocabulary."""

CORPUS = {
    "notes": [
        {**GROCERIES, "ref": f"NOTE-{index}", "id": index, "title": f"Note {index}"}
        for index in range(1, 41)
    ]
}
"""Forty notes — the wall a bare invocation must not print. ``list_notes`` returns all of them
because `/api/v1/notes` has no ``?limit=`` (SLICES defers paging), so this is also what makes
"the summary counts the corpus" a *reachable* mistake rather than a hypothetical one."""


def banner() -> str:
    """What this process's own banner is, from the shipped function.

    Built rather than pinned as a literal, because two of its three lines are facts about *where the
    test is running* — the version, and the path of the interpreter pytest was started from. What is
    pinned byte-for-byte is its shape, in `test_the_banner_is_three_lines`, and its relationship to
    the payload below it, here.
    """
    return overview(PROG, kaya_cli.__version__, executable_path())


# ------------------------------------------------------------------- live state, and exit 0


def test_bare_kaya_prints_the_banner_then_the_notes_and_exits_zero(capsys, answering) -> None:
    """Contract 7 end to end: three lines about the tool, a blank line, then a rendered payload.

    The two halves are asserted as one string rather than separately, because the thing this card
    had to get right is the *join* — the banner is not part of the render and the render is not part
    of the banner, and they meet at exactly one ``BLOCK_GAP`` on one ``print``.
    """
    answering(200, NOTES)
    code = main([])

    assert code == EXIT_OK
    assert capsys.readouterr().out == f"{banner()}\n\n{LIST_ROWS}\n"


def test_bare_kaya_prints_rows_and_never_usage(capsys, answering) -> None:
    """**The regression this card exists to prevent.**

    Argparse's default for a parser with subparsers and no command word is a usage error, and one
    ``required=True`` on the top-level ``add_subparsers`` — the flag `note`'s own subparsers
    deliberately carry — turns bare `kaya` back into `2` and a usage block. Both streams are checked
    because the two halves of ADR 0005 §contract 3 would report it differently: argparse writes
    ``usage:`` to stderr and `failures.report` writes ``error<TAB>usage<TAB>`` to stdout.
    """
    answering(200, NOTES)
    code = main([])
    captured = capsys.readouterr()

    assert code == EXIT_OK
    assert "usage:" not in captured.out
    assert not captured.out.startswith("error\t")
    assert captured.err == ""
    assert "NOTE-12  Groceries" in captured.out


def test_bare_kaya_makes_exactly_one_request(answering) -> None:
    """One `GET /api/v1/notes`, like `note list`. `recent_notes` delegates to ``list_notes`` rather
    than making a second, differently-shaped call — there is no ``?limit=`` for it to make."""
    seen = answering(200, NOTES)
    main([])

    assert [(request.method, request.url.path) for request in seen] == [("GET", "/api/v1/notes")]


# --------------------------------------------------------------- the slice, and the aggregate


def test_only_the_most_recent_notes_are_printed(capsys, answering) -> None:
    """Forty notes in, ``RECENT_NOTES`` rows out — and they are the *first* ones the API returned.

    `GET /api/v1/notes` orders by ``updated_at DESC, id DESC``, so "recent" is the server's opinion.
    Asserting on which refs survive rather than only on how many is what would catch a slice taken
    from the wrong end, which reads identically in a row count.
    """
    answering(200, CORPUS)
    main([])
    rows = capsys.readouterr().out.split("\n\n")[1].splitlines()

    assert len(rows) == RECENT_NOTES
    assert [row.split()[0] for row in rows] == [f"NOTE-{index}" for index in range(1, 6)]


def test_the_aggregate_describes_the_rows_shown_and_not_the_corpus(capsys, answering) -> None:
    """ADR 0005 §contract 5, at the one place in the tool where the two numbers differ.

    Forty notes are fetched and five are shown, so a footer reading ``40 notes`` would be describing
    something the caller cannot see. `aggregates.attach_summary` is handed the sliced payload and
    counts what it was handed, which is why this needed no rule of its own — but it is worth an
    end-to-end assertion because the slice and the count are decided in two different modules.
    """
    answering(200, CORPUS)
    main([])
    out = capsys.readouterr().out

    assert out.split("\n\n")[2] == f"{RECENT_NOTES} notes"
    assert "40 notes" not in out


def test_the_banner_says_a_slice_happened(capsys, answering) -> None:
    """Otherwise ``5 notes`` under a table of five reads as "you have five notes".

    The sentence names the limit and the verb that lifts it, and it is **static** — it carries no
    count taken from the payload, which is what keeps `overview` unable to format a result.
    """
    answering(200, CORPUS)
    main([])
    third_line = capsys.readouterr().out.splitlines()[2]

    assert str(RECENT_NOTES) in third_line
    assert f"{PROG} note list" in third_line


def test_the_banner_is_three_lines_and_leads_with_the_version(capsys, answering) -> None:
    """Provenance stays one keystroke away from a mistyped command (ADR 0007), and the path is the
    line under it: "which build" and "which copy" are one diagnostic, and either alone is half."""
    answering(200, NOTES)
    main([])
    lines = capsys.readouterr().out.splitlines()

    assert lines[0] == version_string()
    assert lines[1] == f"{executable_path()} — markdown notes, API-first."
    assert lines[3] == ""


def test_the_executable_line_names_a_path_that_exists(capsys, answering) -> None:
    """The point of the line is "which copy of kaya is this?", which a relative name or a bare
    ``kaya`` does not answer. Resolved, absolute, and a real file — under pytest that file is the
    interpreter's entry script, which is the correct answer to the question asked."""
    answering(200, NOTES)
    main([])
    path = Path(capsys.readouterr().out.splitlines()[1].split(" — ")[0])

    assert path.is_absolute()
    assert path.exists()


def test_zero_notes_is_a_definitive_zero_state(capsys, answering) -> None:
    """``no notes`` plus the one next step that still makes sense, and exit `0`.

    Not an empty screen under a banner: an empty result is indistinguishable from a crashed pipe,
    and it is the state where a next step is worth the most. `hints.help_lines` drops
    ``note get <ref>`` because there is no row to address, which is a rule this card inherits rather
    than one it wrote.
    """
    answering(200, {"notes": []})
    code = main([])

    assert code == EXIT_OK
    assert capsys.readouterr().out == f"{banner()}\n\nno notes\n\nhelp: kaya note create <title>\n"


# ------------------------------------------------------------------------ the failure paths


def test_no_token_is_the_structured_row_on_stdout(capsys) -> None:
    """Contract 7's note: "no token → a structured auth error, not a stack trace".

    No ``answering`` fixture, so `verbs.run` resolves a credential that is not there. The banner is
    built before the request and printed after it, so stdout holds the row and **nothing else** — an
    agent reading it does not have to skip three lines of prose to find the answer.
    """
    code = main([])
    captured = capsys.readouterr()

    assert code == EXIT_RUNTIME
    assert captured.out.startswith("error\tno_credential\t")
    assert captured.out.rstrip("\n").split("\t")[3] == "KAYA_TOKEN"
    assert captured.err == ""


def test_no_token_is_a_structured_row_in_a_real_process() -> None:
    """The same thing where a traceback would actually be visible.

    ``main`` returning an ``int`` is what makes the in-process assertion above possible, and it is
    also what would hide an exception escaping a subprocess's ``sys.exit(main(...))``. So this runs
    the module and reads stderr, which is where a traceback goes and where nothing else may.
    """
    result = subprocess.run(
        [sys.executable, "-m", "kaya_cli"],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=30,
        check=False,
    )

    assert result.returncode == EXIT_RUNTIME
    assert result.stdout.startswith("error\tno_credential\t")
    assert result.stderr == ""
    assert "Traceback" not in result.stderr


def test_an_unreachable_deployment_is_a_structured_refusal(capsys, fake_api) -> None:
    """KAN-716's connect budget is what bounds this in the field — 5 s, not the 40 s read budget —
    so a bare `kaya` against a dead host answers rather than hanging. What is asserted here is the
    shape of the answer; the deadline itself is `kaya-client`'s constant and is guarded from the
    backend."""

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nothing is listening", request=request)

    fake_api(refused)
    code = main([])
    captured = capsys.readouterr()

    assert code == EXIT_RUNTIME
    assert captured.out.startswith("error\tunreachable\t")
    assert captured.err == ""


def test_an_api_refusal_keeps_its_own_exit_code(capsys, answering) -> None:
    """A bare invocation is a read like any other, so a `401` from it is ADR 0005's `3` and not the
    `1` a "banner command" might plausibly have been given for being decorative."""
    answering(401, {"error": {"code": "invalid_token", "message": "no"}})

    assert main([]) == 3
    assert capsys.readouterr().out.startswith("error\tinvalid_token\t")


# ------------------------------------------------------------------- --help and --version


def test_help_still_prints_usage_and_makes_no_request(capsys, answering) -> None:
    """The other half of contract 7. ``--help`` is a ``ParserExit``, which returns before anything
    opens a session, so the one command a confused user reaches for cannot fail on a credential."""
    seen = answering(200, NOTES)
    code = main(["--help"])
    out = capsys.readouterr().out

    assert code == EXIT_OK
    assert out.startswith("usage: kaya")
    assert "--version" in out
    assert seen == []


def test_the_epilogue_describes_the_bare_invocation(capsys) -> None:
    """`kaya --help` is where someone finds out what typing `kaya` alone does, and the epilogue is
    the only place that can say so — a usage block lists flags and words, not defaults."""
    main(["--help"])
    out = capsys.readouterr().out

    assert "Bare `kaya`" in out


def test_version_is_one_line_and_makes_no_request(capsys, answering) -> None:
    """ADR 0007 §1's two forms and no third. ``--version`` is handled before the dispatch, so it
    still answers on a machine with no configuration at all."""
    seen = answering(200, NOTES)
    code = main(["--version"])
    out = capsys.readouterr().out

    assert code == EXIT_OK
    assert out == f"{version_string()}\n"
    assert seen == []


def test_a_flag_with_no_verb_is_still_a_usage_error(capsys, answering) -> None:
    """Bare `kaya` takes no output flags, because the top-level parser has none — see
    `kaya_cli.__main__`'s docstring for why a banner and ``--format json`` do not compose. This is
    V2a's behaviour, unchanged, and it is here so that changing it is a deliberate act."""
    answering(200, NOTES)

    assert main(["--format", "json"]) == 2
    assert capsys.readouterr().out.startswith("error\tusage\t")


# -------------------------------------------------------------------------- the boundaries


def test_the_banner_carries_no_fragment_of_a_credential(capsys, monkeypatch, fake_api) -> None:
    """Q41/Q42 over the whole of a bare invocation's output.

    A banner is where a "logged in as …" line would go, and four characters of a live PAT is the
    exact shape `kaya_client.config` refuses for `config show`. The token here is the one the fake
    API is answering for, so the request genuinely carried it.
    """
    monkeypatch.setenv("KAYA_TOKEN", SECRET)
    fake_api(lambda request: httpx.Response(200, json=NOTES), token=SECRET)
    main([])
    out = capsys.readouterr().out

    leaked = sorted(
        {
            SECRET[start:stop]
            for start in range(len(SECRET))
            for stop in range(start + 4, len(SECRET) + 1)
        }
        & {out[start:stop] for start in range(len(out)) for stop in range(start + 4, len(out) + 1)}
    )
    assert leaked == []


def test_render_is_called_in_exactly_one_place_in_this_package() -> None:
    """ADR 0004's boundary, as a fact about the source rather than a sentence in a docstring.

    Bare `kaya` is the first invocation that puts two blocks on stdout, and the obvious way to build
    it is a second ``render`` call for the banner — which would put the "is this a list or an
    entity?" question in an adapter and start the drift ADR 0004 exists to prevent. The banner takes
    no ``Payload`` at all (`kaya_client.overview`), so this count stayed at one.
    """
    calls = [
        f"{path.name}:{node.lineno}"
        for path in sorted(PACKAGE.rglob("*.py"))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
        if isinstance(node.func, ast.Name) and node.func.id == "render"
    ]

    assert len(calls) == 1, calls
    assert calls[0].startswith("__main__.py:")


def test_the_bare_row_is_a_verb_like_any_other() -> None:
    """`verbs.BARE` is dispatched by the same table lookup as `note list`, so a bare invocation
    opens and closes its session through the same ``with`` and reports failures through the same
    funnel. A branch in ``run`` would be a second path with its own lifetime bug to find."""
    assert verbs.BARE in verbs.VERBS
    assert verbs.BARE not in verbs.LOCAL_VERBS


@pytest.mark.parametrize("argv", [[], ["note", "list"]])
def test_no_verb_formats_a_payload_of_its_own(argv: list[str], capsys, answering) -> None:
    """The two invocations that render the same payload differently must differ **only** by the
    banner. Anything else would mean this package had grown an opinion about the rows."""
    answering(200, NOTES)
    main(argv)
    out = capsys.readouterr().out

    assert out.endswith(f"{LIST_ROWS}\n")
    assert TOKEN not in out
