"""KAN-561: the ``[[...]]`` parser, with no database and no framework.

Every case here is pure — a string in, a list of `WikilinkRef` out — because `find_wikilinks` never
does anything else (ADR 0003: nothing in kaya may block on pandan, and this module makes no network
call at all). See `app/wikilinks.py`'s module docstring for the argument behind each design
decision; this file is the proof.
"""

import dataclasses

import pytest

from app.wikilinks import WikilinkRef, find_wikilinks


def spanned(body: str, raw: str, kind: str, number: int) -> WikilinkRef:
    """Build the `WikilinkRef` a caller should expect for `raw`'s (only) occurrence in `body`,
    computing the span from `str.index` rather than by counting characters by hand — a hand count
    is exactly the kind of off-by-one this file should not be trusted to get right silently."""
    start = body.index(raw)
    return WikilinkRef(kind=kind, number=number, raw=raw, start=start, end=start + len(raw))


# --- The straightforward cases ------------------------------------------------------------------


def test_no_links_is_an_empty_list() -> None:
    assert find_wikilinks("just some prose, no brackets here") == []


def test_a_single_link() -> None:
    body = "see [[KAN-561]] for context"
    refs = find_wikilinks(body)

    assert refs == [spanned(body, "[[KAN-561]]", "KAN", 561)]


def test_an_epic_link() -> None:
    body = "part of [[EPIC-45]]"
    refs = find_wikilinks(body)

    assert refs == [spanned(body, "[[EPIC-45]]", "EPIC", 45)]


def test_multiple_links_in_one_body() -> None:
    refs = find_wikilinks("blocked by [[KAN-1]], see also [[KAN-2]] and [[EPIC-3]]")

    assert [r.canonical for r in refs] == ["KAN-1", "KAN-2", "EPIC-3"]


def test_a_link_at_the_very_start_of_the_body() -> None:
    body = "[[KAN-1]] kicks off the sentence"
    refs = find_wikilinks(body)

    assert refs[0] == spanned(body, "[[KAN-1]]", "KAN", 1)
    assert refs[0].start == 0


def test_a_link_at_the_very_end_of_the_body() -> None:
    body = "the sentence ends with [[KAN-1]]"
    refs = find_wikilinks(body)

    assert refs[0].end == len(body)


def test_adjacent_links_with_no_separator() -> None:
    refs = find_wikilinks("[[KAN-1]][[KAN-2]]")

    assert [r.canonical for r in refs] == ["KAN-1", "KAN-2"]


def test_spans_are_offsets_into_the_given_text() -> None:
    body = "before [[KAN-42]] after"
    ref = find_wikilinks(body)[0]

    assert body[ref.start : ref.end] == ref.raw == "[[KAN-42]]"


# --- Prefix vocabulary: KAN- and EPIC-, never PAN- ----------------------------------------------


def test_pan_is_not_a_recognised_prefix() -> None:
    """The whole point of the card: pandan ADR 0018 kept `KAN-` un-rebranded, so a parser matching
    `PAN-` would match a reference that has never existed."""
    assert find_wikilinks("[[PAN-123]]") == []


def test_other_plausible_prefixes_are_also_refused() -> None:
    for body in ["[[NOTE-1]]", "[[TICKET-1]]", "[[JIRA-1]]", "[[KANBAN-1]]"]:
        assert find_wikilinks(body) == [], body


def test_kan_with_no_digits_is_not_a_link() -> None:
    assert find_wikilinks("[[KAN-]]") == []


def test_kan_with_a_trailing_suffix_is_not_a_link() -> None:
    """Mirrors `app/api/refs.py`'s `NOTE-12-old` case: greedy digits, then only whitespace or the
    closing brackets are allowed — a trailing word is neither."""
    assert find_wikilinks("[[KAN-123-old]]") == []


# --- Case sensitivity and whitespace inside the brackets ----------------------------------------


def test_the_prefix_is_case_insensitive() -> None:
    """Mirrors `NOTE_REF_PATTERN`'s choice in `app/api/refs.py`: a human typing a reference
    mid-sentence gets the same leniency kaya already grants its own `NOTE-` refs."""
    for body in ["[[kan-561]]", "[[Kan-561]]", "[[KAN-561]]", "[[kAn-561]]"]:
        refs = find_wikilinks(body)
        assert len(refs) == 1, body
        assert refs[0].kind == "KAN", body
        assert refs[0].number == 561, body


def test_a_lowercase_epic_is_recognised_too() -> None:
    body = "[[epic-9]]"
    refs = find_wikilinks(body)

    assert refs == [spanned(body, "[[epic-9]]", "EPIC", 9)]


def test_whitespace_inside_the_brackets_is_tolerated() -> None:
    body = "[[ KAN-123 ]]"
    refs = find_wikilinks(body)

    assert refs == [spanned(body, "[[ KAN-123 ]]", "KAN", 123)]


def test_asymmetric_whitespace_inside_the_brackets() -> None:
    refs = find_wikilinks("[[KAN-123 ]] and [[ KAN-456]]")

    assert [r.canonical for r in refs] == ["KAN-123", "KAN-456"]


def test_a_newline_inside_the_brackets_is_not_tolerated() -> None:
    """A wikilink is written on one line; letting it span a newline would make `[[KAN-\\n123]]` a
    link, a shape no editor produces by hand."""
    assert find_wikilinks("[[KAN-\n123]]") == []


def test_a_non_ascii_digit_is_not_a_link() -> None:
    """Same reasoning as `app/api/refs.py`'s non-ascii-digit case: without `re.ASCII`, `\\d` matches
    Unicode decimal digits, and `int()` converts them, minting a ref number nothing else agrees
    with."""
    assert find_wikilinks("[[KAN-٣]]") == []


