"""The single entry point behind the `kaya` console script.

There is exactly one console script (Q39, ADR 0007 §4). Since KAN-551 it has nine verbs —
`note {list,get,create,edit,move,delete}` and `config {set,show,path}` — and the three formats ADR
0005 §contract 1 publishes. ADR 0005 sequences the output layer *before* the behaviour that goes
through it, and the whole of this file is what that sequencing bought: the verbs are a subparser and
a dispatch table, because the layer they print through was already finished when they arrived.
KAN-551 quadrupled the verb count; ``main`` below gained one conditional, and only after a
review found the eager one was a lockout (the comment there has it).

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
  have the only ones there are. `verbs.py` has not changed for either card. KAN-551 split the
  ``verbs.run(args)`` call out of that statement onto its own line so the payload can be inspected
  before it is rendered — see the comment there — but ``render`` is still called exactly once.

`--version` is a plain flag handled here rather than argparse's ``action="version"``: the built-in
prints and raises ``SystemExit`` from inside the parser, which would put an exit path outside the
return value the named-code table hangs off. ``main`` is the only thing in this package that decides
an exit code.

### Bare `kaya`

**Live state since KAN-549**, which is ADR 0005 §contract 7 arriving: three banner lines, the
caller's five most recently updated notes, the aggregate over *those five*, and the `help:`
templates. Exit `0`. With no token it is the structured `no_credential` row on stdout and exit `1` —
the same funnel every other failure takes, which is why there is no traceback to prevent.

Three things about it are decisions rather than layout:

- **It is a verb** (`verbs.BARE`), dispatched by the same table lookup as `note list`. So it opens
  its session, closes it, reports its failures and renders its payload through the code every other
  verb already uses, and this file gained no second path for it.
- **The banner is not a payload and does not go through ``render``.** `kaya_client.overview` takes
  three strings — program, version, executable path — and no ``Payload``, so it *cannot* format a
  result. That is what keeps "``render`` is called here and nowhere else" true with a banner on
  screen: the two are joined by ``BLOCK_GAP`` on the print below, not by a second rendering. The
  same door ``version_string`` already takes, for the reason `kaya_client.provenance` gives.
- **A bare invocation has no output flags**, because the top-level parser has none — ``--format``,
  ``--fields`` and ``--full`` live on the verbs. `kaya --format json` is a usage error, unchanged
  from V2a, and the alternative is worse than it looks: a banner is prose and would have to be
  either invalid JSON in front of a document or a key inside one, and `kaya note list --format json`
  already answers the question that reaches for. So the banner is `human`'s alone by construction
  rather than by a suppression rule, which is the same shape `hints` has for `help:` lines.
"""

import argparse
import os
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

from kaya_client import BLOCK_GAP, Format, KayaError, overview, render, version_line
from kaya_client import DESCRIPTION as PRODUCT

