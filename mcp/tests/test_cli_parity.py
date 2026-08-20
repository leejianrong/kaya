"""`MCP ⊆ CLI`, asserted rather than inspected (KAN-570, ADR 0006 §4 rule 2).

ADR 0006 §4 states the direction once — in `mcp/README.md`, and every other document links there
rather than restating it — and requires a test behind it: *"For every frozen tool name, a
corresponding CLI verb must exist. A new MCP tool without a CLI verb fails CI."* This file is that
test. Until it landed, the direction was true by inspection, and the README said so in those words;
inspection is what pandan had too, right up until its packaged skill claimed tool-for-tool coverage
in bold while a `curl` workaround for a missing CLI verb sat forty lines below the claim, and that
false claim reached a roadmap card where it nearly justified deleting a working MCP surface
(ADR 0006 §Context, finding 2).

### The mapping is data, and the mapping is the thing that needs guarding

The obvious implementation of "every frozen tool name has a CLI verb" derives the verb from the
tool name, and it is wrong on the sixth tool. `search_notes`' CLI spelling is `kaya note list --q
TERM`: there is no `kaya search_notes` and there never will be, because `GET /api/v1/notes?q=`
answers with the very same `NoteList` a plain list does (KAN-558/559), so the CLI needed a flag
where MCP needed a name. A name-derived parity test passes for five tools and then needs a
hand-written exception for the sixth — and an exception hand-written into a parity test is the
parity test not holding. `mcp/README.md`'s table footnote called this out before this card started.

So `CLI_EQUIVALENT` below is a hand-written table. That makes *it* the weak point, which is what
most of this file is about: a row naming a CLI verb that does not exist must fail, a tool with no
row at all must fail, and a **renamed CLI verb** must fail here even though nothing in `mcp/`
changed. All three are checked against `kaya-cli`'s own source, never against a second list of verb
names written down over here — two hand-typed lists agreeing with each other prove nothing except
that one person typed both.

### Why the CLI is read as an AST rather than imported

ADR 0004 points the dependency arrow at `kaya-client`: both adapters depend on it and neither
depends on the other. `mcp/pyproject.toml` says so on the line that declares its one path source,
and `tests/conftest.py` gives the operational half of the same reason — the two adapter packages
are separately installable, so a suite that reached into a sibling would break the day one of them
ships alone. Adding `kaya-notes` as a dev dependency of `mcp` to run one parser would draw a new
arrow between two adapters for the convenience of a test.

The established answer in this repository is to read the other package's **source** instead:
`backend/tests/unit/test_client_deadline_outlasts_auth.py` reads `kaya-client`'s deadline out of its
AST for exactly this reason, `test_error_extras_stay_addressable.py` does the same in the other
direction, and both explain that a *text* scan would match their own docstrings. Same technique
here, and the same hazard: an AST reader that quietly finds nothing turns every assertion below
into a pass. That is what `test_the_readers_found_the_cli_that_is_actually_there` and
`test_the_readers_are_not_fooled_by_...` are for, and they are not decoration — they are the only
thing standing between this file and a green test that checks nothing.

### Two readers, cross-checked against each other

Neither reader is asked to understand argparse. Each one reads a different file for a different
fact, and the two are then made to agree, which is the strongest control available without an
import:

- `dispatch_words()` reads `verbs.py`'s two dispatch tables and returns `{(command, subcommand)}`.
  Those tables are what `verbs.run` dispatches on, and `kaya-cli/tests/test_verbs.py`'s
  `test_every_parser_word_has_a_verb_and_every_verb_has_a_parser_word` already pins them against
  the parser — so reading the tables is reading the parser's vocabulary, with the CLI's own suite
  as the link between the two.
- `declared_flags()` reads `__main__.py`'s parser construction and returns `{word: {flags}}`. The
  flag half cannot come from `verbs.py` at all: `--q` is a parser fact, added to the `note list`
  subparser alone (KAN-559 deliberately kept it off `output_flags()`, since it names a request
  parameter rather than an output-shaping flag).

`test_the_two_readers_agree_about_which_words_exist` then asserts that the words one reader found
in the dispatch tables are exactly the words the other found in the parser. A reader that goes
blind — because a constant moved, a helper was renamed, or argparse is now called some other way —
disagrees with the other one and reddens, rather than silently agreeing that there is nothing to
check.

### What a row is, and what it deliberately is not

A row names the argv tokens that reach **the same capability** the tool does: the verb word (or
group and word), plus any flag without which the verb is a different capability. `--q` is in
`search_notes`' row for that reason.

Output-shaping flags are **not** part of a row. `--fields`, `--full` and `--format` are ADR 0004's
one parameter through one seam — `fields` on the MCP side is the same parameter as `--fields` on the
CLI side, `output_flags()` puts all three on every verb by construction, and ADR 0005 §contract 1 is
already a promise about every verb with `kaya-cli/tests/test_output_flags.py` behind it. Naming them
here would be this package re-asserting a shaping contract it is forbidden from holding an opinion
about. No row needs a `--format` today either; if one ever does, `declared_flags()` already finds
the shared flags through `parents=[flags]`, and `test_the_readers_found_the_cli_that_is_actually_
there` is the assertion that proves it does.
"""