# --- Unclosed `[[` --------------------------------------------------------------------------------


def test_an_unclosed_bracket_is_not_a_link() -> None:
    assert find_wikilinks("see [[KAN-123 for details") == []


def test_an_unclosed_bracket_with_a_well_formed_link_later_in_the_body() -> None:
    """The unclosed one contributes nothing; a later well-formed one is still found."""
    refs = find_wikilinks("dangling [[KAN-1 and then a real one [[KAN-2]]")

    assert [r.canonical for r in refs] == ["KAN-2"]


def test_only_one_closing_bracket_is_also_not_a_link() -> None:
    assert find_wikilinks("[[KAN-123]") == []


# --- Nesting: the innermost well-formed pair wins, the malformed outer one is refused -----------


def test_nesting_matches_only_the_innermost_pair() -> None:
    """`[[KAN-1 [[KAN-2]] ]]`: the outer span is not well-formed (there's a stray `[[KAN-2]]` where
    only whitespace-then-`]]` may appear), so scanning left to right finds nothing until it reaches
    the inner pair. See the module docstring for the full argument."""
    refs = find_wikilinks("[[KAN-1 [[KAN-2]] ]]")

    assert [r.canonical for r in refs] == ["KAN-2"]


def test_nesting_the_other_way_round() -> None:
    refs = find_wikilinks("[[EPIC-1 [[KAN-2]] more text]]")

    assert [r.canonical for r in refs] == ["KAN-2"]


def test_doubled_opening_brackets_do_not_confuse_the_scan() -> None:
    refs = find_wikilinks("[[[[KAN-1]]]]")

    assert [r.canonical for r in refs] == ["KAN-1"]


# --- A link inside a code fence is not a link -----------------------------------------------------


def test_a_link_inside_a_fenced_code_block_is_ignored() -> None:
    body = "\n".join(
        [
            "before [[KAN-1]]",
            "```",
            "inside the fence: [[KAN-999]]",
            "```",
            "after [[KAN-2]]",
        ]
    )

    refs = find_wikilinks(body)

    assert [r.canonical for r in refs] == ["KAN-1", "KAN-2"]


def test_a_fence_with_a_language_annotation() -> None:
    body = "\n".join(
        [
            "```python",
            "# see [[KAN-1]] in a comment",
            "```",
        ]
    )

    assert find_wikilinks(body) == []


def test_an_unterminated_fence_swallows_everything_after_it() -> None:
    """No closing delimiter before the body ends: CommonMark treats that as a code block running to
    the end of the document, and so does this parser."""
    body = "before [[KAN-1]]\n```\nnever closed [[KAN-2]]"

    refs = find_wikilinks(body)

    assert [r.canonical for r in refs] == ["KAN-1"]


def test_multiple_fences_in_one_body() -> None:
    body = "\n".join(
        [
            "[[KAN-1]]",
            "```",
            "[[KAN-2]]",
            "```",
            "[[KAN-3]]",
            "```",
            "[[KAN-4]]",
            "```",
            "[[KAN-5]]",
        ]
    )

    refs = find_wikilinks(body)

    assert [r.canonical for r in refs] == ["KAN-1", "KAN-3", "KAN-5"]


def test_an_indented_fence_inside_a_list_item() -> None:
    body = "\n".join(
        [
            "- a step",
            "  ```",
            "  [[KAN-1]]",
            "  ```",
        ]
    )

    assert find_wikilinks(body) == []


def test_a_fence_delimiter_line_itself_is_excluded_even_if_it_looked_like_a_link() -> None:
    """Contrived, but the exclusion range covers the delimiter lines themselves, not just the
    content between them — proven by putting the wikilink-looking text on the opening line."""
    body = "``` [[KAN-1]]\ncode\n```"

    assert find_wikilinks(body) == []


# --- Surrounding punctuation is never swallowed ---------------------------------------------------


def test_parentheses_around_a_link() -> None:
    body = "([[KAN-123]].)"
    refs = find_wikilinks(body)

    assert refs == [spanned(body, "[[KAN-123]]", "KAN", 123)]
    assert body[0] == "(" and body[refs[0].end] == "."


def test_quotes_and_a_trailing_comma() -> None:
    body = '"[[KAN-123]],"'
    refs = find_wikilinks(body)

    assert refs == [spanned(body, "[[KAN-123]]", "KAN", 123)]
    assert body[0] == '"' and body[refs[0].end] == ","


def test_a_link_at_the_end_of_a_sentence() -> None:
    refs = find_wikilinks("Fixed by [[KAN-561]].")

    assert refs[0].raw == "[[KAN-561]]"
    assert refs[0].end < len("Fixed by [[KAN-561]].")


def test_a_link_wrapped_in_markdown_emphasis() -> None:
    body = "**[[KAN-1]]** is blocking"
    refs = find_wikilinks(body)

    assert refs == [spanned(body, "[[KAN-1]]", "KAN", 1)]


# --- The dataclass's own surface ------------------------------------------------------------------


def test_canonical_is_the_bracket_free_uppercase_spelling() -> None:
    ref = find_wikilinks("[[ kan-7 ]]")[0]

    assert ref.canonical == "KAN-7"
    assert ref.raw == "[[ kan-7 ]]", "raw keeps the caller's own casing and whitespace"


def test_wikilink_ref_is_frozen_and_comparable() -> None:
    a = WikilinkRef(kind="KAN", number=1, raw="[[KAN-1]]", start=0, end=9)
    b = WikilinkRef(kind="KAN", number=1, raw="[[KAN-1]]", start=0, end=9)

    assert a == b
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.number = 2  # type: ignore[misc]
