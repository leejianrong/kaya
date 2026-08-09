"""``text_limit`` (KAN-547): what it cuts, what it refuses to cut, and what the hint says.

This file is the other half of what `test_passthrough_is_a_no_op.py` used to say, and that file is
now gone. V2a pinned both of ``render``'s shaping parameters as no-ops precisely so their arrival
would be a diff somebody could date; KAN-546 spent the ``fields`` half into `test_projection.py`,
this card spends the ``text_limit`` half here, and a file named for a pass-through with nothing left
passing through would be a lie the next reader believes. Its two orphans moved to the files that
were already about them: ``render`` refusing a raw ``dict`` is in `test_shaping_order.py` with the
rest of the type chain, and "every format renders an empty payload" is in `test_serialization.py`.

**Three claims are worth more than the rest and each is stated on its own.**

- *Under-limit output is byte-identical.* ADR 0005 says that property is what kept pandan's V45 to
  two rewritten assertions where V44 needed forty. Here it is stronger than byte-identity: an
  under-limit payload comes back as **the same object**, so the pin in `test_human_row_is_pinned.py`
  — untouched by this card, deliberately — is a consequence rather than a coincidence.
- *The total is the length before the cut.* The easy bug is reporting what is left, which is a
  number the reader can already see, and it is `test_the_hint_reports_the_length_before_the_cut`
  and `test_the_total_is_not_the_truncated_length` that would catch it.
- *Only allow-listed fields are touched.* SLICES marks this **[mutate]**. A ``next_cursor`` and a
  URL are the two failures ADR 0005 names by name, so they are the payload the guard is built on.

What is **not** here is the byte-identity literal itself. That is `test_human_row_is_pinned.py`, and
a pin restated by the slice it exists to constrain is not a pin.
"""

import json

import pytest
from conftest import GROCERIES, note_collection, note_entity
from toon_decode import decode as decode_toon

from kaya_client import DEFAULT_TEXT_LIMIT, Payload, render, truncate
from kaya_client.truncation import FULL_SPELLING, HINT_SEPARATOR, hint, truncate_text

LONG = "x" * 1200
"""Comfortably over the default, and one character repeated so a slice is checkable by length."""


def prose_payload(**over: object) -> Payload:
    """A one-note entity whose ``body`` is ``LONG`` unless a test says otherwise."""
    return note_entity({**GROCERIES, "body": LONG, **over})


# ----------------------------------------------------------------- the cut and the total


def test_a_long_body_is_cut_to_the_limit() -> None:
    """The prose stops at ``text_limit`` characters. The hint is *extra*, not part of the budget.

    SLICES §V2b says over-limit text "truncates at the limit", and the limit bounds the *value* the
    API returned rather than the bytes on screen. A hint counted inside the budget would make the
    amount of prose a caller gets depend on how long the note was, which is the opposite of what a
    limit is for.
    """
    rendered = render(prose_payload(), text_limit=100)
    assert isinstance(rendered, str)

    body = rendered.split("\n\n", 1)[1]
    text, marker = body.split(HINT_SEPARATOR)
    assert text == "x" * 100
    assert marker == hint(1200, "body")


def test_the_prefix_is_the_original_verbatim() -> None:
    """No stripping, no ellipsis substituted into the prose, no re-wrapping.

    The strongest simple statement of what a cut is: ``value[:limit]`` is the original's first
    ``limit`` characters and nothing else, so a caller who wants the leading text back can slice for
    it. A trailing space quietly dropped would make that false in a way no eye catches in review.
    """
    body = "a b  \n\tc" + "z" * 50
    cut = truncate_text(body, 8, "body")

    assert cut.startswith(body[:8])
    assert cut[:8] == "a b  \n\tc"


def test_the_hint_reports_the_length_before_the_cut() -> None:
    """"A **true** total" (ADR 0005 §contract 6), which is the whole reason records arrive whole."""
    rendered = render(prose_payload(), text_limit=100)
    assert isinstance(rendered, str)

    assert "(truncated, 1200 chars total" in rendered


def test_the_total_is_not_the_truncated_length() -> None:
    """Stated as its own negative, because the wrong number is the convenient one.

    A hint built from the value it is attached to reports ``len(text[:limit])`` — always the limit,
    always self-consistent, and useless: it tells the reader the number they typed. Asserted at
    three limits so a hint that happened to agree at one cannot pass.
    """
    for limit in (50, 100, 499):
        assert hint(len(LONG), "body") in str(render(prose_payload(), text_limit=limit))
        cut = str(render(prose_payload(), text_limit=limit))
        assert f"(truncated, {limit} chars total" not in cut