import ast
from collections.abc import Mapping
from pathlib import Path

from kaya_mcp import TOOL_NAMES

REPO_ROOT = Path(__file__).resolve().parents[2]
"""`mcp/tests/<this file>`, so `parents[2]` is the repository root."""

CLI_PACKAGE = REPO_ROOT / "kaya-cli" / "src" / "kaya_cli"
VERBS_SOURCE = CLI_PACKAGE / "verbs.py"
PARSER_SOURCE = CLI_PACKAGE / "__main__.py"
PARSING_SOURCE = CLI_PACKAGE / "parsing.py"
"""The three files that between them say what a `kaya` invocation may look like: the dispatch
tables, the parser that accepts the words, and the flag-name constants both of them spell."""

DISPATCH_TABLES = ("VERBS", "LOCAL_VERBS")
"""`kaya_cli.verbs`' two tables. Two rather than one because `config show` has to answer with no
credential at all, so the local verbs are dispatched without a session — see that module's
docstring. A parity row may name a word from either: "there is a CLI verb behind this tool" is a
claim about the CLI's vocabulary, not about which of the two tables happens to hold it."""

SHARED_FLAGS_VAR = "flags"
SHARED_FLAGS_FACTORY = "output_flags"
"""`flags = output_flags()` in `build_parser`, handed to every subparser as `parents=[flags]` and
passed under the same name into the two group helpers. Read rather than assumed: the reader below
only treats `parents=[flags]` as the shared output flags because
`test_the_shared_parent_parser_is_the_one_this_reader_thinks_it_is` has confirmed that `flags` is
what `output_flags()` was assigned to."""


# --------------------------------------------------------------------------- the mapping

CLI_EQUIVALENT: Mapping[str, tuple[str, ...]] = {
    "list_notes": ("note", "list"),
    "get_note": ("note", "get"),
    "create_note": ("note", "create"),
    "edit_note": ("note", "edit"),
    "search_notes": ("note", "list", "--q"),
    "get_backlinks": ("backlinks",),
}
"""Each frozen tool, and the argv that reaches the same capability from a shell.

Words first, then flags — the same order a person types. One word is a top-level verb (`backlinks`,
KAN-566, which is top level rather than `note backlinks` for the reason `_add_link_verbs`'
docstring gives); two words are a group and a verb.

Five rows are a verb word and nothing else. The sixth is the one that matters:

    search_notes  →  kaya note list --q TERM

`KayaClient.list_notes(q)` is the one call behind both `list_notes` and `search_notes`, because the
API returns the same `NoteList` either way — so on the CLI side the difference is a flag, and
`--q` has to be *in* the row. Without it this row would be byte-identical to `list_notes`', and
deleting `--q` from the CLI would leave the tool with no CLI spelling and this test still green.
`get_backlinks` was the other row worth checking rather than trusting, and KAN-964 is why it is
honest: until that card landed the tool refused every call, so a parity test written a day earlier
would have pinned a set with one broken member.
"""


# ------------------------------------------------------------- reading the CLI's source


