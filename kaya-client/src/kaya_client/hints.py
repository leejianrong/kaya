"""ADR 0005 §contract 8: the ``help[]`` next-step templates. **Live since KAN-550.**

    Results carry ``help[]`` next-step **templates** with placeholders left unfilled.
    Every hint must parse as a real command, pinned by a test.

Two lines of contract, and each one is a decision this module had to make rather than implement.

### Human-only, and **deliberately the opposite of KAN-547's truncation hint**

SLICES §V2b item 5 ends "**Suppressed under structured formats**", and the sibling tool agrees:
`pandan get KAN-724` prints ``help: pandan move <id> in_progress`` on a terminal, and the same read
under ``--format json`` carries no ``help`` key at all. So a hint is something `human` adds, not
something the payload gains — which is why this module is not a fifth step of ADR 0004's pipeline
and why `serialization._as_human` is the only thing that calls it. Nothing here touches a
``Payload``; ``render``'s four steps are the same four.

That is the reverse of the decision KAN-547 made two cards ago, and the contrast is the point rather
than an inconsistency somebody should tidy up:

- **A truncation hint carries a true total.** That is a fact about *this* payload which a structured
  consumer cannot obtain any other way — the untruncated string is gone by the time it could count —
  so ADR 0005's amendment of the same date put it in-band, inside the string, where `json`, `toon`
  and `data` all reach it.
- **A help template carries no fact about the payload at all.** It is a static per-kind string, the
  same bytes on every read forever, and an agent learns it once from ``kaya --help`` or from this
  registry. Paying for it on every structured read would be spending tokens to repeat something the
  consumer already knows — the exact cost ADR 0004 exists to recover, incurred by the layer written
  to recover it.

The rule that separates them: **in-band if it is data about this result, human-only if it is advice
about the tool.** Do not "fix" one to match the other.

### Derived from the ``Payload``, never from a verb name

``render``'s signature is frozen by ADR 0005's sequencing rule and has now absorbed five V2b cards
unmoved. There is no verb parameter and there must not be one, so the templates are keyed on
``(payload.kind, payload.noun)`` — the two facts `KayaClient` and `kaya_client.config` already
attach at the call. A collection of notes suggests different next steps than one note does, which is
what ``kind`` answers, and `config show` is a collection of ``setting`` rather than of ``note``,
which is what ``noun`` answers.

**An unknown key emits nothing.** A payload nobody wrote templates for is silent rather than falling
back to a note's, so KAN-566's ``/links`` and ``/backlinks`` arrive with no hints instead of with
wrong ones, and adding them is adding a row here.

**What that derivation costs, stated rather than hidden.** `note delete` returns an *entity* with
``noun="note"`` (a ``{ref, deleted}`` record — see `client.delete_note`), so it is handed the same
single template a `note get` is. A caller who has just deleted a note is told how to edit *a* note,
with the ref left unfilled. That is mildly redundant and it is the honest price of the rule: the
alternatives are a verb parameter, which is ADR 0005's stop signal, or sniffing the record for a
``deleted`` key, which is precisely the fragility `payloads`' own docstring rejects ("sniffing for a
``notes`` key would work today and break the day `/links` lands"). One redundant line beats either.

### Fewer, and each one justified

Every line here is paid on every human read forever, so a hint has to answer "what does the caller
do next?" rather than "what else exists?". The menu already exists and is ``kaya --help``, whose
epilogue lists all nine verbs; a hint block that reproduced it would be the same information twice,
in the place it costs the most. Pandan emits two or three. Kaya emits at most two:

- **a `note list`** → ``note get <ref>`` (read one of the rows just printed) and
  ``note create <title>`` (the other thing a list is a jumping-off point for). `move` and `delete`
  are not offered: they are not what a caller does next from a listing, and `delete` in particular
  is destructive and needs no advertising.
- **one note** → ``note edit <ref> --body-file <path>``, the template SLICES §V2b names verbatim,
  and the one next step that is true of every single-note result. It is *one* line rather than a
  set, which is also what keeps the `note delete` redundancy above to a single line.
- **`config show` / `config path`** → ``config set``, with both flags on one line. Configuration is
  the one place a caller reads output specifically because something is wrong, and `config set` is
  the fix; naming both flags in one template costs a line rather than two. What contract 8 cannot
  express here is the *other* answer — ``export KAYA_TOKEN=…``, the spelling that never touches the
  disk — because a hint must parse as a kaya command and that is a shell builtin. The caveat about
  putting a credential in argv lives on ``--token``'s own help text, where a caller meets it before
  typing one.

### A placeholder stays a placeholder

``kaya note edit <ref> --body-file <path>``, never ``kaya note edit NOTE-12``. Interpolating a value
from the payload would produce a line a caller can paste — which is the danger, not the feature: the
line a `note list` would interpolate is the *first row's* ref, and a caller pasting an edit or a
delete aimed at whichever note happened to sort first is a data-loss bug wearing a convenience.
Contract 8 says "placeholders left unfilled" for that reason, and the templates below are module
constants precisely so that there is no record in scope for one to be filled from.

The zero state is the one thing that varies, and it varies on ``records`` rather than on their
contents: ``note get <ref>`` addresses a row, and an empty `note list` has none, so it is dropped
and ``note create <title>`` is left. An empty result is exactly where a next step is worth most —
the sentence ``no notes`` answers "what have I got" and answers nothing about what to do — and
offering to fetch one of the zero rows above would be the menu failure this module's whole budget
argument is against.

### Where the "must parse" guard lives, and why it is in the other package

`kaya-cli/tests/test_help_templates.py`. The parser is `kaya_cli`'s and the templates are this
package's, and ADR 0004 points the dependency arrow that way, so the test sits on the side that can
see both — the same cross-package shape as
`backend/tests/unit/test_client_deadline_outlasts_auth.py`, which reads a constant out of
`kaya-client`'s AST because the two numbers it compares live in packages that may not import each
other. `kaya_cli.parsing.StructuredParser` raises instead of exiting, which is what makes feeding
every template to the **real** parser a test rather than a subprocess. Pandan's spec shipped
``comment add <id> "…"``, which is not a valid command because the body needs ``--body``, and the
wrong form propagated into a card; comparing strings would not have caught it and parsing does.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from kaya_client.payloads import Kind, Payload

PROG = "kaya"
"""The console script every template starts with (`kaya-cli`'s ``PROG``, spelled once here).

Written out rather than imported: ADR 0004 points the dependency arrow from the adapters at this
package, so `kaya_client` may not read a name out of `kaya_cli`. The two agreeing is checked by the
parse test in `kaya-cli`, which strips this word before handing the rest to that package's own
parser and would fail on any other spelling."""

HELP_PREFIX = "help: "
"""What marks a hint line. Pandan's spelling, adopted verbatim for the same reason ADR 0005 adopts
its exit codes verbatim: an operator fluent in one tool's output should not have to learn a second
word for the same thing.

It is a prefix rather than a heading over an indented block so that every line is independently
greppable and independently strippable — ``kaya note list | grep '^help: '`` is the whole of
"what can I do next", and a consumer that wants the answer alone does not have to track state
across lines."""


@dataclass(frozen=True)
class Hint:
    """One template, and whether it names a row that has to exist for it to make sense."""

    template: str
    addresses_a_row: bool = False
    """``True`` for a template whose placeholder stands for one of the records above it.

    The only thing about a hint that depends on the payload's *contents* rather than on its shape,
    and it depends on ``len(records)`` alone — never on a value, which is what keeps
    `test_a_hint_never_carries_a_value_from_the_payload` a property rather than a sample."""


NOTE_NOUN = "note"
SETTING_NOUN = "setting"
CONFIG_NOUN = "config file"
"""The nouns `KayaClient` and `kaya_client.config` attach to the payloads they build.

Spelled here rather than imported from `client`, which would drag httpx into `serialization`'s
import chain and point a dependency arrow from a formatter at a transport. That they still match is
asserted by `tests/test_hints.py` against the real builders, so a renamed noun is a red test rather
than a registry that silently stops matching anything."""

HINTS: Mapping[tuple[Kind, str], tuple[Hint, ...]] = {
    (Kind.COLLECTION, NOTE_NOUN): (
        Hint(f"{PROG} note get <ref>", addresses_a_row=True),
        Hint(f"{PROG} note create <title>"),
    ),
    (Kind.ENTITY, NOTE_NOUN): (Hint(f"{PROG} note edit <ref> --body-file <path>"),),
    (Kind.COLLECTION, SETTING_NOUN): (Hint(f"{PROG} config set --api-url <url> --token <pat>"),),
    (Kind.ENTITY, CONFIG_NOUN): (Hint(f"{PROG} config set --api-url <url> --token <pat>"),),
}
"""``(kind, noun)`` → the templates that result offers. See this module's docstring for each one.

A table rather than a chain of conditionals, so "which hints does this payload get?" is a lookup a
reader can check exhaustively, and so `kaya-cli`'s parse test can iterate every template that
exists rather than only the ones some fixture happens to reach."""


def help_lines(payload: Payload) -> tuple[str, ...]:
    """The commands this payload suggests next, unprefixed, placeholders unfilled.

    **One parameter, and it is the payload** — the same arity argument `aggregates.attach_summary`
    makes. There is no verb name in scope, nowhere for one to arrive from, and adding one would mean
    widening ``render``'s frozen signature to carry it, which is a visible thing to do in review and
    is ADR 0005's stop signal rather than a step. `tests/test_hints.py` asserts the arity for that
    reason.

    Returns ``()`` for a payload the registry has no row for, which is the only behaviour that keeps
    a future envelope silent instead of wrong.
    """
    if not isinstance(payload, Payload):
        raise TypeError(
            "help_lines takes a Payload — the templates are derived from its kind and noun, "
            "never from a verb name passed in (ADR 0005 §contract 8)"
        )
    hints = HINTS.get((payload.kind, payload.noun), ())
    return tuple(hint.template for hint in hints if payload.records or not hint.addresses_a_row)


def help_block(payload: Payload) -> str | None:
    """`help_lines` as the block `human` prints, or ``None`` when there is nothing to say.

    ``None`` rather than ``""`` so that `serialization._as_human` appends a block or does not,
    without a separator to decide about — the same shape `aggregates.summary_line` already returns
    for a result that has no footer.
    """
    lines = help_lines(payload)
    if not lines:
        return None
    return "\n".join(f"{HELP_PREFIX}{line}" for line in lines)
