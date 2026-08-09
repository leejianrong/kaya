"""**Every ``help[]`` template parses as a real command.** ADR 0005 §contract 8, KAN-550.

    Every hint must parse as a real command, pinned by a test.

That sentence is in the ADR because pandan's spec shipped ``pandan comment add <id> "…"``, which is
**not** a valid command — the body needs ``--body`` — and the wrong form propagated into a card
before anybody noticed. A test comparing strings would not have caught it. A test that feeds each
template to the parser does, which is what this file is.

### Why it lives in `kaya-cli` and the templates live in `kaya-client`

The templates are output, so ADR 0004 puts them in `kaya_client.hints` with every other shaping
decision; the parser is how *this* adapter gets its arguments, so it is here. Neither package can
hold both halves, and the arrow points from here to there — so the guard sits on the side that can
see both, exactly like `backend/tests/unit/test_client_deadline_outlasts_auth.py`, which reads a
constant out of `kaya-client` because the two numbers it compares live in packages that may not
import each other.

`kaya_cli.parsing.StructuredParser` is what makes this a test rather than a subprocess: it raises
``UsageError`` where a stock ``ArgumentParser`` would call ``sys.exit``, so a template that does not
parse fails an assertion here instead of killing the test runner.

### What "parses" is taken to mean

Three things, in order, because each catches a different way a template can be wrong:

1. **argparse accepts it.** The pandan defect: a positional where the parser wants a flag.
2. **it names a verb that exists.** A template could parse as ``kaya --version`` and be useless as a
   next step, or name a subcommand pair no dispatch table has a row for.
3. **it is a template, not a command.** Every one carries an unfilled ``<placeholder>``. That half
   is the client's to assert over a rendered payload (`kaya-client/tests/test_hints.py`); what is
   checked here is that the placeholder survives the parse — i.e. that the thing the parser accepted
   is the thing a reader was shown.
"""

import shlex

import pytest
from kaya_client.hints import HINTS, PROG, Hint

from kaya_cli.__main__ import build_parser
from kaya_cli.verbs import LOCAL_VERBS, VERBS

EVERY_TEMPLATE: list[tuple[str, Hint]] = [
    (f"{kind}/{noun}", hint) for (kind, noun), hints in HINTS.items() for hint in hints
]
"""Every template in the registry, not only the ones some fixture's payload reaches.

Built from ``HINTS`` itself so a row added there is covered without anybody adding a case here —
which is the property that would have caught pandan's defect, since the bad template was in a spec
nothing iterated."""

IDS = [f"{key} :: {hint.template}" for key, hint in EVERY_TEMPLATE]


def argv(template: str) -> list[str]:
    """A template as the argv a shell would hand `main`, with the program name stripped.

    ``shlex`` rather than ``str.split`` because a template is written the way a person would type
    it, and the day one carries a quoted argument the naive split would silently produce two.
    """
    words = shlex.split(template)
    assert words[0] == PROG, f"{template!r} does not start with {PROG!r}"
    return words[1:]


@pytest.mark.parametrize(("key", "hint"), EVERY_TEMPLATE, ids=IDS)
def test_every_template_parses(key: str, hint: Hint) -> None:
    """**The card's whole point.** The real parser, on the real templates, one at a time.

    A failure names the template that does not parse, so the diagnosis is the assertion message
    rather than a bisect: that is the difference between this and the string comparison that let
    ``comment add <id> "…"`` reach a card.
    """
    parser = build_parser()
    try:
        parsed = parser.parse_args(argv(hint.template))
    except BaseException as refused:  # noqa: BLE001 - the message is the test's whole output
        pytest.fail(f"{key}: {hint.template!r} does not parse — {refused}")

    assert parsed is not None


@pytest.mark.parametrize(("key", "hint"), EVERY_TEMPLATE, ids=IDS)
def test_every_template_names_a_verb_that_exists(key: str, hint: Hint) -> None:
    """Parsing is necessary and not sufficient: ``kaya --version`` parses and is not a next step.

    The pair ``(command, subcommand)`` is what `verbs.run` dispatches on, and the two tables are
    exhaustive over the parser's own words (`test_verbs.py` asserts that separately). So a template
    naming a word that has no row would be advice pointing at a verb that cannot run.
    """
    parsed = build_parser().parse_args(argv(hint.template))
    word = (parsed.command, parsed.subcommand)

    assert word in VERBS or word in LOCAL_VERBS, f"{key}: {hint.template!r} names no verb"


@pytest.mark.parametrize(("key", "hint"), EVERY_TEMPLATE, ids=IDS)
def test_every_template_keeps_its_placeholders_through_the_parse(key: str, hint: Hint) -> None:
    """The placeholder is not merely present in the string — it is what the parser took as a value.

    A template that put ``<ref>`` inside a comment, a flag name or some other decoration would pass
    the client's "contains a placeholder" check and still show a caller something they cannot fill
    in. Here every ``<…>`` word must survive as one of the parsed values.
    """
    parsed = build_parser().parse_args(argv(hint.template))
    placeholders = {word for word in argv(hint.template) if word.startswith("<")}
    assert placeholders, f"{key}: {hint.template!r} has no placeholder to fill in"

    values = {value for value in vars(parsed).values() if isinstance(value, str)}
    assert placeholders <= values, f"{key}: {hint.template!r} lost {placeholders - values}"


def test_a_positional_where_a_flag_belongs_is_caught() -> None:
    """The mutation guard, run as a test: pandan's actual defect, refused by this parser.

    ``kaya note create <title> <body>`` is the shape of ``comment add <id> "…"`` — a second
    positional where the schema wants a named flag — and it is what the parametrized test above
    would report if a template were written that way. Asserted here so the guard's own failure mode
    is exercised on every run rather than only when somebody remembers to break a template.
    """
    parser = build_parser()
    with pytest.raises(BaseException):  # noqa: B017,PT011 - StructuredParser raises UsageError
        parser.parse_args(argv(f"{PROG} note create <title> <body>"))


def test_the_registry_is_not_empty() -> None:
    """A guard over the guard. Every assertion above is parametrized over ``HINTS``, so an empty
    registry would make this file pass while contract 8 shipped nothing at all."""
    assert EVERY_TEMPLATE
