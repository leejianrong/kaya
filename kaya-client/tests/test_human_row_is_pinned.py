"""The byte-identity pin. SLICES §V2a marks it **[mutate]**, and it is the point of the slice.

ADR 0005's sequencing rule buys one thing above all: "under-limit output stays byte-identical by
construction", which is what kept pandan's V45 to two rewritten assertions where V44 needed forty.
A claim like that is only worth anything if something checks it, so the default human row is written
out here as a literal — every space, in a triple-quoted block that shows the alignment — rather than
rebuilt from the same code that produced it. A test that formats its own expectation agrees with any
bug it shares with the implementation.

**Two cards have been allowed to move these literals, and this docstring is the record of which
bytes each moved.** V2a wrote here that a later slice reddening this file while ``--fields`` was
omitted would be "the guard working, not a stale test to update", and that sentence did its job
twice before anything moved at all: KAN-546 (`--fields`) and KAN-547 (truncation) both landed with
this file untouched and green, which was their evidence.

**KAN-548 (the aggregate) changed the collection literals, and it was the first card allowed to.**
ADR 0005 §contract 5 requires a trailing summary line on every human *collection*, so the bytes
below a `note list` genuinely moved and there is no version of the contract under which they did
not:

- **every collection literal gained ``\\n\\n<count> <noun>``** — a blank line and a footer. Nothing
  inside the table changed: the columns, the two-space gap, the widths taken from the returned rows,
  the absence of a header and the absence of trailing whitespace are all still asserted, still
  byte-for-byte, and `test_no_row_carries_trailing_whitespace` still runs over every line.
- **``SINGLE_NOTE`` did not change**, because a summary describes a returned *set*.
- **the zero state did not change.** ``no notes`` *is* the rendering of ``count: 0``.

**KAN-550 (``help[]``) moved every literal in the file, and it is the second and last card of V2b
allowed to.** ADR 0005 §contract 8 requires results to "carry ``help[]`` next-step templates", and
SLICES §V2b requires them suppressed under structured formats — so `human`, and only `human`, gained
a trailing block. Exactly what moved:

- **every collection literal gained ``\\n\\nhelp: kaya note get <ref>\\nhelp: kaya note create
  <title>``**, beneath the summary footer, separated from it by the same blank line that separates
  the footer from the table.
- **``SINGLE_NOTE`` gained ``\\n\\nhelp: kaya note edit <ref> --body-file <path>``**, and this is
  the first card to touch it. That is *not* the aggregate leaking onto an entity, which is what
  KAN-548 left this file asserting: `test_aggregates.py`'s ``test_a_single_note_gets_no_summary`` is
  untouched and still proves one note gets no summary. A help template is keyed on ``kind`` and
  ``noun``, and a single note has a next step even though it is not a returned set.
- **the zero state gained exactly one line**, ``help: kaya note create <title>`` and *not* the `get`
  template, because `note get <ref>` addresses a row and an empty list has none. ``no notes`` itself
  is unchanged and is still the whole of the first block.
- **nothing inside a table, a label block or a note's prose moved.** Every column, every gap, every
  width, the absence of a header and the absence of trailing whitespace are asserted below exactly
  as before; the hint block is separated from all of it by a blank line rather than woven into it.

**What this file pins is still the contract for the rest of V2b.** KAN-549's content-first bare
invocation lands next; if it changes one byte of the literals below while ``--fields`` is omitted
and the text is under the limit, this file goes red and that is still the guard doing its job
(SLICES §V2b repeats the pin as "this is V2a's pin doing its job"). A pin quietly edited is a pin
destroyed, which is why the paragraphs above exist at all.
"""

import pytest
from conftest import GROCERIES, READING_LIST, note_collection, note_entity

from kaya_client import Payload, render

LIST_HELP = "help: kaya note get <ref>\nhelp: kaya note create <title>"
"""ADR 0005 §contract 8's block for a `note list`, spelled out once because five literals below end
in it. Two lines, each a **template**: ``<ref>`` and ``<title>`` are the placeholders the contract
requires be left unfilled, and neither is any value from the payload above them.

That the block is under a blank line and each line under its own ``help: `` marker is the same
argument `LIST_ROWS`' footer makes — a trailing block must not be readable as another row. That
every one of these parses as a real command is `kaya-cli/tests/test_help_templates.py`'s, because
the parser lives in that package."""

ENTITY_HELP = "help: kaya note edit <ref> --body-file <path>"
"""And for one note: the single template SLICES §V2b names verbatim."""

LIST_ROWS = (
    "NOTE-12  Groceries       home/groceries.md\n"  #
    "NOTE-3   A reading list\n"
    "\n"
    "2 notes\n"
    "\n" + LIST_HELP
)
"""Two notes, columns ``ref``/``title``/``path``, two spaces between columns, widths from the rows
actually returned, no header, and **no trailing whitespace** — the second note's ``path`` is empty
and the line stops at the title rather than carrying seventeen spaces nobody can see. Trailing
whitespace is the classic thing a later refactor adds silently and a diff review misses.

Then a blank line and ADR 0005 §contract 5's footer, added by KAN-548. The blank line is why it
reads as a footer rather than as a third note, and it is the same separation `SINGLE_NOTE` already
used between a note's labels and its prose. The count describes **the rows above it** and nothing
else; `test_aggregates.py` is where that is asserted against a corpus it is a slice of.

Then a blank line and §contract 8's templates, added by KAN-550 — the third block, joined by the
second use of the same separator. Under `--format json` or `toon` this last block does not exist at
all; `test_hints.py` is the witness for that."""

