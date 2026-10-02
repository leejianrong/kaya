"""KAN-1814's formatter in the fast layer: idempotence, link-edge preservation, the decline path.

The whole risk of formatting a note body is the link graph. ``note_link`` is re-derived from the
body on every save, and mdformat escapes ``[[KAN-12]]`` into ``\\[[KAN-12]\\]`` — so an unguarded
``mdformat.text`` would silently delete an edge from the graph and every backlinks panel. Every
test here that matters asserts on the *edges* ``app/wikilinks.py`` extracts, not on the prose.
"""

from pathlib import Path

import pytest

from app import markdown_format
from app.markdown_format import format_markdown
from app.wikilinks import find_note_title_links, find_wikilinks

MESSY = """---
title:   x
tags: [a,b]
---
#  Heading
* item one
* item two
  - nested

See [[KAN-12]] and [[ Some Note Title ]] and [[kan-3]] plus [[EPIC-4]] and NOTE-4.
Embeds ![[img.png]] and [[Title|alias]] and `[[inline]]`.

| a | b |
|--|--|
| [[KAN-1]] | long cell text |

```python
x   =  [[1,2]]  # [[KAN-9]]
```

<div>raw   html</div>

- [ ] todo
- [x] done

1) first
2) second
"""


def edges(text: str) -> list[tuple[str, str]]:
    return [
        *[(ref.kind, ref.canonical) for ref in find_wikilinks(text)],
        *[(link.kind, link.title) for link in find_note_title_links(text)],
    ]


def test_it_formats_markdown() -> None:
    result = format_markdown(MESSY)

    assert result.outcome == "formatted"
    assert "# Heading" in result.text
    assert "- item one" in result.text
    assert "tags: [a, b]" in result.text
    assert result.changed_lines > 0


def test_formatting_is_idempotent() -> None:
    once = format_markdown(MESSY)
    twice = format_markdown(once.text)

    assert twice.outcome == "unchanged"
    assert twice.text == once.text


def test_every_wikilink_survives_byte_for_byte() -> None:
    """The load-bearing one. A bare mdformat turns each of these into ``\\[[…]\\]``."""
    text = format_markdown(MESSY).text

    for link in ("[[KAN-12]]", "[[ Some Note Title ]]", "[[kan-3]]", "[[EPIC-4]]", "![[img.png]]"):
        assert link in text
    assert "\\[[" not in text


def test_link_edges_are_identical_before_and_after() -> None:
    assert edges(format_markdown(MESSY).text) == edges(MESSY)


def test_code_fences_are_untouched() -> None:
    assert "x   =  [[1,2]]  # [[KAN-9]]" in format_markdown(MESSY).text


def test_a_table_cell_holding_a_wikilink_pads_as_if_the_text_were_there() -> None:
    """The placeholder is the link's own width; a shorter one would pad the column differently."""
    text = format_markdown("| a | b |\n|--|--|\n| [[KAN-1]] | x |\n").text

    assert text.splitlines()[0] == "| a         | b   |"
    assert text.splitlines()[2] == "| [[KAN-1]] | x   |"


def test_many_wikilinks_do_not_collide_on_their_placeholders() -> None:
    """``…1`` is a prefix of ``…10``: more than ten links is where an unterminated token breaks."""
    body = "\n\n".join(f"link [[KAN-{n}]] and [[Title {n}]]" for n in range(1, 30))

    result = format_markdown(body)

    assert edges(result.text) == edges(body)
    assert result.text == body + "\n"


def test_a_note_that_already_contains_the_placeholder_prefix_is_still_safe() -> None:
    body = "zqwl0q is plain prose, and so is [[KAN-1]] next to zqwl1q\n"

    result = format_markdown(body)

    assert edges(result.text) == edges(body)
    assert "zqwl0q is plain prose" in result.text
    assert "[[KAN-1]]" in result.text


def test_an_escaped_backslash_before_a_wikilink_keeps_the_edge() -> None:
    body = "text \\\\[[KAN-5]] more\n"

    assert edges(format_markdown(body).text) == edges(body)


def test_an_already_formatted_body_is_unchanged() -> None:
    result = format_markdown("# Title\n\nA paragraph with [[KAN-1]].\n")

    assert result.outcome == "unchanged"
    assert result.changed_lines == 0


def test_an_engine_failure_declines_instead_of_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*args: object, **kwargs: object) -> str:
        raise ValueError("pathological")

    monkeypatch.setattr(markdown_format.mdformat, "text", explode)

    result = format_markdown("# Title  \n")

    assert result.outcome == "skipped"
    assert result.text == "# Title  \n"
    assert result.reason is not None


def test_a_result_that_would_change_the_links_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """The safety net: if the placeholder trick ever fails, the note is left alone."""
    monkeypatch.setattr(markdown_format.mdformat, "text", lambda text, **kw: "dropped the link\n")
    body = "see [[KAN-1]]\n"

    result = format_markdown(body)

    assert result.outcome == "skipped"
    assert result.text == body
    assert "links" in (result.reason or "")


def test_empty_text_is_unchanged() -> None:
    assert format_markdown("").outcome == "unchanged"


# --- The corpus: every markdown file this repo ships ---------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[3]
CORPUS = sorted(
    path
    for path in REPO_ROOT.rglob("*.md")
    if not {"node_modules", ".venv", ".git", "dist"} & set(path.relative_to(REPO_ROOT).parts)
)


def test_the_corpus_is_not_empty() -> None:
    """A glob that silently matches nothing would make the next test pass vacuously."""
    assert len(CORPUS) > 50


@pytest.mark.parametrize("path", CORPUS, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_real_documents_format_idempotently_and_keep_their_links(path: Path) -> None:
    """KAN-1814's acceptance, over ~170 real files: format(format(x)) == format(x), identical link
    edges, and the formatter never *declined* — a skip here would mean it can't handle prose this
    project actually writes."""
    text = path.read_text()

    once = format_markdown(text)
    twice = format_markdown(once.text)

    assert once.outcome != "skipped", once.reason
    assert twice.text == once.text
    assert edges(once.text) == edges(text)
