"""argparse, taught ADR 0005 §contract 3: usage text on stderr, the structured row on stdout.

### What argparse does by default, and why none of it is usable as-is

``ArgumentParser.error()`` prints usage to stderr and then calls ``self.exit(2, …)``, which calls
``sys.exit`` — the process is gone before a caller sees a return value, and nothing structured was
ever printed. ``--help`` takes the same door with status `0`. Both halves are wrong for this CLI:

- **The exit escapes.** ``main()`` returns an int so a test can assert on it and so every failure
  leaves through one place. A ``SystemExit`` raised from inside the parser bypasses that entirely,
  and the failure it reports is then the one path no test exercises.
- **Only half the contract is emitted.** ADR 0005 wants *both* — the human ``usage:`` block on
  stderr, because that is what a person at a shell needs, **and** the ``error<TAB>…`` row on stdout,
  because that is what a program reads. Neither substitutes for the other, and argparse writes only
  the first.

So ``StructuredParser`` intercepts both methods. Every exit from argparse becomes an exception and
``main`` decides what it means. The default path is not merely bypassed in normal use, it is
unreachable: overriding ``exit`` covers ``--help`` — and KAN-543's ``--version`` — as well as
``error``, so there is no argv that reaches ``sys.exit`` from inside the parser.

### Why usage stays on stderr

It is the right-hand column of ADR 0005's contract 3, and its reason is stdout's reason inverted: a
program parsing ``kaya``'s output must be able to read the whole of stdout as the answer. A
forty-line usage block interleaved with a machine row would make the row findable only by scanning,
and "scan stdout for a line starting with ``error``" is a rule that fails silently the first time a
note's title starts with the word.

### The output flags, and why resolving them is not shaping

``--format``, ``--json`` and ``--fields`` are declared here and resolved here. That is not a
violation of ADR 0004: what this module decides is which *name* the user asked for, and every byte
of what that name means lives in `kaya_client`. The vocabularies themselves are not written down in
this package — ``choices`` comes from ``CLI_FORMATS``, which is derived from the ``Format`` enum, so
a format published in the client is offered by the CLI without anybody editing an adapter, and an
adapter-only format (``data``) cannot be offered by accident.

``--fields`` is the same trade with a sharper edge, because projection is the concern ADR 0004 was
written about. So this module does exactly one thing with it: **split the comma-separated argv value
into a ``list[str]``**. Which names exist, what an unknown one costs, whether the verb can be
projected at all, and what the narrowed payload looks like are all decided in
`kaya_client.projection` — see `resolve_fields`. Pandan put projection in its CLI and its MCP
adapter inherited none of it; the one line below is the whole of kaya's version of that decision,
and if it ever grows a second line the review question is "why isn't this in the client?".
"""

import argparse
import sys
from typing import NoReturn

from kaya_client import CLI_FORMATS, Format, UsageError


class ParserExit(Exception):
    """argparse asked to end the process without a failure. ``--help`` is the whole of it today.

    Not a ``KayaError``: nothing went wrong, so there is no error object to render and no code to
    look up. ``main`` returns ``status`` and prints nothing further. A separate class rather than a
    `0` return down the failure path, because "argparse printed help" and "argparse rejected argv"
    are different events, and collapsing them would give the second one a way to exit `0`.
    """

    def __init__(self, status: int) -> None:
        super().__init__(f"the parser ended with status {status}")
        self.status = status


class StructuredParser(argparse.ArgumentParser):
    """An ``ArgumentParser`` that raises instead of exiting, and never swallows the usage text.

    Subparsers inherit it automatically: ``add_subparsers`` builds children from ``parser_class``,
    which defaults to the type of the parser it is called on. That matters more than it looks —
    KAN-541 adds ``kaya note list``, and a subparser that was a plain ``ArgumentParser`` would call
    ``sys.exit`` for ``kaya note lst`` while the top-level parser raised for ``kaya --nope``. One of
    those two paths would have a test and the other would not.
    """

    def error(self, message: str) -> NoReturn:
        """argv was rejected. Usage to stderr, then hand the message up for ``main`` to render.

        Deliberately not ``super().error(...)``, which would print and then exit. The two writes
        below reproduce argparse's stderr output verbatim — the usage block and the
        ``prog: error: message`` line — because that text is the contract with the *human* half of
        the audience, and paraphrasing it would make ``kaya``'s diagnostics differ from every other
        argparse tool on the machine in exchange for nothing.
        """
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise UsageError(message)

    def exit(self, status: int = 0, message: str | None = None) -> NoReturn:
        """Every other way argparse ends a process. ``--help`` today; ``--version`` with KAN-543.

        ``message`` is argparse's own and is only ever set on an abnormal end, so it goes to stderr.
        Help text is not routed through here at all: ``print_help`` has already written it to stdout
        by the time argparse calls ``exit``.
        """
        if message:
            print(message, end="", file=sys.stderr)
        raise ParserExit(status)


