"""The one markdown formatter (KAN-1814): ``mdformat`` with GFM and frontmatter, wikilink-safe.

One engine, on the server, for every client — the SPA's format-on-save, ``kaya note format`` and the
MCP call all reach it through ``PATCH /notes/{ref}`` with ``format: true``. A formatter in the SPA
plus a second one in Python would make a note flip-flop depending on who saved it last, and
formatting is a *write-side transform*, not output shaping, so it does not belong in an adapter
(ADR 0004).

**Why this is not just ``mdformat.text(body)``.** mdformat escapes brackets it cannot prove are
literal, so ``[[KAN-12]]`` comes back as ``\\[[KAN-12]\\]`` — which ``find_wikilinks`` no longer
sees as a link. ``note_link`` is re-reconciled from the body on every save, so that one escape
would silently delete an edge from the graph and from every backlinks panel. So every ``[[…]]``
span is swapped for an opaque placeholder *of the same length* before formatting and swapped back
after. Same length matters for tables, whose column padding is computed from cell width: a shorter
stand-in would pad differently from the text it replaces.

**A safety net, because a placeholder is a trick and tricks fail.** After formatting, the link
edges of the result are compared with the edges of the input. If they differ in any way, or if the
engine raises on a pathological document, the original text is returned and the reason is reported
(``skipped``). A formatter that cannot prove it left the link graph alone does not get to touch the
note — an unformatted save is a cosmetic miss, a lost edge is data loss.

Nothing here reads a session or calls pandan (ADR 0003): a pure function of its input.
"""

import difflib
import re
from dataclasses import dataclass
from typing import Literal

import mdformat

from app.wikilinks import find_note_title_links, find_wikilinks

EXTENSIONS = frozenset({"gfm", "frontmatter"})
"""``gfm`` brings tables, strikethrough, task lists and autolinks; ``frontmatter`` keeps a leading
``---`` YAML block out of the markdown parser, which would otherwise read it as a thematic break
over a setext heading and mangle it."""

OPTIONS = {"number": True}
"""Consecutive ordered-list numbering (``1. 2. 3.``). mdformat's default writes ``1.`` on every
item, which is valid but reads as a bug to the human who typed ``1. 2. 3.``."""

# Anything between ``[[`` and ``]]`` on one line with no bracket inside. Deliberately wider than the
# two wikilink grammars: it protects *every* double-bracket span, including ones that are not links,
# so the formatter never has an opinion about them. No backslash lookbehind, because the link
# detector (``app/wikilinks.py``) has none either: ``\\[[KAN-1]]`` is an edge to it, so it has to
# be an untouchable span to us.
_WIKILINK_SPAN = re.compile(r"\[\[[^\[\]\n]+\]\]")

Outcome = Literal["formatted", "unchanged", "skipped"]


@dataclass(frozen=True)
class FormatResult:
    """What formatting a body did, in a shape both the write path and the check path can use."""

    text: str
    """The formatted body, or the input verbatim when ``outcome`` is ``skipped``."""

    outcome: Outcome
    """``formatted`` the text changed, ``unchanged`` it was already formatted, ``skipped`` the
    formatter declined (see ``reason``) and ``text`` is the input."""

    reason: str | None = None
    """Why it was skipped; ``None`` otherwise. A short, loggable phrase, never user content."""

    changed_lines: int = 0
    """Lines added plus lines removed by a ``difflib`` unified diff — a rough size for the hint
    ("would reformat 14 lines"), not a precise edit distance."""


def _edges(text: str) -> list[tuple[str, str]]:
    """Every link edge the reconciler would derive from ``text``, order-preserving, span-free."""
    return [
        *[(ref.kind, ref.canonical) for ref in find_wikilinks(text)],
        *[(link.kind, link.title) for link in find_note_title_links(text)],
    ]


def _unused_prefix(text: str) -> str:
    prefix = "zqwl"
    while prefix in text:
        prefix += "q"
    return prefix


def _protect(text: str) -> tuple[str, dict[str, str]]:
    prefix = _unused_prefix(text)
    originals: dict[str, str] = {}

    def swap(match: re.Match[str]) -> str:
        original = match.group(0)
        # The trailing ``q`` is a terminator: without it ``…1`` is a prefix of ``…10`` and the
        # restore would replace the first inside the second. Padding to the original's width with
        # more letters keeps a table cell measuring the same.
        token = f"{prefix}{len(originals)}q".ljust(len(original), "q")
        originals[token] = original
        return token

    return _WIKILINK_SPAN.sub(swap, text), originals


def _restore(text: str, originals: dict[str, str]) -> str:
    for token, original in originals.items():
        text = text.replace(token, original)
    return text


def _count_changed_lines(before: str, after: str) -> int:
    diff = difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0)
    return sum(
        1
        for line in diff
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    )


def format_markdown(text: str) -> FormatResult:
    """Format ``text``; never raises and never alters the link graph."""
    protected, originals = _protect(text)
    try:
        formatted = mdformat.text(protected, extensions=EXTENSIONS, options=OPTIONS)
    except Exception:  # noqa: BLE001 — any engine failure means "decline", never "fail the save"
        return FormatResult(text, "skipped", "the formatter could not parse this document")

    formatted = _restore(formatted, originals)

    # A placeholder the engine split, dropped or duplicated would leave a stray token behind.
    if any(token in formatted for token in originals) or _edges(formatted) != _edges(text):
        return FormatResult(text, "skipped", "formatting would have changed the note's links")

    if formatted == text:
        return FormatResult(text, "unchanged")
    return FormatResult(formatted, "formatted", changed_lines=_count_changed_lines(text, formatted))
