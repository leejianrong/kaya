"""The single entry point behind the `kaya` console script.

There is exactly one console script (Q39, ADR 0007 §4). Since KAN-551 it has nine verbs —
`note {list,get,create,edit,move,delete}` and `config {set,show,path}` — and the three formats ADR
0005 §contract 1 publishes. ADR 0005 sequences the output layer *before* the behaviour that goes
through it, and the whole of this file is what that sequencing bought: the verbs are a subparser and
a dispatch table, because the layer they print through was already finished when they arrived.
KAN-551 quadrupled the verb count and ``main`` below did not change at all.

`--version` (KAN-543) is here too, in the *first* release rather than the fifth: a CLI that cannot
say which build it is makes every other guarantee unverifiable in the field. Both of its forms are
printed by ``kaya_client.version_line``, so V6's MCP server reports provenance the same way.

### The shape of ``main``

    parser = build_parser()
    try:  parse → resolve the format → run the verb → print what `render` returned
    except ParserExit:  return its status      # --help
    except KayaError:   return report(..., fmt)  # every failure, one funnel

Three lines of that are load-bearing and each is load-bearing for a different reason:

- **The parse is inside the ``try``.** `parsing.StructuredParser` turns every argparse exit into an
  exception, so a bad flag and a `404` leave through the same funnel and get the same treatment:
  a structured row on stdout, the number from `failures.EXIT_FOR_CODE`.
- **The format is resolved after the parse and before the verb**, so a failure *from the verb* is
  reported in the format the user asked for. A failure from the parse is reported in ``human``,
  because argv never got far enough to name one.
- **``render`` is called here and nowhere else in this package.** `verbs.run` returns a ``Payload``
  and this line turns it into bytes. That is the entire ADR 0004 boundary, visible in one statement:
  if a second place in `kaya-cli` ever formats a payload, it will be a line added next to this one.
  ``--fields`` (KAN-546) and ``--full`` (KAN-547) arrive on that same line and **not** through
  `verbs.run`, which is the boundary doing its job: a verb that took a projection or a truncation
  argument would be a verb with an opinion about the payload's shape, and the client's steps already
  have the only ones there are. `verbs.py` has not changed for either card.

`--version` is a plain flag handled here rather than argparse's ``action="version"``: the built-in
prints and raises ``SystemExit`` from inside the parser, which would put an exit path outside the
return value the named-code table hangs off. ``main`` is the only thing in this package that decides
an exit code.

### Bare `kaya`

Still the banner, with the version line as its first row, so provenance is one keystroke away even
from a mistyped command. ADR 0005 §contract 7 replaces it with live state in V2b; the exit code is
`0` either way.
"""

import argparse
import sys
from collections.abc import Sequence

from kaya_client import Format, KayaError, render, version_line

from kaya_cli import __version__, verbs
from kaya_cli.failures import EXIT_OK, report
from kaya_cli.parsing import (
    API_URL_FLAG,
    BODY_FILE_FLAG,
    BODY_FLAG,
    PATH_FLAG,
    PRECONDITION_FLAG,
    TITLE_FLAG,
    TOKEN_FLAG,
    ParserExit,
    StructuredParser,
    output_flags,
    resolve_fields,
    resolve_format,
    resolve_text_limit,
)

PROG = "kaya"

DESCRIPTION = "kaya — markdown notes, API-first."

EPILOGUE = (
    "Notes: `note list`, `note get <ref>`, `note create <title>`, `note edit <ref>`,\n"
    "`note move <ref> <path>`, `note delete <ref>`. Configuration: `config show`, `config set`,\n"
    "`config path`. `--fields a,b,c` selects columns on a list, and prose is cut to\n"
    "KAYA_MAX_TEXT_CHARS (default 500) unless `--full`. A note is addressed as NOTE-12, note-12\n"
    "or 12, never by its path. See docs/SLICES.md."
)

NOTE_HELP = "create, read, change and delete the notes you own"

CONFIG_HELP = "read and write the local kaya configuration"

REF_HELP = "the note, as NOTE-12, note-12 or 12"


def version_string() -> str:
    """ADR 0007 §1's line for this build: `kaya X.Y.Z (sha)`, or the source-checkout form."""
    return version_line(PROG, __version__)


