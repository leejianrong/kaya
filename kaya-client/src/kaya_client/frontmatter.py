"""R12's file format: YAML-ish front matter, a fence, the body verbatim.

`docs/roadmap/BREADBOARD.md`'s R12 fixes the shape — ``kaya_ref``, ``title``, ``path``,
``created_at``, ``updated_at`` as front matter, a ``---`` line, then the body — and its headline
finding is why this module is short: kaya's ``[[Title]]`` wikilink syntax is already
Obsidian-native, so the body crosses this boundary **unchanged**. There is no link rewriting here
and there must not be one — a rewriter would be the thing R12 measured as unnecessary, re-added by
accident.

### Hand-rolled, not a YAML library

`kaya-client` has exactly one runtime dependency, ``httpx`` (see ``pyproject.toml``), for the
reason its own docstring gives: the serializers are stdlib so that shaping stays free of anything
that could pull a wheel in behind an adapter's back. A YAML *reader* for arbitrary front matter
(tags, nested maps, block scalars — the shapes a real Obsidian vault uses) is a general parser this
module does not attempt to be. What it reads is a fixed handful of scalar ``key: value`` lines —
kaya writes exactly five, and an arbitrary vault's front matter is read only far enough to find
``kaya_ref`` and ``title`` if either is there — and a line this module does not understand is
skipped, not refused, because refusing a vault's ``tags: [x, y]`` would make importing anyone
else's Obsidian notes a usage error over a feature this module has no need of.

### Why `compose_document`/`parse_document` live in `kaya-client` and not `kaya-cli`

ADR 0004's review question: would a future adapter (an MCP export tool, say) have to reimplement
this to be correct? Yes — the front matter shape is a fact about kaya's own file format, not about
how an argv reached this package, so it belongs where ``export``/``import``'s note-shaping already
lives (`KayaClient`), the same reasoning that keeps truncation and projection out of `kaya-cli`.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

FENCE = "---"

REF_KEY = "kaya_ref"
TITLE_KEY = "title"
PATH_KEY = "path"
CREATED_KEY = "created_at"
UPDATED_KEY = "updated_at"

FRONT_MATTER_FIELDS: tuple[tuple[str, str], ...] = (
    (REF_KEY, "ref"),
    (TITLE_KEY, TITLE_KEY),
    (PATH_KEY, PATH_KEY),
    (CREATED_KEY, CREATED_KEY),
    (UPDATED_KEY, UPDATED_KEY),
)
"""``(front-matter key, record key)`` pairs, in the order `compose_document` writes them —
BREADBOARD.md's R12 shape. Only ``ref`` differs: the API's own record (`NoteRead`) spells a note's
identity ``ref``, and front matter spells it ``kaya_ref`` so the field reads unambiguously in a
file that is not otherwise namespaced kaya's — the same word BREADBOARD.md's R12 table uses.

A whitelist rather than "every key the record has": `KayaClient.get_note`'s record still carries
``id`` and ``body``. ``id`` must never reach a file — ADR 0008 makes ``ref`` a note's identity, and
publishing the internal surrogate beside it invites exactly the confusion ADR 0008 argues against —
and ``body`` goes after the fence, verbatim, rather than as a front-matter scalar (it is prose, not
a short field, and YAML's block-scalar rules are the general-parser problem this module opts out
of)."""


@dataclass(frozen=True)
class ParsedDocument:
    """A file split into its front matter (parsed as far as this module goes) and its body.

    ``front_matter`` is whatever ``key: value`` lines were found between two fences, however many
    of `FRONT_MATTER_FIELDS` that turns out to be — including none, for a file with no fence at all,
    or an arbitrary vault file whose front matter kaya cannot read past. ``body`` is the rest of the
    file, byte for byte: no trailing-newline trimming, no re-encoding, so ``compose_document`` and
    ``parse_document`` round-trip a body exactly.
    """

    front_matter: Mapping[str, str] = field(default_factory=dict)
    body: str = ""

    def get(self, key: str) -> str | None:
        """One front-matter value, or ``None`` — the only thing a caller of this module needs from
        ``front_matter`` directly; see `KayaClient._import_document`'s use of ``kaya_ref`` and
        ``title``.
        """
        return self.front_matter.get(key)


def compose_document(record: Mapping[str, Any]) -> str:
    """One note, as ``export`` writes it: the fenced front matter, then ``record["body"]``
    verbatim.

    Only the keys in `FRONT_MATTER_FIELDS` that ``record`` actually carries are written — a record
    missing ``path`` (never happens from the API, but this function makes no assumption about its
    caller) simply omits the line rather than writing ``path: "None"``.
    """
    lines = [FENCE]
    for front_matter_key, record_key in FRONT_MATTER_FIELDS:
        value = record.get(record_key)
        if value is not None:
            lines.append(f"{front_matter_key}: {_quote(str(value))}")
    lines.append(FENCE)
    lines.append("")
    return "\n".join(lines) + str(record.get("body", ""))


def parse_document(text: str) -> ParsedDocument:
    """The inverse of `compose_document`, and the reader for an arbitrary markdown file too.

    A leading line that is exactly ``---`` opens front matter; the next line that is exactly
    ``---`` closes it. Absent either — no opening fence, or an opening fence with no closing one (a
    note body that itself starts with a horizontal rule, before any front matter was ever written)
    — the *whole file* is read as the body and the front matter is empty. That is the safe default
    for a file kaya did not write, which is also the corpus-import case (BREADBOARD.md's R12: "a
    file with no ``kaya_ref``… imports as a fresh note").

    A line inside the fence that is not a plain ``key: value`` pair (a YAML list item, a nested
    map, a comment) is skipped rather than refused — see this module's docstring for why. A value
    is unquoted if it looks like one of this module's own quoted scalars (`_unquote`) and left
    exactly as written otherwise, so a bare ``title: Groceries`` in a hand-edited or
    Obsidian-authored file reads the same as this module's own quoted form.
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != FENCE:
        return ParsedDocument(front_matter={}, body=text)

    front_matter: dict[str, str] = {}
    index = 1
    closed = False
    while index < len(lines):
        line = lines[index]
        if line.strip() == FENCE:
            closed = True
            index += 1
            break
        key, colon, value = line.partition(":")
        key = key.strip()
        if key and colon:
            front_matter[key] = _unquote(value.strip())
        index += 1

    if not closed:
        return ParsedDocument(front_matter={}, body=text)

    return ParsedDocument(front_matter=front_matter, body="".join(lines[index:]))


def _quote(value: str) -> str:
    """A double-quoted YAML scalar for ``value``. Always quoted — one rule for the writer, one
    form for `_unquote` to undo, and no bare-scalar case to special-case for a title or path that
    happens to contain a colon (``"Design: notes"`` is unambiguous quoted; unquoted it would
    truncate at the first colon under a real YAML reader)."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def _unquote(value: str) -> str:
    """The inverse of `_quote`, tolerant of a bare (unquoted) scalar — see `parse_document`."""
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return _unescape(value[1:-1])
    return value


def _unescape(inner: str) -> str:
    """``\\n``, ``\\"`` and ``\\\\`` undone left to right, so a doubled backslash is never read as
    two separate escapes (the bug a sequential ``str.replace`` chain would have)."""
    result: list[str] = []
    index = 0
    while index < len(inner):
        char = inner[index]
        if char == "\\" and index + 1 < len(inner):
            nxt = inner[index + 1]
            if nxt == "n":
                result.append("\n")
                index += 2
                continue
            if nxt in ('"', "\\"):
                result.append(nxt)
                index += 2
                continue
        result.append(char)
        index += 1
    return "".join(result)
