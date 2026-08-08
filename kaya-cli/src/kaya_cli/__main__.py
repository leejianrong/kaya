"""The single entry point behind the `kaya` console script.

There is exactly one console script (Q39, ADR 0007 §4) and, for now, no verbs. `kaya note list` and
`kaya note get` land in KAN-541, because ADR 0005 sequences the output layer *before* the behaviour
that goes through it — adding verbs here first is precisely the retrofit that ordering exists to
avoid.

What this file does own is `--version`, which ADR 0007 puts in the *first* release rather than the
fifth: a CLI that cannot say which build it is makes every other guarantee unverifiable in the
field. Both of its forms are printed by ``kaya_client.version_line`` — the string is shaped in the
shared client so the MCP server reports provenance the same way in V6 (ADR 0004), and this module
supplies only the two things that are its own: the program name a user typed and this
distribution's version.

### The parser, and what the next two cards attach to it

`build_parser()` exists as a function returning a configured parser so KAN-541 can hang
``add_subparsers()`` off it and KAN-542 can replace the error path, neither of them restructuring
what is here. Two choices are load-bearing for that:

- **`--version` is a plain flag handled in `main`, not argparse's `action="version"`.** The built-in
  action prints and raises ``SystemExit`` from inside the parser, which would put an exit path
  outside the return value KAN-542's named-code table hangs off. Here every exit code is something
  ``main`` returns.
- **Argparse's own exits are funnelled back into that return value.** `--help` and a usage error
  both raise ``SystemExit`` from `parse_args`; catching it means `main` always answers with an int
  and there is exactly one place for KAN-542 to change when the code table lands.

Bare `kaya` still prints a banner saying which slice brings the verbs, now with the version line as
its first row, so provenance is one keystroke away even from a mistyped command.
"""

import argparse
import sys
from collections.abc import Sequence

from kaya_client import version_line

from kaya_cli import __version__

PROG = "kaya"

DESCRIPTION = "kaya — markdown notes, API-first."

EPILOGUE = (
    "No verbs yet: `note list` and `note get` arrive with the rest of the output layer in V2a.\n"
    "See docs/SLICES.md."
)


def version_string() -> str:
    """ADR 0007 §1's line for this build: `kaya X.Y.Z (sha)`, or the source-checkout form."""
    return version_line(PROG, __version__)


def build_parser() -> argparse.ArgumentParser:
    """The argument parser. A function, so KAN-541 adds subparsers without moving anything."""
    parser = argparse.ArgumentParser(
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
    """Run the CLI. Returns the process exit code; never calls ``sys.exit`` itself.

    Returning an int rather than exiting is what lets a test assert on the code without catching
    ``SystemExit``, and it is the single hook KAN-542's named-code table replaces.
    """
    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exit_request:
        # `--help` (code 0) and a usage error (argparse's 2) both arrive here. KAN-542 replaces
        # this branch with the named-code table; until then argparse's own numbers already agree
        # with SLICES §V2a, which puts an unknown flag at 2.
        return int(exit_request.code or 0)

    if args.version:
        print(version_string())
        return 0

    print(f"{version_string()}\n{EPILOGUE}")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via the console script
    sys.exit(main(sys.argv[1:]))
