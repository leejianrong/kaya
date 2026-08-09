"""ADR 0005 §contract 8 (KAN-550): the ``help[]`` templates, and the two things they must never do.

Contract 8 is two clauses and a note, and each one is tested somewhere different on purpose:

1. **"Results carry ``help[]`` next-step templates"** — here, per payload kind and noun.
2. **"with placeholders left unfilled"** — here, as a property over the *rendered* block rather than
   over the registry, so a card that starts interpolating goes red even though the constants it
   interpolates from are still templates.
3. **"Every hint must parse as a real command, pinned by a test"** —
   `kaya-cli/tests/test_help_templates.py`, because the parser lives in that package and ADR 0004
   points the dependency arrow that way. That is the same cross-package shape
   `backend/tests/unit/test_client_deadline_outlasts_auth.py` uses for the same reason.

And SLICES §V2b's own clause, **"suppressed under structured formats"**, which is asserted against
all three of them rather than against `json` alone: a hint that reached `data` would reach V6's MCP
``structuredContent``, which is the surface this whole package exists to keep cheap.

The byte-level pin on where the block *goes* is `test_human_row_is_pinned.py`, which KAN-550 was
allowed to move and whose docstring records exactly which literals it moved.
"""

import inspect
import json

import pytest
from conftest import GROCERIES, READING_LIST, note_collection, note_entity
from toon_decode import decode as decode_toon

from kaya_client import (
    HELP_PREFIX,
    HINTS,
    AdapterFormat,
    Format,
    Payload,
    help_block,
    help_lines,
    path_payload,
    render,
    settings_payload,
)
from kaya_client.client import NOTE_NOUN
from kaya_client.config import CONFIG_NOUN, SETTING_NOUN
from kaya_client.hints import Hint
from kaya_client.payloads import Kind

PLACEHOLDER = "<"
"""What makes a word a placeholder rather than a value. Angle brackets, per ADR 0005 §contract 8's
own spelling (``kaya note edit <ref> --body-file …``) and pandan's ``pandan move <id> …``."""


# ------------------------------------------------------------- which hints, per payload


def test_a_note_list_offers_reading_one_and_creating_one(notes: Payload) -> None:
    """The two things a caller does from a listing. Not `move` or `delete`: neither is what follows
    a list, and `--help`'s epilogue is the menu."""
    assert help_lines(notes) == ("kaya note get <ref>", "kaya note create <title>")


def test_one_note_offers_editing_it(note: Payload) -> None:
    """SLICES §V2b's own example, verbatim, and deliberately the only one — a single line rather
    than a set, because every line is paid on every read forever."""
    assert help_lines(note) == ("kaya note edit <ref> --body-file <path>",)


def test_the_config_verbs_offer_the_verb_that_fixes_them() -> None:
    """`config show` and `config path` are read when something is misconfigured, and `config set` is
    the fix. Both flags on one line, so it costs one line rather than two.

    Asserted through the shipped payload builders rather than through a hand-built payload, because
    half of what this card had to get right is that a `config` result reaches the *config* row of
    the registry and not the note one.
    """
    assert help_lines(settings_payload()) == ("kaya config set --api-url <url> --token <pat>",)
    assert help_lines(path_payload()) == ("kaya config set --api-url <url> --token <pat>",)


def test_an_unrecognised_payload_gets_no_hints() -> None:
    """KAN-566's `/links` and `/backlinks` arrive silent rather than carrying a note's next steps.

    Fail-closed is the only behaviour that keeps "adding an envelope" and "writing its hints" the
    same commit: a fall-back to the note templates would ship wrong advice that nothing reddens.
    """
    links = Payload.collection(noun="link", envelope_key="links", records=[], columns=("ref",))
    assert help_lines(links) == ()
    assert help_block(links) is None


# --------------------------------------------------------------------- the zero state


def test_an_empty_list_offers_creating_and_not_getting() -> None:
    """The one thing that varies with the records, and it varies on their *number*.

    ``note get <ref>`` addresses one of the rows above it, and an empty list has none — offering to
    fetch one of zero rows is the menu failure this module's budget argument is against. The other
    template is untouched, and an empty result is where it is worth most.
    """
    assert help_lines(note_collection()) == ("kaya note create <title>",)
    assert render(note_collection()) == "no notes\n\nhelp: kaya note create <title>"


def test_a_one_row_list_still_offers_getting() -> None:
    """The boundary is zero rows, not "few" rows: one note is a collection and `get` applies."""
    assert help_lines(note_collection(GROCERIES)) == (
        "kaya note get <ref>",
        "kaya note create <title>",
    )


# ---------------------------------------------------- suppressed under structured formats


@pytest.mark.parametrize("fmt", [Format.JSON, Format.TOON, AdapterFormat.DATA])
def test_no_structured_format_carries_a_hint(notes: Payload, note: Payload, fmt: str) -> None:
    """SLICES §V2b: "suppressed under structured formats". Asserted over the raw output, so a hint
    smuggled in as a value inside a record would fail here too.

    ``data`` is in the list because it is what V6's MCP server returns as ``structuredContent``. A
    template is a static string an agent learns once from ``--help``; paying for it on every
    structured read would be the cost ADR 0004 exists to recover, spent by the layer written to
    recover it. This is deliberately the *opposite* of KAN-547's truncation hint, which is in-band
    precisely because it carries a fact — a true total — that no structured consumer can otherwise
    obtain.
    """
    for payload in (notes, note):
        rendered = render(payload, fmt=fmt)
        text = rendered if isinstance(rendered, str) else json.dumps(rendered, ensure_ascii=False)
        assert HELP_PREFIX not in text
        for hint in help_lines(payload):
            assert hint not in text