def _string_constants(tree: ast.Module) -> dict[str, str]:
    """Every module-level ``NAME = "literal"``.

    Deliberately narrow, the same way `test_client_deadline_outlasts_auth.py`'s `float_constants`
    is: only a bare assignment of a string literal at module scope counts. A constant that becomes
    an expression, moves into a function or turns into a call stops being found — and something not
    being found is a red assertion below, not a quiet pass.
    """
    found: dict[str, str] = {}

    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        else:
            continue

        value = node.value
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue

        for target in targets:
            if isinstance(target, ast.Name):
                found[target.id] = value.value

    return found


def _vocabulary(tree: ast.Module) -> dict[str, str]:
    """Every name the CLI spells a word or a flag with, as `{name: literal}`.

    Three sources, because a constant is reached by a different spelling depending on which file is
    doing the reaching. `verbs.py` holds the words (`LIST = "list"`) and spells them bare inside its
    own dispatch tables; `parsing.py` holds the flags (`QUERY_FLAG = "--q"`) and `__main__.py`
    imports those bare while reaching the words through the module (`verbs.LIST`). So the map
    carries both spellings and `_resolve` looks up either.

    The module being read comes first, which is what lets the synthetic sources in
    `test_the_readers_are_not_fooled_by_prose_or_by_a_lookalike` define their own constants and be
    read on their own terms rather than against the real CLI's.
    """
    words = _string_constants(_parse(VERBS_SOURCE))
    return {
        **_string_constants(_parse(PARSING_SOURCE)),
        **words,
        **{f"verbs.{name}": value for name, value in words.items()},
        **_string_constants(tree),
    }


def _parse(path: Path) -> ast.Module:
    assert path.is_file(), (
        f"{path} is not there, so this guard has checked nothing. It is a path across the "
        "repository on purpose (see the module docstring) — if `kaya-cli` moved, move this with it "
        "rather than deleting the check."
    )
    return ast.parse(path.read_text(encoding="utf-8"), filename=path.name)


def _resolve(expr: ast.expr, vocabulary: Mapping[str, str]) -> str | None:
    """One argv token, or `None` if this reader cannot say what it is.

    `None` is the honest answer for an f-string, a concatenation or a name from somewhere this
    reader did not read, and it is the safe one: an unresolved token is a token this file cannot
    find, and a mapping row naming it fails.
    """
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return expr.value
    if isinstance(expr, ast.Name):
        return vocabulary.get(expr.id)
    if isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name):
        return vocabulary.get(f"{expr.value.id}.{expr.attr}")
    return None


def dispatch_words(source: str, *, filename: str = "verbs.py") -> set[tuple[str, str | None]]:
    """``{(command, subcommand)}`` as `kaya_cli.verbs`' two dispatch tables spell them.

    A top-level verb's key is `(word, None)` — argparse's own answer, since only the two groups
    declare a `subcommand` dest — so `("backlinks", None)` and `("note", "list")` come back from
    the same read with no shape to special-case.

    `verbs.BARE` is skipped, and skipped rather than translated: it is the one row whose key is a
    plain name instead of a tuple, because ADR 0005 §contract 7's bare `kaya` is a verb with **no
    word**. A mapping row cannot name it — there is no argv for "type nothing" — so it has no
    business being in the set a row is checked against.
    """
    tree = ast.parse(source, filename=filename)
    vocabulary = _vocabulary(tree)
    words: set[tuple[str, str | None]] = set()

    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        else:
            continue

        named = {t.id for t in targets if isinstance(t, ast.Name)}
        if not named & set(DISPATCH_TABLES) or not isinstance(node.value, ast.Dict):
            continue

        for key in node.value.keys:
            if not isinstance(key, ast.Tuple) or len(key.elts) != 2:
                continue  # `BARE`, the verb with no word
            command = _resolve(key.elts[0], vocabulary)
            subcommand = _resolve(key.elts[1], vocabulary)
            if isinstance(key.elts[1], ast.Constant) and key.elts[1].value is None:
                subcommand = None
            elif subcommand is None:
                continue
            if command is not None:
                words.add((command, subcommand))

    return words


