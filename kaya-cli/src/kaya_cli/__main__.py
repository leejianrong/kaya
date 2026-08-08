"""The single entry point behind the `kaya` console script.

There is exactly one console script (Q39, ADR 0007 §4) and, for now, no verbs. `kaya note list` and
`kaya note get` land in KAN-541, because ADR 0005 sequences the output layer *before* the behaviour
that goes through it — adding verbs here first is precisely the retrofit that ordering exists to
avoid.

What this file does own is `--version` (KAN-543), which ADR 0007 puts in the *first* release rather
than the fifth: a CLI that cannot say which build it is makes every other guarantee unverifiable in
the field. Both of its forms are printed by ``kaya_client.version_line`` — the string is shaped in
the shared client so the MCP server reports provenance the same way in V6 (ADR 0004), and this
module supplies only the two things that are its own: the program name a user typed and this
distribution's version.

### The failure funnel (KAN-542), and what KAN-543 left for it

543 wrote that "`build_parser()` exists as a function returning a configured parser so KAN-541 can
hang ``add_subparsers()`` off it and KAN-542 can replace the error path, neither of them
restructuring what is here". That is what happened, and the two load-bearing choices it named both
survived intact:

- **`--version` is a plain flag handled in `main`, not argparse's `action="version"`.** The built-in
  action prints and raises ``SystemExit`` from inside the parser, which would put an exit path
  outside the return value the named-code table hangs off. That reasoning is now stronger rather
  than weaker: `parsing.StructuredParser` makes *every* exit from argparse a raised exception, so
  ``main`` is the only thing in this package that decides an exit code.
- **Argparse's own exits are funnelled back into that return value.** 543 caught ``SystemExit`` and
  returned ``exit_request.code``; the two ``except`` clauses below replace that one. The difference
  is not the plumbing but what reaches the user: argparse's number is now looked up in
  `failures.EXIT_FOR_CODE` from a *named meaning*, and — the half argparse could never do — the
  structured row goes to stdout while the human ``usage:`` block stays on stderr.

### The shape of ``main``, and what a verb changes about it

    parser = build_parser()
    try:  parse
    except ParserExit:  return its status      # --help
    except KayaError:   return report(...)     # every failure, one funnel

A verb adds a subparser to ``build_parser`` and a call between the parse and the return. It does not
add an ``except``: `kaya_client.errors` gives every failure a common base and a ``code``, so the
funnel below already covers the `401`, the `403`, the `404` and the unreachable API that KAN-541's
verbs will be the first to actually produce. That is the point of building the layer first.

Bare `kaya` still prints the banner saying which slice brings the verbs, with the version line as
its first row, so provenance is one keystroke away even from a mistyped command.
"""

import argparse
import sys
from collections.abc import Sequence

from kaya_client import KayaError, version_line

from kaya_cli import __version__
from kaya_cli.failures import EXIT_OK, report
from kaya_cli.parsing import ParserExit, StructuredParser

PROG = "kaya"

DESCRIPTION = "kaya — markdown notes, API-first."

EPILOGUE = (
    "No verbs yet: `note list` and `note get` arrive with the rest of the output layer in V2a.\n"
    "See docs/SLICES.md."
)


def version_string() -> str:
    """ADR 0007 §1's line for this build: `kaya X.Y.Z (sha)`, or the source-checkout form."""
    return version_line(PROG, __version__)


def build_parser() -> StructuredParser:
    """The argument parser. A function, so KAN-541 adds subparsers without moving anything.

    A ``StructuredParser`` rather than an ``ArgumentParser``: same configuration, but every exit
    argparse would take becomes an exception ``main`` can answer for, and a usage error emits both
    halves of ADR 0005 §contract 3 instead of only the stderr one. Subparsers added here inherit it
    automatically through ``parser_class``, so KAN-541's ``kaya note lst`` fails the same way
    ``kaya --nope`` does.
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
    # KAN-541 attaches `parser.add_subparsers(dest="command")` here for `note list` / `note get`.
    # Until it does, any positional argument is an unrecognised one and argparse says so.
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

    try:
        args = parser.parse_args(list(argv))
    except ParserExit as ended:
        # `--help`, and nothing else today. Argparse has already printed; there is no failure to
        # report and no error object it would be honest to emit.
        return ended.status
    except KayaError as failure:
        return report(failure)

    if args.version:
        print(version_string())
        return EXIT_OK

    print(f"{version_string()}\n{EPILOGUE}")
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - exercised via the console script
    sys.exit(main(sys.argv[1:]))