def test_the_hint_names_the_field_it_is_about() -> None:
    """Not hard-coded to ``body``: the allow-list is a set, and KAN-566 will add to it."""
    assert hint(9, "summary_text") == (
        f"(truncated, 9 chars total — use {FULL_SPELLING} to see complete summary_text)"
    )


def test_the_hint_matches_the_slices_demo_line() -> None:
    """SLICES §V2b's demo is an acceptance criterion, so its wording is pinned as a literal.

    Written out rather than rebuilt from the same f-string that produced it: a test that formats its
    own expectation agrees with any typo it shares with the implementation.
    """
    assert hint(2847, "body") == (
        "(truncated, 2847 chars total — use --full to see complete body)"
    )


# --------------------------------------------------------------- under the limit, untouched


@pytest.mark.parametrize("fmt", ["human", "json", "toon", "data"])
def test_under_limit_output_is_byte_identical(fmt: str) -> None:
    """ADR 0005's headline property, over every format rather than only the one with a pin."""
    short = note_entity({**GROCERIES, "body": "milk\neggs"})

    assert render(short, text_limit=DEFAULT_TEXT_LIMIT, fmt=fmt) == render(
        short, text_limit=0, fmt=fmt
    )


def test_an_under_limit_payload_comes_back_as_the_same_object(notes: Payload) -> None:
    """Identity, not equality — the assertion that replaces the retired no-op file's ``is`` check.

    An equal-but-rebuilt payload would satisfy byte-identity while hiding that every record had been
    copied on every read. More importantly it is what makes the byte-identity claim structural: a
    payload the truncator declined to touch is *the payload*, so nothing downstream can have been
    handed a subtly different one.
    """
    assert truncate(notes, DEFAULT_TEXT_LIMIT) is notes


def test_a_value_of_exactly_the_limit_is_not_truncated() -> None:
    """Off-by-one, stated. A value of ``limit`` characters is not over the limit, so it is not cut,
    so it carries no hint — and a note that grows one character later starts carrying one."""
    exact = note_entity({**GROCERIES, "body": "y" * 500})

    assert "truncated" not in str(render(exact, text_limit=500))
    assert "truncated" in str(render(note_entity({**GROCERIES, "body": "y" * 501}), text_limit=500))


def test_the_default_limit_is_five_hundred() -> None:
    """SLICES §V2b and ADR 0005 §contract 6. Pinned by literal value, like the exit table."""
    assert DEFAULT_TEXT_LIMIT == 500
    assert "truncated" in str(render(prose_payload()))


# ------------------------------------------------------------------------ --full is 0


@pytest.mark.parametrize("fmt", ["human", "json", "toon", "data"])
def test_zero_disables_truncation_entirely(fmt: str) -> None:
    """ADR 0005's ``--full``, which has exactly this one spelling at the seam.

    Asserted per format because "restores the whole body **everywhere it applies**" is SLICES'
    wording, and a disable implemented in the human serializer would pass on one of the four.
    """
    rendered = render(prose_payload(), text_limit=0, fmt=fmt)
    text = json.dumps(rendered) if isinstance(rendered, dict) else rendered

    assert LONG in text
    assert "truncated" not in text


def test_full_recovers_the_body_a_default_read_cut() -> None:
    """The two invocations side by side, which is what a person actually does."""
    payload = prose_payload()

    assert len(str(render(payload, text_limit=0))) > len(str(render(payload)))
    assert str(render(payload, fmt="data")["body"]).startswith("x" * 500)
    assert render(payload, text_limit=0, fmt="data")["body"] == LONG


# ------------------------------------------------------- the allow-list, never a heuristic


def cursored() -> Payload:
    """A collection carrying the two values ADR 0005 names: a pagination cursor and a URL.

    Both are long, neither is prose, and neither is in ``prose_fields``. This is the payload the
    SLICES **[mutate]** line is about — "a long ``next_cursor`` and a long URL pass through intact".
    """
    return Payload.collection(
        noun="note",
        envelope_key="notes",
        records=[
            {
                "ref": "NOTE-1",
                "next_cursor": "c" * 900,
                "url": "https://kaya.example/notes/" + "u" * 900,
                "body": LONG,
            }
        ],
        columns=("ref", "next_cursor", "url"),
        prose_fields=frozenset({"body"}),
    )


def test_a_long_cursor_passes_through_intact() -> None:
    """The failure ADR 0005 names first: "a blanket rule eventually cuts a ``next_cursor`` and
    silently breaks pagination". Silently is the word that matters — the caller sees a cursor."""
    record = render(cursored(), fmt="data")["notes"][0]

    assert record["next_cursor"] == "c" * 900
    assert "truncated" not in record["next_cursor"]


def test_a_long_url_passes_through_intact() -> None:
    """ADR 0005's second named failure: "or mangles a URL"."""
    record = render(cursored(), fmt="data")["notes"][0]

    assert record["url"].endswith("u" * 900)


