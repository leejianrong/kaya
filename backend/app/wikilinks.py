"""``[[...]]`` wikilink parsing: ``KAN-`` and ``EPIC-`` pandan refs, never ``PAN-`` (KAN-561).

Pandan's ticket and epic prefixes come from immutable Postgres sequences and were deliberately
**not** renamed under the pandan brand — pandan ADR 0018 records ``KAN-`` surviving the rebrand,
for the same reason kaya's own ``NOTE-`` is permanent (see the block comment above
``NOTE_REF_PREFIX`` in ``app/models/note.py``). A parser that goes looking for ``PAN-`` matches
nothing that has ever existed. So the accepted vocabulary is exactly two literal prefixes,
``KAN-`` and ``EPIC-``, each followed by one or more ASCII digits. Nothing else is a pandan
reference, however plausible it looks.

This module is deliberately narrow and does one thing two later cards each build directly on:

1. Find every ``[[KAN-n]]`` / ``[[EPIC-n]]`` occurring in a note's markdown body, as a **pure**
   function — no session, no HTTP client, no import of anything in ``app.auth`` or ``app.api``. ADR
   0003 forbids kaya blocking on pandan, and a parser that finds *candidate* references cannot also
   be the thing that decides whether pandan actually has a card by that number: that decision is a
   network call, belongs to a later card (KAN-564), and this file makes none.
2. Hand back a shape two future cards are already committed to. KAN-562 stores one row per
   ``WikilinkRef`` in a new ``note_link`` table and reconciles it on every save; KAN-567 uses the
   ``start``/``end`` span to place CodeMirror's ``[[`` autocomplete. Both need ``kind``, ``number``
   and the exact span the wikilink occupies in the raw text, and neither needs anything more, so
   nothing more is returned.

**Scope note, so KAN-563 does not have to guess:** this parses references to *pandan* cards and
epics only. Kaya's own note-to-note wikilinks — ``[[Some Note Title]]``, resolved by title rather
than by a ``KAN-``/``EPIC-`` prefix — are KAN-563's syntax, not this one's, and are out of scope
here. The two forms may end up sharing one regex alternation eventually; until KAN-563 exists,
keeping them apart is one call to make later rather than one call to unmake.

**KAN-563's answer: stay apart, deliberately.** ``find_note_title_links``/``NoteTitleLink`` below
are a sibling of ``find_wikilinks``/``WikilinkRef``, not a case added to it, because the two shapes
have nothing in common past "a bracket pair": a pandan reference is a closed two-word vocabulary
plus a number, a note title is unbounded text, and forcing ``WikilinkRef.number: int`` to also mean
"no number, this is a title" would turn a clean field into an optional one for every existing
caller. What *does* have to be shared is exclusion: the two parsers run as two independent scans
over the same body, so ``NOTE_TITLE_PATTERN`` carries its own negative lookahead refusing any
bracket pair that is itself a syntactically valid ``KAN-n``/``EPIC-n`` form. Without it,
``[[KAN-1]]`` would be reported twice — once as a pandan reference and once as a literal note title
"KAN-1" — and ``app/note_links.py`` would record a phantom edge to a note nobody meant to name. The
lookahead's
notion of "syntactically valid" is exactly ``WIKILINK_PATTERN``'s own (ASCII digits, optional
horizontal whitespace), so a form that ``find_wikilinks`` itself refuses — ``[[KAN-]]``,
``[[KAN-123-old]]``, a non-ASCII digit — is free to fall through and be read as a literal title
instead, the same way it already falls through to plain prose today.

## The edge cases this file was asked to get right

**The prefix vocabulary is closed and literal.** ``KAN`` and ``EPIC``, nothing else — not ``PAN``,
and no attempt to be clever about a third prefix existing later. Matching is case-*insensitive* on
the prefix itself (``[[kan-1]]`` finds ``KAN-1``), mirroring ``app/api/refs.py``'s
``NOTE_REF_PATTERN``: a human typing a card reference mid-sentence gets the same leniency kaya
already grants its own ``NOTE-`` refs, and the returned ``kind`` is always the canonical uppercase
spelling so a caller never has to normalise it a second time.

**Unclosed ``[[`` is not a link.** ``WIKILINK_PATTERN`` requires a literal closing ``]]``; with none
present the regex has nothing to match, so ``[[KAN-123`` — whatever follows it — contributes zero
``WikilinkRef``\\ s. There is no partial-match fallback, and none is wanted: a note mid-edit with a
dangling ``[[`` should read as prose, not as a broken link.

**A code fence is literal text.** A ```` ``` ````-delimited block is stripped from consideration
before the wikilink regex ever runs, via ``_fenced_ranges``, so ``[[KAN-1]]`` typed inside a fence
(demonstrating the syntax, say) is never treated as a real reference. The fence detector is
deliberately simple — any line that, once leading spaces/tabs are stripped, starts with three or
more backticks toggles fence state — and does not implement CommonMark's full "a closing fence must
be at least as long as its opening" rule. Getting that exactly right is a CommonMark-conformance
problem, not a wikilink one, and this card's job is "code fences don't leak", not "kaya grows a
second Markdown parser" (one already exists, in ``frontend/src/lib/markdown.ts``, for rendering
preview — a different job). Inline code spans (single backticks) are likewise out of scope: the card
asks about a fence, not a span. An unterminated fence — an opening delimiter with no closing one
before the body ends — is treated as running to the end of the body, the same choice CommonMark
itself makes for a document that ends mid-block.

**Nesting resolves to the innermost well-formed pair, and the malformed outer one is refused.**
``[[KAN-1 [[KAN-2]] ]]`` finds exactly one reference, ``KAN-2``. This is not a special case in the
code — it falls out of ``WIKILINK_PATTERN`` requiring the content between the brackets to be
*exactly* optional whitespace + prefix + digits + optional whitespace, with no wildcard anywhere in
between. The regex engine's ordinary left-to-right scan fails to match starting at the outer ``[[``
(there is a stray ``[[KAN-2]]`` sitting where only whitespace-then-``]]`` is allowed) and only
succeeds once it reaches the inner pair; the two leftover fragments (``[[KAN-1 `` and `` ]]``) are
not well-formed pairs either, so they contribute nothing. Written down here rather than merely
observed, because the alternative reading — "refuse the whole malformed span, find nothing at all" —
is equally defensible, and a future maintainer should not have to re-derive which one this is from
the regex alone.

**Surrounding punctuation is never swallowed.** ``([[KAN-123]].)`` and ``"[[KAN-123]],"`` both find
exactly ``KAN-123``: the pattern is anchored on the literal ``[[``/``]]`` delimiters, so nothing
about a match can extend past them and punctuation outside the brackets was never a candidate
character in the first place. There is no trimming step because there is nothing to trim.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

# The whole accepted vocabulary. Exactly these two literal prefixes — see the module docstring and
# pandan ADR 0018 for why `PAN-` is deliberately absent.
WIKILINK_KINDS: tuple[str, ...] = ("KAN", "EPIC")

# `[[`, optional horizontal whitespace, one of the two literal prefixes (case-insensitive), `-`, one
# or more ASCII digits, optional horizontal whitespace, `]]`. No wildcard appears anywhere in this
# pattern — that absence is what makes the nesting behaviour documented above fall out of
# `re.finditer`'s ordinary scan instead of needing to be coded by hand.
#
# `[ \t]*` rather than `\s*`: a wikilink is written on one line, and letting it span a newline would
# make `[[KAN-\n123]]` a link, a shape no editor produces by hand.
#
# `re.ASCII` for the same reason `app/api/refs.py` uses it on `\d`: without it, a Unicode decimal
# digit (`٣`) would parse via `int()` into a second spelling of a ref number nothing else — not
# pandan, not a resolved link — agrees with.
WIKILINK_PATTERN = re.compile(
    r"\[\[[ \t]*(?P<kind>KAN|EPIC)-(?P<number>\d+)[ \t]*\]\]",
    re.ASCII | re.IGNORECASE,
)

# Any line that, once leading spaces/tabs are stripped, starts with three or more backticks. Both
# the opening delimiter (which may carry an info string, e.g. "```python") and the closing one
# (which may not) match this, which is all `_fenced_ranges` needs: it only cares where a fence
# starts, and where the next fence-delimiter line after that is.
_FENCE_DELIMITER = re.compile(r"^[ \t]*`{3,}")


@dataclass(frozen=True)
class WikilinkRef:
    """One ``[[KAN-n]]`` / ``[[EPIC-n]]`` found in a note body.

    Deliberately minimal: ``kind``, ``number``, ``raw`` and the ``start``/``end`` span are
    everything KAN-562 (a ``note_link`` row per reference) and KAN-567 (placing CodeMirror's
    autocomplete) need, and nothing else is promised. In particular there is no ``resolved`` flag
    and no pandan payload here — this module makes no network call (ADR 0003), so it cannot know
    whether pandan actually has a card by this number. That's KAN-564's job, against the
    ``canonical`` string below.
    """

    kind: Literal["KAN", "EPIC"]
    number: int
    raw: str
    """The exact matched substring, brackets and all — e.g. ``"[[ kan-123 ]]"`` keeps its own
    casing and whitespace verbatim, because a caller that wants to act on the bytes actually typed
    (KAN-567's autocomplete, or a future rename) needs them, not a normalised re-rendering."""
    start: int
    """Offset of the opening ``[`` in the text `find_wikilinks` was given."""
    end: int
    """Offset one past the closing ``]`` — i.e. ``text[start:end] == raw``."""

    @property
    def canonical(self) -> str:
        """The ``KAN-n`` / ``EPIC-n`` spelling pandan itself would recognise: case-normalised, no
        brackets, no whitespace. What KAN-564 sends pandan to resolve this reference."""
        return f"{self.kind}-{self.number}"


def _fenced_ranges(text: str) -> list[tuple[int, int]]:
    """Character-offset spans of every fenced code block in `text`, opening and closing delimiter
    lines both included.

    Line-based and deliberately simple (see the module docstring's code-fence paragraph): it pairs
    the first fence-delimiter line it finds with the next one, with no check that the two use a
    matching number of backticks. An unterminated fence — an opening delimiter with no closing one
    before the text ends — is treated as running to the end of `text`, the same choice CommonMark
    makes for a document that ends mid-block.
    """
    ranges: list[tuple[int, int]] = []
    fence_start: int | None = None
    offset = 0
    for line in text.splitlines(keepends=True):
        line_end = offset + len(line)
        if _FENCE_DELIMITER.match(line):
            if fence_start is None:
                fence_start = offset
            else:
                ranges.append((fence_start, line_end))
                fence_start = None
        offset = line_end
    if fence_start is not None:
        ranges.append((fence_start, len(text)))
    return ranges


def _inside_a_fence(pos: int, fenced: list[tuple[int, int]]) -> bool:
    return any(start <= pos < end for start, end in fenced)


def find_wikilinks(body: str) -> list[WikilinkRef]:
    """Every ``[[KAN-n]]`` / ``[[EPIC-n]]`` in `body`, left to right, code fences excluded.

    Pure: no session, no principal, no HTTP client, and safe to call on a note body that has never
    touched a database — which is the point, since KAN-562's reconcile-on-save calls this before
    anything is written and KAN-567's autocomplete calls it on text that may never be saved at all.
    """
    fenced = _fenced_ranges(body)
    refs: list[WikilinkRef] = []
    for match in WIKILINK_PATTERN.finditer(body):
        if _inside_a_fence(match.start(), fenced):
            continue
        kind = match.group("kind").upper()
        refs.append(
            WikilinkRef(
                kind=kind,  # type: ignore[arg-type]
                number=int(match.group("number")),
                raw=match.group(0),
                start=match.start(),
                end=match.end(),
            )
        )
    return refs


# KAN-563. `[[`, optional horizontal whitespace, then any run of one or more characters that are
# neither a bracket nor a newline (lazy, so it stops at the first spot the tail can match — see the
# nesting argument below), optional horizontal whitespace, `]]`. The negative lookahead immediately
# inside the opening `[[` is what keeps this pattern from ever claiming a pair `WIKILINK_PATTERN`
# already owns — see the module docstring's "KAN-563's answer" paragraph for why that matters and
# why the lookahead's digit class is `[0-9]`, not `\d`: it must agree with `WIKILINK_PATTERN`'s own
# `re.ASCII`-gated notion of a valid ref regardless of what flags this pattern carries.
#
# No wildcard spans a bracket (the content class excludes `[`/`]`), which is what makes nesting
# resolve to the innermost well-formed pair here too, for the identical structural reason
# `WIKILINK_PATTERN` does — see that docstring paragraph; it is not re-argued twice.
#
# `[^\[\]\n]` rather than `[^\[\]]`: a wikilink is written on one line, mirroring
# `WIKILINK_PATTERN`'s `[ \t]*` choice over `\s*` for the same reason (no editor produces a bracket
# pair spanning a hand-typed newline).
NOTE_TITLE_PATTERN = re.compile(
    r"\[\[(?![ \t]*(?:KAN|EPIC)-[0-9]+[ \t]*\]\])[ \t]*([^\[\]\n]+?)[ \t]*\]\]",
    re.IGNORECASE,
)

NOTE_TITLE_MAX = 255
"""Byte-for-byte ``app/models/note_link.py``'s ``TARGET_REF_MAX``, duplicated rather than imported:
this module is pure text-in-refs-out and does not reach into the persistence layer for a constant,
the same direction ``app/models/note_link.py`` itself draws against ``app/api/schemas.py``'s
``TITLE_MAX``. A bracket span longer than this cannot name a real note (``Note.title`` is
``String(255)``) and would overflow ``note_link.target_ref``'s own column if it ever reached an
INSERT unfiltered — refusing it here is what keeps an over-long, almost certainly accidental
``[[...]]`` span from turning into a `500` on save, the same posture ``_FENCE_DELIMITER`` and
`WIKILINK_PATTERN` already take toward "not a link" over "a value nothing downstream expects"."""


@dataclass(frozen=True)
class NoteTitleLink:
    """One ``[[Some Note Title]]`` found in a note's body (KAN-563) — the note-to-note sibling of
    ``WikilinkRef``. Not the same dataclass: see the module docstring's "KAN-563's answer" for why
    the two shapes don't share a field list. ``kind`` is always ``"NOTE"`` and exists so
    ``app/note_links.py``'s diff can walk a list of these and a list of ``WikilinkRef`` through the
    one attribute pair the diff actually needs, ``(kind, canonical)``.
    """

    title: str
    """The target title exactly as typed, with only the whitespace immediately inside the brackets
    trimmed — never case-folded. Resolution (``app/note_links.py``) matches this against
    ``Note.title`` exactly, case included; see that module for the argument."""
    raw: str
    """The exact matched substring, brackets and all — same contract as ``WikilinkRef.raw``."""
    start: int
    end: int
    kind: Literal["NOTE"] = "NOTE"

    @property
    def canonical(self) -> str:
        """The diff key's second half, for the same reason ``WikilinkRef.canonical`` is one — here
        it is simply the title, since a title has no bracket-free/case-normalised spelling to
        collapse onto the way a pandan reference does."""
        return self.title


def find_note_title_links(body: str) -> list[NoteTitleLink]:
    """Every ``[[Some Note Title]]`` in `body`, left to right, code fences excluded, and any pair
    that ``find_wikilinks`` would itself recognise as a ``KAN-``/``EPIC-`` reference excluded too
    (``NOTE_TITLE_PATTERN``'s own lookahead, not a post-filter against `find_wikilinks`'s output —
    see the module docstring for why a post-filter would be the wrong shape).

    Pure, exactly like `find_wikilinks`: no session, no owner, no notion of which titles actually
    exist. Whether a title names a real note is `app/note_links.py`'s question, against a database
    this function never touches.

    A whitespace-only bracket pair (``[[   ]]``) and a span longer than `NOTE_TITLE_MAX` are both
    reported as *no* link rather than as a link with a hollow or truncated title — the same "not a
    link" treatment `WIKILINK_PATTERN` gives `[[KAN-]]`'s missing digits.
    """
    fenced = _fenced_ranges(body)
    refs: list[NoteTitleLink] = []
    for match in NOTE_TITLE_PATTERN.finditer(body):
        if _inside_a_fence(match.start(), fenced):
            continue
        title = match.group(1).strip()
        if not title or len(title) > NOTE_TITLE_MAX:
            continue
        refs.append(
            NoteTitleLink(title=title, raw=match.group(0), start=match.start(), end=match.end())
        )
    return refs