def _flags_declared_in(func: ast.FunctionDef, vocabulary: Mapping[str, str]) -> frozenset[str]:
    """Every flag passed first to an `add_argument` call anywhere inside this function.

    Receiver-blind on purpose, and that is sound only because of where it is used: on
    `output_flags()`, whose whole body builds one parent parser, and on the single-parameter helpers
    in `__main__.py`, whose whole body decorates the one subparser they were handed
    (`_add_body_flags`, which reaches its verb through `add_mutually_exclusive_group()` — an
    intermediate this reader would otherwise have to model). A helper taking *two* parsers would be
    mis-attributed, which is why the caller below only consults helpers of arity one, and why
    `test_the_readers_found_the_cli_that_is_actually_there` names the flags it expects to arrive
    this way.
    """
    flags: set[str] = set()

    for node in ast.walk(func):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "add_argument":
            continue
        token = _resolve(node.args[0], vocabulary)
        if token is not None and token.startswith("-"):
            flags.add(token)

    return frozenset(flags)


def declared_flags(source: str, *, filename: str = "__main__.py") -> dict[str, frozenset[str]]:
    """``{word: {flags}}`` for every word `build_parser` declares an `add_parser` for.

    Keyed on the single word rather than on the `(command, subcommand)` pair, because a word's
    subparser is built in a helper that never sees its parent's name. That is sound while the words
    are unique, so uniqueness is asserted here rather than hoped for: a second `list` under another
    group makes this reader raise instead of quietly merging two verbs' flags.

    Group words (`note`, `config`) come back with whatever they declare, which is nothing — they
    are here so that a mapping row's first token can be checked as a real word and so that
    `test_the_two_readers_agree_about_which_words_exist` has both halves to compare.
    """
    tree = ast.parse(source, filename=filename)
    vocabulary = _vocabulary(tree)

    shared = frozenset()
    for node in _parse(PARSING_SOURCE).body:
        if isinstance(node, ast.FunctionDef) and node.name == SHARED_FLAGS_FACTORY:
            shared = _flags_declared_in(node, vocabulary)

    helpers = {
        node.name: _flags_declared_in(node, vocabulary)
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and len(node.args.args) == 1
    }

    found: dict[str, set[str]] = {}
    word_of: dict[str, str] = {}

    def declare(word: str | None, call: ast.Call, variable: str | None) -> None:
        if word is None:
            return
        assert word not in found, (
            f"`{word}` is declared as an `add_parser` word twice in {filename}. This reader keys "
            "flags on the word alone (see its docstring), which two verbs sharing a word makes "
            "unsound — so it refuses rather than merging them. Give this reader the "
            "(command, subcommand) pair before adding a duplicate word to the CLI."
        )
        found[word] = set()
        if variable is not None:
            word_of[variable] = word
        for keyword in call.keywords:
            if keyword.arg != "parents" or not isinstance(keyword.value, ast.List):
                continue
            for element in keyword.value.elts:
                if isinstance(element, ast.Name) and element.id == SHARED_FLAGS_VAR:
                    found[word] |= shared

    for func in (node for node in tree.body if isinstance(node, ast.FunctionDef)):
        for statement in func.body:
            call = _add_parser_call(statement)
            if call is not None:
                declare(_resolve(call.args[0], vocabulary), call, _assigned_name(statement))
                continue

            if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
                continue
            call = statement.value

            if (
                isinstance(call.func, ast.Attribute)
                and call.func.attr == "add_argument"
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id in word_of
                and call.args
            ):
                token = _resolve(call.args[0], vocabulary)
                if token is not None and token.startswith("-"):
                    found[word_of[call.func.value.id]].add(token)
            elif (
                isinstance(call.func, ast.Name)
                and call.func.id in helpers
                and call.args
                and isinstance(call.args[0], ast.Name)
                and call.args[0].id in word_of
            ):
                found[word_of[call.args[0].id]] |= helpers[call.func.id]

    return {word: frozenset(flags) for word, flags in found.items()}


def _add_parser_call(statement: ast.stmt) -> ast.Call | None:
    """The `X.add_parser(WORD, …)` in this statement, assigned or bare.

    Bare matters: `config show` and `config path` take no arguments of their own, so their
    subparsers are statements rather than assignments, and a reader that only looked at assignments
    would report two of the CLI's eleven words as not existing.
    """
    value: ast.expr | None = None
    if isinstance(statement, ast.Assign | ast.Expr):
        value = statement.value

    if (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Attribute)
        and value.func.attr == "add_parser"
        and value.args
    ):
        return value
    return None