def test_the_allow_listed_field_in_the_same_record_is_still_cut() -> None:
    """The guard above would pass trivially if truncation had simply stopped working.

    So the same record is asserted from both sides: ``body`` is in ``prose_fields`` and is cut,
    ``next_cursor`` and ``url`` are not and are not. A mutation that widens the rule reddens the two
    tests above; one that narrows it to nothing reddens this.
    """
    record = render(cursored(), fmt="data")["notes"][0]

    assert record["body"].startswith("x" * 500)
    assert "truncated" in record["body"]


def test_a_payload_with_no_prose_fields_is_returned_unchanged() -> None:
    """No allow-list, nothing to truncate — not "fall back to any long string"."""
    bare = Payload.collection(
        noun="note",
        envelope_key="notes",
        records=[{"ref": "NOTE-1", "title": "x" * 900}],
        columns=("ref", "title"),
    )
    assert truncate(bare, 10) is bare


def test_a_non_string_in_an_allow_listed_field_is_left_alone() -> None:
    """``None`` is what a sparse row carries, and it is not text with a length worth reporting."""
    payload = note_entity({**GROCERIES, "body": None})

    assert render(payload, text_limit=1, fmt="data")["body"] is None


# ------------------------------------------------------- a truncated value is still a string


def test_no_key_is_added_removed_or_retyped() -> None:
    """ADR 0005 §contract 6's second clause, asserted on the record rather than on a rendering.

    A serializer could hide any of the three — a dropped key looks like a sparse row, an added one
    looks like an API change — so this reads the shaped dict directly. The value's *type* is checked
    too, because the tempting richer design is ``{"text": …, "total": …}``, which would carry the
    total honestly and break every consumer that treats ``body`` as a string.
    """
    before = render(prose_payload(), text_limit=0, fmt="data")
    after = render(prose_payload(), text_limit=50, fmt="data")

    assert list(after) == list(before)
    assert {key: type(value) for key, value in after.items()} == {
        key: type(value) for key, value in before.items()
    }
    assert isinstance(after["body"], str)


def test_the_key_order_of_a_truncated_record_is_unchanged() -> None:
    """Rebuilding a record is where key order goes missing, and `json` output shows it."""
    rendered = render(prose_payload(), text_limit=50, fmt="json")
    assert isinstance(rendered, str)

    assert list(json.loads(rendered)) == list(render(prose_payload(), text_limit=0, fmt="data"))


def test_the_original_payload_is_not_edited(notes: Payload) -> None:
    """``--full`` is satisfiable only while the complete records survive (ADR 0004)."""
    payload = prose_payload()
    render(payload, text_limit=10)

    assert payload.record["body"] == LONG


# ----------------------------------------------------------------- multi-byte characters

# The guarantee is **code points**, not grapheme clusters — see `truncation`'s module docstring for
# why the stronger claim is not made and what it would cost. These tests state both halves: the cut
# never produces an invalid string, and a cluster genuinely can be split.

MULTIBYTE = "日本語のノート" * 200
"""Three-byte characters, so a cut by *bytes* would produce a decode error rather than a short
string. Python slices by code point, so this passes by construction — which is the point: the test
is here to fail if anybody ever reaches for ``value.encode()[:limit]``."""


def test_a_cut_never_splits_a_character() -> None:
    """SLICES §V2b's unit line. Round-tripped through UTF-8, which is where a split would show."""
    cut = truncate_text(MULTIBYTE, 501, "body")
    text = cut.split(HINT_SEPARATOR)[0]

    assert len(text) == 501
    assert text == MULTIBYTE[:501]
    assert text.encode("utf-8").decode("utf-8") == text
    assert "�" not in text


def test_the_limit_counts_characters_and_not_bytes() -> None:
    """500 CJK characters is 1,500 bytes, and the caller asked for 500 of something.

    ``text_limit`` and the hint's total are the same unit — code points — so a reader comparing
    "500" against "1400 chars total" is comparing like with like.
    """
    cut = truncate_text(MULTIBYTE, 500, "body")

    assert len(cut.split(HINT_SEPARATOR)[0]) == 500
    assert f"{len(MULTIBYTE)} chars total" in cut


@pytest.mark.parametrize(
    ("cluster", "description"),
    [
        ("👩‍💻", "a ZWJ sequence"),
        ("👍\U0001f3fd", "a skin-tone modifier"),
        ("é", "a combining acute accent"),
    ],
)
def test_a_grapheme_cluster_may_split_and_the_pieces_are_still_valid(
    cluster: str, description: str
) -> None:
    """**The honest half.** A cut inside a cluster is possible and this is what it looks like.

    Written as an assertion rather than left undocumented because the alternative — claiming
    clusters — would need a UAX #29 table, and ``kaya-client`` has exactly one runtime dependency
    (SLICES §V2a). What is guaranteed is what is asserted here: every piece is a whole code point,
    the string encodes, and nothing becomes a replacement character. The rendering may look odd; it
    is never invalid.
    """
    text = "a" * 10 + cluster + "b" * 600
    cut = truncate_text(text, 11, "body")
    prefix = cut.split(HINT_SEPARATOR)[0]

    assert prefix == text[:11]
    assert prefix.encode("utf-8").decode("utf-8") == prefix
    assert "�" not in prefix
    assert prefix[10] == cluster[0], description