def test_no_structured_format_grows_a_help_key(notes: Payload) -> None:
    """The other way a hint could arrive structurally: beside ``summary`` in the envelope."""
    as_data = render(notes, fmt="data")
    assert isinstance(as_data, dict)
    assert set(as_data) == {"notes", "summary"}
    assert set(json.loads(str(render(notes, fmt="json")))) == {"notes", "summary"}
    assert set(decode_toon(str(render(notes, fmt="toon")))) == {"notes", "summary"}


# ------------------------------------------------ a placeholder stays a placeholder


@pytest.mark.parametrize(
    "payload",
    [
        note_collection(GROCERIES, READING_LIST),
        note_collection(GROCERIES),
        note_collection(),
        note_entity(GROCERIES),
        note_entity(READING_LIST),
    ],
    ids=["two-notes", "one-note", "empty", "groceries", "reading-list"],
)
def test_a_hint_never_carries_a_value_from_the_payload(payload: Payload) -> None:
    """**The mutation this file exists for.** A hint with a real ref in it is a line a caller
    pastes, and the ref it would carry is whichever note happened to sort first — so an interpolated
    `edit` or `delete` aimed at the wrong note is a data-loss bug wearing a convenience.

    Asserted over the emitted block rather than over ``HINTS``, so interpolation *at render time*
    fails here even though every constant in the registry is still a template.
    """
    block = help_block(payload)
    assert block is not None

    values = {str(value) for record in payload.records for value in record.values() if value != ""}
    for line in block.splitlines():
        assert line.startswith(HELP_PREFIX)
        assert PLACEHOLDER in line, f"{line!r} carries no placeholder"
        for value in values:
            assert value not in line, f"{line!r} carries {value!r} from the payload"


def test_every_registered_template_is_a_template() -> None:
    """The same property one level down, over the registry itself rather than over one render.

    Every template names at least one placeholder, which is what makes the emitted-block assertion
    above a real check: a hint with nothing to fill in could never fail it.
    """
    for key, hints in HINTS.items():
        for hint in hints:
            assert PLACEHOLDER in hint.template, f"{key} → {hint.template!r} has no placeholder"


# ------------------------------------------------------------------- the derivation


def test_help_lines_takes_the_payload_and_nothing_else() -> None:
    """The arity assertion, and the same one `test_aggregates.py` makes about ``attach_summary``.

    ``render``'s signature is frozen by ADR 0005's sequencing rule, so a template keyed on a *verb*
    would need a fifth parameter threaded from the adapter — which is the stop signal, not a step.
    Keying on ``(kind, noun)`` means the wrong answer is not reachable from inside this function:
    producing it requires widening a signature, which is a visible thing to do in review.
    """
    parameters = list(inspect.signature(help_lines).parameters)
    assert parameters == ["payload"]

    with pytest.raises(TypeError, match="never from a verb name"):
        help_lines({"notes": []})  # type: ignore[arg-type]


def test_the_registry_is_keyed_on_the_nouns_the_client_actually_attaches() -> None:
    """`hints` spells the nouns rather than importing them from `client` and `config`, which would
    point a dependency arrow from a formatter at a transport. This is what keeps that safe.

    A noun renamed at the call site is a red test here, not a registry that silently matches
    nothing and a CLI that quietly stops offering next steps.
    """
    nouns = {noun for _kind, noun in HINTS}
    assert nouns == {NOTE_NOUN, SETTING_NOUN, CONFIG_NOUN}


def test_the_kind_and_not_the_row_count_chooses_the_template_set() -> None:
    """A collection of exactly one note is still a collection — `Kind`'s own docstring — so it gets
    the list's templates and not the entity's, and vice versa for a `note get`."""
    assert help_lines(note_collection(GROCERIES)) != help_lines(note_entity(GROCERIES))
    assert (Kind.COLLECTION, NOTE_NOUN) in HINTS
    assert (Kind.ENTITY, NOTE_NOUN) in HINTS


def test_projection_does_not_change_the_hints(notes: Payload) -> None:
    """``--fields`` narrows records and columns; ``kind`` and ``noun`` survive `narrowed_to`, so a
    narrowed read offers the same next steps. A projection that changed the advice would mean the
    advice was derived from the columns on screen rather than from what the result *is*."""
    assert help_lines(notes.narrowed_to(["ref"])) == help_lines(notes)


def test_a_hint_is_one_line_per_template_under_one_marker(notes: Payload) -> None:
    """``help: `` per line, so ``kaya note list | grep '^help: '`` is the whole of "what next".

    A heading over an indented block would make the answer require state across lines, which is the
    thing the tab-separated error row is also designed to avoid.
    """
    block = help_block(notes)
    assert block is not None
    assert block.splitlines() == [f"{HELP_PREFIX}{line}" for line in help_lines(notes)]


def test_a_hint_defaults_to_not_addressing_a_row() -> None:
    """``addresses_a_row`` is opt-in, so a template added without thinking about the zero state is
    offered there rather than silently dropped. Being offered when it does not apply is visible in
    a demo; being dropped when it does is not."""
    assert Hint("kaya note create <title>").addresses_a_row is False