def build_parser() -> StructuredParser:
    """The argument parser, verbs and all.

    A ``StructuredParser`` rather than an ``ArgumentParser``: same configuration, but every exit
    argparse would take becomes an exception ``main`` can answer for, and a usage error emits both
    halves of ADR 0005 §contract 3 instead of only the stderr one. Subparsers inherit it through
    ``parser_class``, so `kaya note lst` fails exactly the way `kaya --nope` does — which is the
    reason `parsing` bothered to override ``exit`` as well as ``error``.

    ``note``'s subparsers are ``required=True`` so that bare `kaya note` is a usage error naming the
    words it accepts. The *top-level* set is not required, because bare `kaya` is a successful
    invocation that prints the banner (ADR 0005 §contract 7).
    """
    parser = StructuredParser(
        prog=PROG,
        description=DESCRIPTION,
        epilog=EPILOGUE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="print this build's version and the commit it was built from, then exit",
    )

    commands = parser.add_subparsers(dest="command")
    flags = output_flags()

    note = commands.add_parser(verbs.NOTE, help=NOTE_HELP, description=NOTE_HELP)
    _add_note_verbs(note.add_subparsers(dest="subcommand", required=True), flags)

    config = commands.add_parser(verbs.CONFIG, help=CONFIG_HELP, description=CONFIG_HELP)
    _add_config_verbs(config.add_subparsers(dest="subcommand", required=True), flags)

    return parser


def _add_note_verbs(note_commands, flags: argparse.ArgumentParser) -> None:
    """`note {list,get,create,edit,move,delete}`: one subparser each, all with the output flags.

    ``dest="subcommand"`` is shared with the `config` group so `verbs.run` dispatches on one pair
    of attributes rather than on a per-group name it would have to know in advance.

    **`move` is a separate word over the same request as `edit --path`** (ADR 0008: moving a note
    *is* a `PATCH` to one column). It earns the word because "move this note" is the sentence a
    person says and `edit --path` is the sentence a schema says, and because the alternative reading
    — that a move needs its own endpoint and link rewriting — is precisely the one ADR 0008 exists
    to refuse. What keeps the sugar honest is that `KayaClient.move_note` delegates to
    ``update_note`` rather than making its own call, so there is no second request shape for anybody
    to later "back properly" with a second route.
    """
    note_commands.add_parser(
        verbs.LIST,
        parents=[flags],
        help="list the notes you own, newest first",
        description="List the notes you own, newest first.",
    )

    get = note_commands.add_parser(
        verbs.GET,
        parents=[flags],
        help="read one note by NOTE-n, note-n or n",
        description="Read one note. The identifier is passed to the API untouched (ADR 0008).",
    )
    get.add_argument("ref", help=REF_HELP)

    create = note_commands.add_parser(
        verbs.CREATE,
        parents=[flags],
        help="create a note from a title, and optionally a body and a path",
        description="Create a note. The ref, the id and both timestamps are the database's.",
    )
    create.add_argument("title", help="the note's title; it is required and must not be empty")
    _add_body_flags(create)
    create.add_argument(PATH_FLAG, default=None, help="where the note filed, e.g. home/notes.md")

    edit = note_commands.add_parser(
        verbs.EDIT,
        parents=[flags],
        help="change a note's title, body and/or path",
        description="Change a note. Fields you do not name are left alone.",
    )
    edit.add_argument("ref", help=REF_HELP)
    edit.add_argument(TITLE_FLAG, default=None, help="a new title")
    _add_body_flags(edit)
    edit.add_argument(PATH_FLAG, default=None, help="a new path; the same write as `note move`")
    edit.add_argument(
        PRECONDITION_FLAG,
        default=None,
        metavar="TIMESTAMP",
        help=(
            "the updated_at you read, echoed back: the write is refused with a 409 if the note "
            "has changed since (ADR 0009). Omit it for a plain overwrite"
        ),
    )

    move = note_commands.add_parser(
        verbs.MOVE,
        parents=[flags],
        help="file a note at a new path",
        description="Move a note. One column, no link rewriting, no separate endpoint (ADR 0008).",
    )
    move.add_argument("ref", help=REF_HELP)
    move.add_argument("path", help="where to file it, e.g. archive/2026/groceries.md")

    delete = note_commands.add_parser(
        verbs.DELETE,
        parents=[flags],
        help="delete a note",
        description="Delete a note. The ref is never reused, so a later read is a 404 forever.",
    )
    delete.add_argument("ref", help=REF_HELP)