def _assigned_name(statement: ast.stmt) -> str | None:
    if (
        isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
    ):
        return statement.targets[0].id
    return None


def _cli_words() -> set[tuple[str, str | None]]:
    return dispatch_words(VERBS_SOURCE.read_text(encoding="utf-8"))


def _cli_flags() -> dict[str, frozenset[str]]:
    return declared_flags(PARSER_SOURCE.read_text(encoding="utf-8"))


def _split(invocation: tuple[str, ...]) -> tuple[tuple[str, str | None], tuple[str, ...]]:
    """One row as `((command, subcommand), flags)`. Words first, then flags — argv's own order."""
    words = tuple(token for token in invocation if not token.startswith("-"))
    flags = tuple(token for token in invocation if token.startswith("-"))

    assert 1 <= len(words) <= 2, (
        f"`{' '.join(invocation)}` does not name one or two CLI words. A row is a group and a verb "
        "(`note list`) or a top-level verb (`backlinks`); `kaya` has no third level and no row may "
        "invent one."
    )
    assert invocation[: len(words)] == words, (
        f"`{' '.join(invocation)}` interleaves a flag with its words. Write the words first, the "
        "way a person types them, so `_split` cannot mistake a flag's value for a verb."
    )
    return (words[0], words[1] if len(words) == 2 else None), flags


# ------------------------------------------------- the positive controls, before the guard


def test_the_readers_found_the_cli_that_is_actually_there() -> None:
    """Both readers, shown working, on facts chosen because they discriminate.

    Every assertion below the line is of the form "this row names something real", and each of them
    passes trivially if a reader returns everything, and fails loudly if a reader returns nothing.
    The dangerous case is the third one — a reader that returns *something* while being wrong about
    which verb owns what — so these are not "did it find anything" checks. Each one is a fact a
    broken reader would get wrong in a specific way:

    - `--q` is on `note list` and **not** on `note get`. That is per-verb attribution, which is the
      single thing `declared_flags` could plausibly get wrong while still looking healthy, and it
      is the fact `search_notes`' row rests on.
    - `--if-updated-at` is on `note edit` and nowhere else (ADR 0009's precondition, and KAN-551's
      "no `--force`"), so the attribution is checked on a second verb rather than on one.
    - `--full` is on `note list` **via `parents=[flags]`**, which is the only assertion that
      exercises the shared-parent branch at all.
    - `--body` is on `note create` **via `_add_body_flags`**, the only assertion that exercises the
      single-parameter-helper branch — and that helper reaches its verb through
      `add_mutually_exclusive_group()`, so this is also what proves the receiver-blind read of a
      helper body is doing its job.
    """
    words = _cli_words()
    flags = _cli_flags()

    assert ("note", "list") in words
    assert ("backlinks", None) in words
    assert ("config", "show") in words

    assert "--q" in flags["list"]
    assert "--q" not in flags["get"]
    assert "--if-updated-at" in flags["edit"]
    assert "--if-updated-at" not in flags["list"]
    assert "--full" in flags["list"]  # inherited through parents=[flags]
    assert "--body" in flags["create"]  # added by the _add_body_flags helper
    assert "--body" not in flags["move"]


def test_the_two_readers_agree_about_which_words_exist() -> None:
    """Two files, two readers, one vocabulary — so neither can go blind unnoticed.

    `dispatch_words` reads `verbs.py`'s tables and `declared_flags` reads `__main__.py`'s parser,
    and the words they find have to be the same words. This is the control that does not depend on
    anybody writing a verb name down over here: if a constant moves, a helper is renamed, or
    argparse is called some new way, one reader stops seeing part of the CLI and this fails, rather
    than the guard below quietly having less to check.

    The two sets are not identical in shape — `declared_flags` also sees the two **group** words,
    since `note` and `config` are `add_parser` calls too, while a dispatch key names a group only
    as the left half of a pair — so the group words are added to the left-hand side, derived from
    the pairs rather than typed out.
    """
    pairs = _cli_words()
    groups = {command for command, subcommand in pairs if subcommand is not None}
    leaves = {subcommand or command for command, subcommand in pairs}

    assert leaves, "the dispatch-table reader found no words at all"
    assert set(_cli_flags()) == groups | leaves