def test_multibyte_prose_survives_the_structured_formats() -> None:
    """A cut that produced a lone surrogate would fail here rather than in a human's terminal."""
    payload = note_entity({**GROCERIES, "body": MULTIBYTE})
    as_json = render(payload, text_limit=100, fmt="json")
    assert isinstance(as_json, str)

    assert json.loads(as_json)["body"] == render(payload, text_limit=100, fmt="data")["body"]
    assert decode_toon(str(render(payload, text_limit=100, fmt="toon"))) == json.loads(as_json)


# ------------------------------------------------------------------ the two rendering paths


def test_a_truncated_entity_puts_the_hint_after_the_prose() -> None:
    """`note get`'s layout: the label block, a blank line, the prose, a blank line, the hint.

    The block above the prose is asserted unchanged because that is what "the hint appends without
    disturbing a byte of the block above it" means, and it is the reason `serialization._entity`
    prints prose unlabelled and last.
    """
    lines = str(render(prose_payload(), text_limit=20)).splitlines()

    assert lines[0] == "ref         NOTE-12"
    assert lines[-1] == hint(1200, "body")
    assert lines[-3] == "x" * 20
    assert lines[-2] == ""


def test_a_truncated_cell_is_one_line_and_the_grid_holds() -> None:
    """The other path, reachable since KAN-546 made ``body`` selectable on a list.

    `serialization._cell` collapses whitespace, so the same value that renders as a block under
    `get` renders as one line here — no branch in either module, and the columns stay aligned. A
    hint that broke the grid would be a bug in a table nobody looks at closely.

    The table is separated from KAN-548's summary footer before the rows are counted, because "the
    hint stayed on one line" is a claim about the *rows* and would otherwise be broken by a line
    that has nothing to do with truncation.
    """
    payload = note_collection(
        {**GROCERIES, "body": "m" * 30}, {"ref": "NOTE-3", "title": "Short", "body": "hi"}
    )
    table, footer = str(render(payload, fields=["ref", "body"], text_limit=10)).split("\n\n")
    rows = table.splitlines()

    assert len(rows) == 2
    assert rows[0] == f"NOTE-12  {'m' * 10} {hint(30, 'body')}"
    assert rows[1] == "NOTE-3   hi"
    assert footer == "2 notes"


def test_the_hint_reaches_every_structured_format() -> None:
    """The in-band decision, cashed: an agent on ``--format json`` sees the true total too.

    Under a human-only hint this assertion is the one that fails, and with it the ability of a
    consumer to tell a 500-char note from a truncated 3,000-char one — which is the audience "a true
    total" was written for.
    """
    as_data = render(prose_payload(), text_limit=50, fmt="data")
    as_json = str(render(prose_payload(), text_limit=50, fmt="json"))
    as_toon = str(render(prose_payload(), text_limit=50, fmt="toon"))

    assert as_data["body"].endswith(hint(1200, "body"))
    assert json.loads(as_json)["body"] == as_data["body"]
    assert decode_toon(as_toon)["body"] == as_data["body"]


def test_an_empty_body_is_untouched_and_gains_no_hint() -> None:
    """``NoteCreate`` defaults ``body`` to ``""``, so this is the common note, not an edge case."""
    rendered = str(render(note_entity({**GROCERIES, "body": ""}), text_limit=1))

    assert "truncated" not in rendered
    assert not rendered.endswith("\n")


# ------------------------------------------------------------------ what the seam refuses


@pytest.mark.parametrize("text_limit", [-1, -500])
def test_a_negative_text_limit_is_refused(notes: Payload, text_limit: int) -> None:
    """``0`` already spells "disabled" (ADR 0005's ``--full``), so a negative is a caller bug."""
    with pytest.raises(ValueError, match="0 disables"):
        render(notes, text_limit=text_limit)


@pytest.mark.parametrize("text_limit", ["500", 1.5, True, None])
def test_a_text_limit_that_is_not_a_character_count_is_refused(
    notes: Payload, text_limit: object
) -> None:
    """``True`` is in there deliberately: it is an ``int`` and would silently mean one char."""
    with pytest.raises(TypeError):
        render(notes, text_limit=text_limit)  # type: ignore[arg-type]
