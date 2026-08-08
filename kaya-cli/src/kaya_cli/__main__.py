"""The single entry point behind the `kaya` console script.

There is exactly one console script (Q39, ADR 0007 §4). Since KAN-541 it has two verbs — `note list`
and `note get <ref>` — and the three formats ADR 0005 §contract 1 publishes. ADR 0005 sequences the
output layer *before* the behaviour that goes through it, and the whole of this file is what that
sequencing bought: the verbs are a subparser and a dispatch table, because the layer they print
through was already finished when they arrived.

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
from kaya_cli.parsing import ParserExit, StructuredParser, output_flags, resolve_format

PROG = "kaya"

DESCRIPTION = "kaya — markdown notes, API-first."

EPILOGUE = (
    "Reads only: `note list` and `note get`. The write verbs, `--fields` and truncation arrive in\n"
    "V2b. See docs/SLICES.md."
)

NOTE_HELP = "read the notes you own"


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
    note = commands.add_parser(verbs.NOTE, help=NOTE_HELP, description=NOTE_HELP)
    note_commands = note.add_subparsers(dest="note_command", required=True)

    flags = output_flags()
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
    get.add_argument("ref", help="the note, as NOTE-12, note-12 or 12")

    return parser


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

        print(render(verbs.run(args), fmt=fmt))
        return EXIT_OK
    except ParserExit as ended:
        # `--help`, and nothing else today. Argparse has already printed; there is no failure to
        # report and no error object it would be honest to emit.
        return ended.status
    except KayaError as failure:
        return report(failure, fmt=fmt)


if __name__ == "__main__":  # pragma: no cover - exercised via the console script
    sys.exit(main(sys.argv[1:]))