def test_the_shared_parent_parser_is_the_one_this_reader_thinks_it_is() -> None:
    """`declared_flags` treats `parents=[flags]` as `output_flags()`' set on the strength of a
    variable *name*. That coupling is checked here rather than assumed: `build_parser` has to
    actually assign `output_flags()` to `flags`, or the name means nothing and the shared-flag half
    of the reader is reading a variable that no longer holds what it did.
    """
    tree = _parse(PARSER_SOURCE)
    assigned = {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == SHARED_FLAGS_FACTORY
        for target in node.targets
        if isinstance(target, ast.Name)
    }

    assert SHARED_FLAGS_VAR in assigned, (
        f"nothing in {PARSER_SOURCE.name} assigns `{SHARED_FLAGS_FACTORY}()` to "
        f"`{SHARED_FLAGS_VAR}` any more, so `declared_flags` is matching "
        f"`parents=[{SHARED_FLAGS_VAR}]` against a name that no longer means the shared output "
        "flags. Point SHARED_FLAGS_VAR at the new name."
    )


def test_the_readers_are_not_fooled_by_prose_or_by_a_lookalike() -> None:
    """The scanners, run on sources written to break them. An AST read is only worth the trouble if
    it is provably not a grep, so the last two cases are the ones a grep gets wrong.

    The vacuity failure this file is most exposed to is the one CLAUDE.md §Conventions names: a
    probe that matched a *docstring* mentioning the constant instead of the constant, so the
    "mutation" was a comment. Both readers are shown refusing exactly that.
    """
    table = 'NOTE = "note"\nLIST = "list"\nVERBS = {(NOTE, LIST): _f, BARE: _g}\n'
    assert dispatch_words(table) == {("note", "list")}

    # A top-level verb: `(word, None)`, and `None` has to survive as `None` rather than being
    # dropped for failing to resolve to a string.
    assert dispatch_words('LINKS = "links"\nVERBS = {(LINKS, None): _f}\n') == {("links", None)}

    # A dict that is not one of the two dispatch tables says nothing about the CLI's vocabulary.
    assert dispatch_words('NOTE = "note"\nLIST = "list"\nHELP = {(NOTE, LIST): "x"}\n') == set()

    # Prose. `verbs.py` is a heavily documented module and its docstring names both tables and
    # several words; a text scan would read this as a verb.
    assert dispatch_words('"""VERBS = {("note", "list"): _f} is the table."""\n') == set()

    parser = 'Q = "--q"\ndef build():\n    v = c.add_parser("list")\n    v.add_argument(Q)\n'
    assert declared_flags(parser) == {"list": frozenset({"--q"})}

    # A word declared with no flags of its own is a word, not an absence — `config show`.
    assert declared_flags('def build():\n    c.add_parser("show")\n') == {"show": frozenset()}

    # A flag whose name this reader cannot resolve is not silently treated as absent-and-fine: it
    # simply is not found, which is what makes a row naming it go red.
    unresolvable = 'def build():\n    v = c.add_parser("list")\n    v.add_argument(f"--{x}")\n'
    assert declared_flags(unresolvable) == {"list": frozenset()}

    # `add_argument` on something that is not a known subparser is not a verb's flag. This is the
    # `parser.add_argument("--version")` case in `build_parser`, which belongs to no verb.
    assert declared_flags('def build():\n    p.add_argument("--version")\n') == {}

    # Prose again, and the same lesson: `__main__.py`'s docstrings quote flags constantly.
    assert declared_flags('def build():\n    """add_parser("list") and --q go here."""\n') == {}


# --------------------------------------------------------------------------------- the guard


def test_every_frozen_tool_has_a_row() -> None:
    """ADR 0006 §4 rule 2, first half: no tool without a CLI equivalent written down.

    Both directions in one assertion, because both are the same mistake seen from either end. A
    tool with **no** row is a tool whose CLI verb nobody named — which is how pandan grew four MCP
    capabilities no CLI command could reach. A row with **no** tool is a claim about a surface that
    is not there, and it is the quieter of the two: it keeps this file looking thorough while
    guarding nothing.
    """
    assert set(CLI_EQUIVALENT) == set(TOOL_NAMES), (
        "the parity table and `kaya_mcp.TOOL_NAMES` disagree about which tools exist.\n"
        "  A tool with no row: name its CLI verb in CLI_EQUIVALENT and in mcp/README.md's "
        "MCP → KayaClient → CLI table. If you cannot name one, that is the answer — `MCP ⊆ CLI` "
        "(ADR 0006 §4) means the capability lands in the CLI first and the tool follows it, never "
        "the other way round.\n"
        "  A row with no tool: the row goes when the tool goes, and "
        "`tests/test_frozen_tool_set.py` is where the removal has to be argued first — see the "
        "message it prints."
    )