FORMAT_FLAG = "--format"
JSON_FLAG = "--json"
FIELDS_FLAG = "--fields"

FIELDS_SEPARATOR = ","
"""What ``--fields`` splits on. A comma, per ADR 0005 §contract 2's own spelling (``--fields
a,b,c``) and pandan's V42, so an operator's muscle memory carries between the two tools."""


def output_flags() -> argparse.ArgumentParser:
    """The ``--format``/``--json``/``--fields`` set, as a parent parser every verb inherits.

    A parent rather than a copy per subparser: ADR 0005 §contract 1 is a promise about *every* verb,
    and the way that promise breaks is one verb added later without the flags. Declaring them once
    means a verb cannot be added without them.

    ``--format`` defaults to ``None`` rather than to ``human`` on purpose — see `resolve_format`.

    **``--fields`` is inherited by `note get` too, and that is the design rather than an
    oversight.** ADR 0005 §contract 2 requires it to be "a usage error on single-entity verbs,
    **never a silent no-op**", and a flag argparse refuses to *accept* would be a usage error
    raised by the wrong layer: the CLI would answer for a rule about payload kinds, and V6's MCP
    server — which has no argparse — would be left to reimplement it. So the parser accepts it
    everywhere and `kaya_client.projection` refuses it where it does not apply, which is the one
    place both adapters inherit the refusal from.
    """
    flags = argparse.ArgumentParser(add_help=False)
    flags.add_argument(
        FORMAT_FLAG,
        choices=CLI_FORMATS,
        default=None,
        help=f"output format (default: {Format.HUMAN.value})",
    )
    flags.add_argument(
        JSON_FLAG,
        action="store_true",
        help=f"alias for `{FORMAT_FLAG} {Format.JSON.value}`; {FORMAT_FLAG} wins if both are given",
    )
    flags.add_argument(
        FIELDS_FLAG,
        default=None,
        metavar="a,b,c",
        help="select these columns, in this order, on a list verb (default: the standard row)",
    )
    return flags


def resolve_format(args: argparse.Namespace) -> str:
    """Which format the user asked for. ADR 0005 §contract 1's precedence, in one place.

    **``--format`` wins if both are given**, and that is why ``--format``'s default is ``None``: a
    default of ``"human"`` makes "the user typed ``--format human``" and "the user typed nothing"
    the same value, so ``kaya note list --format human --json`` would emit JSON — the alias
    overruling the explicit flag it is an alias *for*. The absent default is the whole mechanism,
    and `tests/test_output_flags.py` pins the case it exists for.

    Returns ``human`` for an invocation with no output flags at all, which includes every path that
    never reached a verb: a usage error is reported in the format nobody had a chance to choose.
    """
    chosen = getattr(args, "format", None)
    if chosen:
        return str(chosen)
    return Format.JSON if getattr(args, "json", False) else Format.HUMAN


def resolve_fields(args: argparse.Namespace) -> list[str] | None:
    """``--fields`` as the ``list[str]`` ``render`` takes, or ``None`` if it was not given.

    **One ``split`` and nothing else.** ADR 0004 leaves an adapter exactly one job — "how it gets
    its arguments" — and a comma-separated string is how argv carries a list. Every decision
    *about* the list is `kaya_client.projection`'s: which names exist (derived from the payload's
    own keys, so it cannot drift from the API), what an unknown one costs, and that it does not
    apply to `note get`. A validation added here would be a second opinion about a vocabulary this
    package cannot see, and it would be one V6's MCP server does not inherit.

    ``None`` and ``[]`` reach ``render`` as different values on purpose: ``None`` is "did not ask",
    which returns the payload untouched, and there is no argv that produces ``[]`` — splitting any
    string yields at least one segment, so ``--fields ""`` is one empty *name* and is refused as
    one. `kaya_client.projection` refuses a genuine ``[]`` too, for a caller reaching it in code.
    """
    given = getattr(args, "fields", None)
    if given is None:
        return None
    return str(given).split(FIELDS_SEPARATOR)
