"""Step 4 of ADR 0004's ordering: serialization. **The one dimension V2a actually implements.**

Every format renders from the same ``Shaped.as_dict()``, which is the mechanism behind ADR 0005's
first contract line ("over **one** serializer … so formats cannot drift"). A format is a function
in ``_SERIALIZERS`` and nothing else; adding one is registering one, which is how ``toon`` arrives
in KAN-541 without this module's shape changing.

### Which formats exist today, and why ``toon`` does not

``human``, ``json`` and ``data``. ``toon`` is KAN-541's, along with the ``--format`` flag it is
reached through and the test-only decoder that proves its round trip (SLICES §V2a step 2). It is
not registered here as a stub that raises, because then there would be two ways for a format to be
unavailable and an adapter would have to handle both. It is simply not a known format yet, and
``render(payload, fmt="toon")`` raises the same ``UnknownFormat`` as a typo would until 541
registers it.

### ``data``, and what makes ``render``'s ``-> str | dict`` precise

ADR 0004 types the seam ``str | dict`` but names only three formats, all of which are strings. The
``dict`` arm needs a spelling, and this is it: ``data`` returns the shaped dict itself — the exact
output of steps 1–3, before any encoder touches it.

It earns its place from the MCP adapter, which V6 will write. An MCP tool returning
``structuredContent`` hands the host a JSON object, and a client that serialized to a string only
for FastMCP to parse it back would be doing a round trip to reach a value it already had. Without
``data``, the obvious workaround is ``json.loads(render(..., fmt="json"))`` in the adapter — a
shaping decision leaking out of the client one careless line at a time, which is the thing ADR 0004
exists to stop. **``data`` is the only value that returns a ``dict``; every other format returns a
``str``.** ``tests/test_serialization.py`` pins both halves.

### Compact JSON, not ``indent=2``

Pandan's decomposition found pretty-printing was 16% of a 44,902-token payload. ``human`` is the
format a person reads; ``json`` is the format a script or an agent reads, and it goes to ``jq`` or
to a parser either way. Sixteen percent for whitespace nobody looks at is the wrong trade in a
package whose entire reason for existing is that number.
"""

import json
from collections.abc import Callable
from enum import StrEnum
from typing import Any

from kaya_client.errors import UnknownFormat
from kaya_client.payloads import Kind, Shaped

COLUMN_GAP = "  "
"""Two spaces between columns. Fixed, because the default human row is pinned byte-identically."""


class Format(StrEnum):
    """The serializers that exist. ``toon`` joins this enum in KAN-541."""

    HUMAN = "human"
    JSON = "json"
    DATA = "data"


def serialize(shaped: Shaped, fmt: str) -> str | dict[str, Any]:
    """Render the shaped dict in ``fmt``. The only step that branches on format, deliberately."""
    if not isinstance(shaped, Shaped):
        raise TypeError("serialize takes a Shaped — run attach_summary first (ADR 0004 §3)")
    try:
        serializer = _SERIALIZERS[str(fmt)]
    except KeyError:
        known = ", ".join(sorted(_SERIALIZERS))
        raise UnknownFormat(f"unknown format {fmt!r} — known formats are {known}") from None
    return serializer(shaped)


def _as_data(shaped: Shaped) -> dict[str, Any]:
    return shaped.as_dict()


def _as_json(shaped: Shaped) -> str:
    # `ensure_ascii=False`: a note is prose and prose is not ASCII. Escaping a CJK title to `\uXXXX`
    # triples its byte cost and makes the output unreadable in the one format meant to be piped to
    # something that will print it.
    return json.dumps(shaped.as_dict(), ensure_ascii=False, separators=(",", ":"))


def _as_human(shaped: Shaped) -> str:
    # V2b appends ADR 0005 §contract 5's trailing summary line here, from `shaped.summary`, which
    # is `None` for the whole of V2a. Not stubbed: a placeholder that renders a dict's `repr` would
    # be a wrong human format shipping under the byte-identity pin that is supposed to catch it.
    if shaped.payload.kind is Kind.COLLECTION:
        return _rows(shaped)
    return _entity(shaped)


def _rows(shaped: Shaped) -> str:
    """A collection as an aligned table, no header, one note per line.

    No header row: the columns are ``ref``/``title``/``path``, which nobody needs told apart, and a
    header is two lines of cost on every read an agent makes. V2b's ``--fields`` widens the row and
    can revisit that with a reason.

    Column widths come from the rows **actually returned**, so a list of short notes is not padded
    to the width of one long one somewhere else in the corpus.
    """
    payload = shaped.payload
    if not payload.records:
        # A definitive zero state rather than an empty string, which is indistinguishable from a
        # crashed pipe.
        return f"no {payload.envelope_key}"

    grid = [[_cell(record.get(column)) for column in payload.columns] for record in payload.records]
    widths = [max(len(row[i]) for row in grid) for i in range(len(payload.columns))]
    return "\n".join(
        COLUMN_GAP.join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip()
        for row in grid
    )


def _entity(shaped: Shaped) -> str:
    """One note: a label block of its scalar columns, then its prose, separated by a blank line.

    Prose is printed **unlabelled and last** because it is the thing the reader opened the note for,
    and because a multi-line value inside an aligned block destroys the alignment. That layout is
    also what makes V2b's truncation hint have somewhere to go — it appends to the prose section
    without disturbing a single byte of the block above it.
    """
    payload = shaped.payload
    record = payload.record

    labels = [column for column in payload.columns if column not in payload.prose_fields]
    prose = [column for column in payload.columns if column in payload.prose_fields]

    blocks: list[str] = []
    if labels:
        width = max(len(label) for label in labels)
        blocks.append(
            "\n".join(
                f"{label.ljust(width)}{COLUMN_GAP}{_cell(record.get(label))}".rstrip()
                for label in labels
            )
        )
    # An empty prose field contributes no block. `NoteCreate` defaults `body` to `""`, so a note
    # created from a title alone is the common case, and a trailing blank line on it would be
    # invisible in review and load-bearing under a byte-identity pin.
    blocks.extend(text for column in prose if (text := str(record.get(column) or "")))
    return "\n\n".join(blocks)


def _cell(value: Any) -> str:
    """One table cell. ``None`` is blank, and a newline never reaches the grid.

    Collapsing whitespace is layout, not shaping: it applies only to a value being placed in an
    aligned column, and the prose section above prints its values untouched. A `title` with a
    newline in it would otherwise silently shift every row below it one column left.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    return " ".join(value.split())


_SERIALIZERS: dict[str, Callable[[Shaped], Any]] = {
    Format.HUMAN: _as_human,
    Format.JSON: _as_json,
    Format.DATA: _as_data,
}
"""The registry. One entry per format, so "one serializer" is a fact about this dict rather than a
claim in a doc. KAN-541 adds ``toon`` by adding a line here."""