def test_every_frozen_tool_names_a_cli_verb_that_exists() -> None:
    """ADR 0006 §4 rule 2, second half, and the reason the CLI is read rather than listed.

    A row pointing at a word `kaya-cli` does not have must fail, and so must a row that *did* point
    at a real word until somebody renamed the verb in the other package. Both come out of the same
    membership test, because the right-hand side is `verbs.py`'s own dispatch tables — the thing a
    rename edits — and not a copy of them kept here.
    """
    words = _cli_words()
    assert words, "the dispatch-table reader found nothing; see the positive controls above"

    for tool, invocation in sorted(CLI_EQUIVALENT.items()):
        word, _ = _split(invocation)
        spelling = "kaya " + " ".join(invocation)
        named = " ".join(part for part in word if part is not None)
        assert word in words, (
            f"`{tool}` says its CLI equivalent is `{spelling}`, and `{named}` is not a verb "
            "`kaya-cli` has.\n"
            f"  The words it does have: {sorted(words)}.\n"
            "  If a CLI verb was renamed or removed, this is the parity check ADR 0006 §4 asks "
            "for, working: either update this row to the new spelling, or restore the verb. "
            "`MCP ⊆ CLI` is a claim about today's CLI, so a tool whose verb has gone is a tool "
            "with nothing behind it — not a row to delete quietly."
        )


def test_every_flag_a_row_names_is_declared_on_that_verb() -> None:
    """The half a name-keyed parity test cannot have, and the reason the table is argv rather than
    words.

    `search_notes` is `kaya note list --q TERM`, so `--q` has to be a flag `note list` actually
    declares. Deleting it from `__main__.py` — or moving it onto another verb, or renaming it —
    leaves `search_notes` with no CLI spelling, and the word half of this file would not notice,
    because `note list` still exists for `list_notes`.
    """
    flags = _cli_flags()

    for tool, invocation in sorted(CLI_EQUIVALENT.items()):
        (command, subcommand), named = _split(invocation)
        verb = subcommand or command
        for flag in named:
            assert flag in flags.get(verb, frozenset()), (
                f"`{tool}` says its CLI equivalent is `kaya {' '.join(invocation)}`, and `{flag}` "
                f"is not declared on `{verb}`.\n"
                f"  What `{verb}` declares: {sorted(flags.get(verb, ()))}.\n"
                f"  A flag is in a row only when the verb without it is a different capability — "
                "`--q` is what makes `note list` a search — so a missing one means this tool has "
                "no CLI spelling any more, even though its verb still exists. Restore the flag, or "
                "amend ADR 0006 §2 and remove the tool through "
                "`tests/test_frozen_tool_set.py`'s checklist."
            )


def test_the_one_row_that_is_not_a_verb_word_is_the_one_the_readme_warns_about() -> None:
    """`search_notes` is the row this whole design exists for, so it is asserted directly.

    `mcp/README.md`'s table footnote says a parity test keyed on tool *names* would go looking for a
    `kaya search_notes` that will never exist. This is that warning turned into an assertion: the
    row is allowed to be the odd one, and it is the **only** one allowed to be, so a second tool
    quietly acquiring a flag-shaped equivalent is a visible edit here rather than a precedent
    somebody follows.
    """
    flagged = {tool for tool, row in CLI_EQUIVALENT.items() if any(t.startswith("-") for t in row)}
    assert flagged == {"search_notes"}

    assert CLI_EQUIVALENT["search_notes"][:2] == CLI_EQUIVALENT["list_notes"], (
        "`search_notes` and `list_notes` are the same CLI verb and a flag apart, because "
        "`KayaClient.list_notes(q)` is the one call behind both (KAN-558/559). If that stops being "
        "true, the README's table and this row both need the new answer."
    )