SINGLE_NOTE = (
    "ref         NOTE-12\n"
    "title       Groceries\n"
    "path        home/groceries.md\n"
    "created_at  2026-08-01T09:15:00+00:00\n"
    "updated_at  2026-08-09T11:02:33.123456+00:00\n"
    "\n"
    "milk\n"
    "eggs\n"
    "\n" + ENTITY_HELP
)
"""One note: a label block padded to the widest label, then a blank line, then the prose unlabelled.
``body`` keeps its own newlines — the collapse that keeps a table aligned applies to table cells
only, and mangling prose would be the truncator's job done badly by the formatter.

**Unchanged by KAN-548, and that was an assertion rather than an omission**: an entity has no
summary because one note is not a returned set, and ``count: 1`` here would be a key identical on
every `note get` ever made. That is still true — there is no ``1 note`` line below.

**Changed by KAN-550, which is a different contract row.** A single note *does* have a next step,
so the prose is followed by a blank line and `ENTITY_HELP`. If a later card adds a count here, that
is still the aggregate bug KAN-548 wrote this paragraph about."""


def test_the_default_note_list_row_is_byte_identical(notes: Payload) -> None:
    assert render(notes) == LIST_ROWS


def test_the_default_single_note_is_byte_identical(note: Payload) -> None:
    assert render(note) == SINGLE_NOTE


def test_human_is_the_default_format(notes: Payload) -> None:
    """``fmt`` defaults to ``human``, so the pin above covers the bare call an adapter makes."""
    assert render(notes) == render(notes, fmt="human")


def test_no_row_carries_trailing_whitespace(notes: Payload) -> None:
    """Stated separately from the literal, because it is the property, not the example.

    A note whose last column is empty must not pad. Asserted over every line so a third column
    added in V2b cannot reintroduce it in a row the literal above does not happen to cover.
    """
    rendered = render(notes)
    assert isinstance(rendered, str)
    assert all(line == line.rstrip() for line in rendered.splitlines())


def test_column_widths_come_from_the_returned_rows_only() -> None:
    """Widths are per-render, so a narrow result is not padded to some other result's width.

    This is the same rule ADR 0005 §contract 5 states for aggregates — describe the returned set,
    not the corpus — applied to layout, and it is why the pin above is stable: it depends on the
    two notes in the payload and on nothing else. Since KAN-548 the footer says the same thing in
    words, which is why this one-row render ends ``1 note``.
    """
    expected = f"NOTE-3  A reading list\n\n1 note\n\n{LIST_HELP}"
    assert render(note_collection(READING_LIST)) == expected


def test_an_empty_result_is_a_definitive_zero_state() -> None:
    """Not an empty string: that is indistinguishable from a crashed pipe or a swallowed error.

    **Unchanged by KAN-548**: ``no notes`` is what ``count: 0`` renders as, so no ``0 notes`` footer
    goes under it. SLICES §V2b asks an empty result to "still print a definitive zero state", and
    one definitive sentence is more definitive than two.

    **KAN-550 put one hint under it, and dropped the other.** An empty list is where a next step is
    worth most — the sentence answers "what have I got" and nothing about what to do — but
    ``note get <ref>`` addresses one of the rows above it and there are none, so only
    ``note create <title>`` is offered. The zero state itself is still the exact sentence, still
    alone in its block.
    """
    assert render(note_collection()) == "no notes\n\nhelp: kaya note create <title>"


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("a\nb", f"NOTE-12  a b  home/groceries.md\n\n1 note\n\n{LIST_HELP}"),
        ("a\tb", f"NOTE-12  a b  home/groceries.md\n\n1 note\n\n{LIST_HELP}"),
    ],
)
def test_a_newline_in_a_cell_never_breaks_the_grid(title: str, expected: str) -> None:
    """A multi-line value in a table cell would shift every row below it one column left.

    Collapsing is layout and applies to cells only. `test_the_default_single_note_is_byte_identical`
    is the other half: prose printed outside the grid keeps its newlines.
    """
    assert render(note_collection({**GROCERIES, "title": title})) == expected


def test_a_missing_column_renders_blank_rather_than_raising() -> None:
    """A column the API stopped sending is a hole in a row, not a traceback.

    The default columns are named by the client, so they can fall out of step with the API across a
    deploy. A `KeyError` here would take down `note list` entirely for a field nobody was reading.
    """
    thin = {key: value for key, value in READING_LIST.items() if key != "path"}
    expected = f"NOTE-3  A reading list\n\n1 note\n\n{LIST_HELP}"
    assert render(note_collection(thin)) == expected


def test_an_entity_with_no_prose_has_no_trailing_blank_line() -> None:
    """A note with an empty body renders the label block and stops.

    ``""`` is a legal body — `NoteCreate` defaults it — so this is the common shape of a
    freshly-created note, not an edge case.

    Since KAN-550 "stops" means "stops and then offers a next step": the assertion is that the
    label block runs straight into the hint block with **one** blank line between them, i.e. that
    the absent prose contributes no block of its own rather than an empty one. An empty prose block
    would show up here as two blank lines, which is exactly the invisible-in-review defect this
    test was written for.
    """
    rendered = render(note_entity(READING_LIST))
    assert isinstance(rendered, str)

    labels, help_block = rendered.split("\n\n")
    assert labels.splitlines()[-1].startswith("updated_at")
    assert help_block == ENTITY_HELP
    assert not rendered.endswith("\n")