def _add_body_flags(verb: argparse.ArgumentParser) -> None:
    """``--body`` or ``--body-file``, never both.

    Two spellings because a note body is prose. Short bodies belong on the command line; anything
    with a blank line, a leading dash or a few paragraphs in it belongs in a file, and a CLI that
    offered only the first would push people into quoting heredocs. Mutually exclusive rather than
    "the last one wins", because two sources for one field is the sort of ambiguity that gets
    resolved differently by the person writing the script and the person reading it.

    There is no ``-`` for the standard input; `parsing.resolve_body` says why, and the shell's own
    ``/dev/stdin`` covers it without a line of code here.
    """
    body = verb.add_mutually_exclusive_group()
    body.add_argument(BODY_FLAG, default=None, help='the note body; "" clears it')
    body.add_argument(
        BODY_FILE_FLAG,
        default=None,
        metavar="PATH",
        help="read the note body from this file, decoded as UTF-8",
    )


def _add_config_verbs(config_commands, flags: argparse.ArgumentParser) -> None:
    """`config {set,show,path}` — the local configuration, and no session behind any of them.

    They carry the output flags like every other verb, because ADR 0005 §contract 1 is a promise
    about *every* verb and `config show --format json` is exactly what a provisioning script wants.

    ``set`` has flags for ``api_url`` and ``token`` and deliberately **none** for
    ``max_text_chars``: it is a preference a person tunes once by hand, and giving every key a flag
    is how a config file becomes a second CLI. That is also what makes this card's trap real — see
    `kaya_client.config.write_settings` for the merge that keeps a hand-set key alive.

    ``--token`` puts a credential in argv, which is visible in shell history and, briefly, to
    ``ps``. It is offered anyway because the alternative for someone who wants a persistent
    credential is hand-editing JSON, and a config file people edit by hand is a config file people
    corrupt. The file is written ``0o600``. ``KAYA_TOKEN`` remains the spelling that never touches
    the disk, and it wins over the file, so a shell that exports it is unaffected by whatever is
    stored.
    """
    setting = config_commands.add_parser(
        verbs.SET,
        parents=[flags],
        help="write settings to the config file, preserving the keys it does not name",
        description="Write settings to the config file. Existing keys are preserved.",
    )
    setting.add_argument(API_URL_FLAG, default=None, help="the kaya deployment to talk to")
    setting.add_argument(
        TOKEN_FLAG,
        default=None,
        help="a pandan personal access token; stored in a 0600 file and never printed back",
    )

    config_commands.add_parser(
        verbs.SHOW,
        parents=[flags],
        help="print the effective settings and where each came from (the token is redacted)",
        description="Print the effective settings. The token is reported as set/not set, never "
        "as a value or a fragment of one.",
    )

    config_commands.add_parser(
        verbs.PATH,
        parents=[flags],
        help="print the config file's path, whether or not it exists yet",
        description="Print the config file's path, and whether it exists.",
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Parse argv, do the thing, return the process exit code.

    Returns an int rather than calling ``sys.exit`` so the exit code is a value a test can assert
    on without catching ``SystemExit`` — and so ADR 0005's table has exactly one place it is read
    from. ``argv`` defaults to ``sys.argv[1:]`` at call time; passing ``[]`` and passing nothing are
    therefore different, which is what lets a test drive a bare invocation without touching the real
    argv.
    """
    parser = build_parser()
    argv = sys.argv[1:] if argv is None else argv
    fmt: str = Format.HUMAN

    try:
        args = parser.parse_args(list(argv))
        fmt = resolve_format(args)

        if args.version:
            print(version_string())
            return EXIT_OK

        if args.command is None:
            print(f"{version_string()}\n{EPILOGUE}")
            return EXIT_OK

        # Resolved before the verb runs, like `fmt` and unlike `fields`: this one reads the
        # environment, and a misconfigured `KAYA_MAX_TEXT_CHARS` should be exit `2` without having
        # spent a request first. `--version` and the banner above never reach it, so a bad value
        # cannot stop the CLI identifying itself.
        text_limit = resolve_text_limit(args)
        print(render(verbs.run(args), fields=resolve_fields(args), text_limit=text_limit, fmt=fmt))
        return EXIT_OK
    except ParserExit as ended:
        # `--help`, and nothing else today. Argparse has already printed; there is no failure to
        # report and no error object it would be honest to emit.
        return ended.status
    except KayaError as failure:
        return report(failure, fmt=fmt)


if __name__ == "__main__":  # pragma: no cover - exercised via the console script
    sys.exit(main(sys.argv[1:]))