from kaya_cli import __version__, verbs
from kaya_cli.failures import EXIT_OK, report
from kaya_cli.parsing import (
    API_URL_FLAG,
    BODY_FILE_FLAG,
    BODY_FLAG,
    NO_TEXT_LIMIT,
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

DESCRIPTION = f"{PROG} — {PRODUCT}."
"""argparse's header, built from `kaya_client.overview.DESCRIPTION` rather than written again.

The banner's second line and this one are then the same sentence by construction. Two copies would
drift the first time one of them was improved, and which one a user meets depends on whether they
typed a command — the worst way for a product description to be inconsistent."""

EPILOGUE = (
    "Bare `kaya` prints this build, where it is installed, and your five most recently updated\n"
    "notes. Notes: `note list`, `note get <ref>`, `note create <title>`, `note edit <ref>`,\n"
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


def executable_path() -> str:
    """**Which** `kaya` is running — the second line of KAN-549's banner.

    ADR 0007's whole point is that a build must be able to say what it is, and a sha answers half of
    that question. The other half is *where the thing that printed it lives*, because the failure
    ADR 0007 exists for — "a stale binary became indistinguishable from current source" — is a
    failure about which copy is on the ``PATH``. Printed next to the version line the two are one
    diagnostic; printed alone, either is half of one.

    So this is **the path of the program**, not of the interpreter, and the three environments it
    has to answer in disagree about what that means:

    - **A frozen release asset** (PyInstaller, KAN-544). ``sys.executable`` *is* `kaya`, because the
      bootloader is the interpreter, and ``sys.argv[0]`` may be a relative name the user typed. So
      ``sys.frozen`` is checked first and ``sys.executable`` wins.
    - **An installed console script** (`uv tool install`, a venv). ``sys.executable`` is
      ``…/bin/python``, which is the wrong answer — it names the interpreter every Python program on
      the machine shares. ``sys.argv[0]`` is the script, and it is a bare ``kaya`` when the shell
      found it on the ``PATH``, so `shutil.which` recovers the directory that ``PATH`` actually
      resolved to. That is the useful fact: "you have two kayas installed" is precisely the
      confusion this line settles.
    - **A source checkout** (``python -m kaya_cli``, ``uv run``). ``sys.argv[0]`` is the
      ``__main__.py`` inside the checkout, which is again the right answer — it names the tree, and
      the version line above it already says "source checkout, not a released build".

    Symlinks are resolved, because the question is which file runs and not which name was typed. The
    README documents a symlink as the supported way to have a short alias (ADR 0007 §4 allows
    exactly one console script), so an unresolved answer would name the alias and hide the target.

    It is here rather than in `kaya_client` because only an adapter has an ``argv`` — the same split
    `kaya_client.provenance` makes, where the client owns the *line* and the caller supplies the
    facts. A resolution that fails at any step degrades to the program name rather than raising: a
    banner is a diagnostic, and one that crashes while identifying itself is worse than a vague one.
    """
    if getattr(sys, "frozen", False):  # pragma: no cover - only true inside a PyInstaller build
        return _resolved(sys.executable)

    invoked = sys.argv[0] if sys.argv else ""
    if invoked and os.sep not in invoked:
        invoked = shutil.which(invoked) or invoked
    return _resolved(invoked) if invoked else PROG


def _resolved(path: str) -> str:
    """``path`` absolute and symlink-free, or exactly what was passed if it cannot be resolved."""
    try:
        return str(Path(path).resolve())
    except OSError:  # pragma: no cover - a path the filesystem refuses to answer about
        return path


def build_parser() -> StructuredParser:
    """The argument parser, verbs and all.

    A ``StructuredParser`` rather than an ``ArgumentParser``: same configuration, but every exit
    argparse would take becomes an exception ``main`` can answer for, and a usage error emits both
    halves of ADR 0005 §contract 3 instead of only the stderr one. Subparsers inherit it through
    ``parser_class``, so `kaya note lst` fails exactly the way `kaya --nope` does — which is the
    reason `parsing` bothered to override ``exit`` as well as ``error``.

    ``note``'s subparsers are ``required=True`` so that bare `kaya note` is a usage error naming the
    words it accepts. The *top-level* set is not required, because bare `kaya` is a successful
    invocation that prints live state (ADR 0005 §contract 7).

    ``set_defaults`` is what lets that be a table row rather than a branch. Argparse leaves
    ``subcommand`` off the namespace entirely when no command word was given, so `verbs.run` would
    raise ``AttributeError`` — a traceback where a structured result belongs — on the one invocation
    most likely to be somebody's first. Two explicit ``None``s make the bare case dispatch to
    ``verbs.BARE`` through the same lookup as everything else.
    """
    parser = StructuredParser(
        prog=PROG,
        description=DESCRIPTION,
        epilog=EPILOGUE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.set_defaults(command=None, subcommand=None)
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

        # KAN-549's banner, built **before** the request and printed **after** it — the only two
        # things about these two lines that matter.
        #
        # Before, because `overview` needs nothing from the payload and a banner assembled beside
        # the render would read as though it might. After, because the print below is the only
        # statement that writes to stdout on the success path: a banner emitted eagerly would still
        # be on stdout when `verbs.run` raised, so `kaya` with no token would put three lines of
        # prose above `failures.report`'s structured row, and an agent reading stdout would have to
        # skip them to find the answer. ADR 0005 §contract 7's "a structured auth error, not a stack
        # trace" is about what the caller can *parse*, and prose in front of the row is the same
        # defect in a politer form.
        #
        # A tuple rather than a string, so the empty case contributes nothing at all to the `print`
        # below instead of an empty block the separator would still be applied to.
        bare = args.command is None
        banner = (overview(PROG, __version__, executable_path()),) if bare else ()

        # Resolved from the payload, **after** the verb, and only when there is prose to cut. It
        # was eager here until KAN-551's review, and the bug that caused is worth writing down
        # because it is the kind a reviewer meets and an author does not.
        #
        # A `max_text_chars` the resolver cannot parse is exit `2` with a message telling the
        # caller to fix "the config file" — and an eager call made *every* verb pay for it,
        # including `config path`, whose entire job is to answer "which config file?". The user was
        # locked out of their own configuration by a message naming a thing only the refused verb
        # could have found. Under KAN-547's environment-only tier it was unreachable, because the
        # bad value was in the caller's own shell where they could already see it; the file tier is
        # what turned it into a trap.
        #
        # The guard is a fact about the payload rather than a list of verb names, so a verb added
        # later inherits it. `prose_fields` is empty for exactly the payloads truncation would
        # leave alone — `truncate` returns those untouched at any limit — which is why
        # `NO_TEXT_LIMIT` here is not a behaviour choice: there is nothing for the number to do.
        #
        # What this gives up is the old comment's "without having spent a request first": a
        # `note list` against a bad limit now makes its request before refusing. That was the
        # weaker half of the trade — the refusal is identical and the request is a read — and it
        # bought nothing at all for the verbs that never truncate.
        payload = verbs.run(args)
        text_limit = resolve_text_limit(args) if payload.prose_fields else NO_TEXT_LIMIT
        rendered = render(payload, fields=resolve_fields(args), text_limit=text_limit, fmt=fmt)
        # `render` is still called exactly once in this package, with `banner` empty for every verb
        # — `tests/test_bare_invocation.py` asserts the count over this file's AST. `BLOCK_GAP` is
        # `kaya_client`'s own separator, imported rather than spelled `"\n\n"` here, because how far
        # apart two blocks of a human render sit is a formatting decision and this package does not
        # make those.
        print(*banner, rendered, sep=BLOCK_GAP)
        return EXIT_OK
    except ParserExit as ended:
        # `--help`, and nothing else today. Argparse has already printed; there is no failure to
        # report and no error object it would be honest to emit.
        return ended.status
    except KayaError as failure:
        return report(failure, fmt=fmt)


if __name__ == "__main__":  # pragma: no cover - exercised via the console script
    sys.exit(main(sys.argv[1:]))
