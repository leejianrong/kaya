"""Step 4 of ADR 0004's ordering: serialization. **The one dimension V2a actually implements.**

Every format renders from the same ``Shaped.as_dict()``, which is the mechanism behind ADR 0005's
first contract line ("over **one** serializer … so formats cannot drift"). A format is a function
in ``_SERIALIZERS`` and nothing else; adding one is registering one, which is how ``toon`` arrives
in KAN-541 without this module's shape changing.

### Two vocabularies, because two audiences

``_SERIALIZERS`` is the **full registry**: every format that can be rendered. ``Format`` is the
**user-facing** subset — the values a person may type after ``--format``, and therefore a published
contract in ADR 0005's sense. ``AdapterFormat`` is what only in-tree adapters ask for by name.

The split is structural rather than documentary, and specifically it is arranged so that the obvious
line an adapter author writes is the correct one::

    parser.add_argument("--format", choices=[fmt.value for fmt in Format], default="human")

That expression yields exactly SLICES §V2a's ``{human, json, toon}`` and can never yield ``data``,
because ``data`` is not in ``Format`` at all. Had ``Format`` held every registered format,
publishing an adapter-only value to the CLI would be the *default* outcome of writing the obvious
thing — and ADR 0005's whole lesson is that a contract published early cannot be cheaply withdrawn.
Pandan spent a whole card (KAN-442) withdrawing a ``pdn`` alias; ten lines here is the same trade
this slice exists to make.

**KAN-541 adds ``toon`` to both ``_SERIALIZERS`` and ``Format``** — the registry so it renders, the
enum so it is offered. ``tests/test_serialization.py`` fails if it lands in only one of them, and
the literal pin on ``CLI_FORMATS`` there makes publishing it a conscious edit rather than a side
effect.

### Which formats exist today, and why ``toon`` does not

``human`` and ``json`` are user-facing; ``data`` is adapter-facing. ``toon`` is KAN-541's, along
with the ``--format`` flag it is reached through and the decoder that proves its round trip. It
is not registered here as a stub that raises, because then there would be two ways for a format to
be unavailable and an adapter would have to handle both. It is simply not a known format yet, and
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

It is deliberately **not** a `--format` value. It is an argument an adapter passes in code, where
the audience is the person writing the adapter and not the person at a shell.

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
    """**The user-facing vocabulary** — the values a person may type after ``--format``.

    This enum is a published contract (ADR 0005 §contract 1, SLICES §V2a: ``{human,json,toon}``), so
    a member added here is a member that cannot be cheaply withdrawn. Adapter-only formats live in
    ``AdapterFormat`` and are absent from here on purpose: iterating this enum for an argparse
    ``choices`` list is the obvious thing to write, and it has to be the right thing to write.

    ``toon`` joins this enum in KAN-541, at the same time as it joins ``_SERIALIZERS``.
    """

    HUMAN = "human"
    JSON = "json"


class AdapterFormat(StrEnum):
    """Formats an in-tree adapter asks for **by name in code**, never by a value a person typed.

    Not a user-facing contract, and not reachable through ``--format``. See ``data``'s section in
    this module's docstring for why the MCP adapter needs one.
    """

    DATA = "data"


def serialize(shaped: Shaped, fmt: str) -> str | dict[str, Any]:
    """Render the shaped dict in ``fmt``. The only step that branches on format, deliberately."""
    if not isinstance(shaped, Shaped):
        raise TypeError("serialize takes a Shaped — run attach_summary first (ADR 0004 §3)")
    try:
        serializer = _SERIALIZERS[str(fmt)]
    except KeyError:
        # The user-facing set only. This message is reachable from a shell — a CLI user who typed
        # `--format hunan` must not be told that `data` is something they may ask for, because a
        # suggestion in an error message is a contract too, and it would be published before
        # KAN-541 has written the flag it appears to describe. An adapter author who mistypes an
        # `AdapterFormat` gets a slightly thinner message; they have this module open.
        known = ", ".join(CLI_FORMATS)
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
    AdapterFormat.DATA: _as_data,
}
"""The **full** registry, user-facing and adapter-facing alike. One entry per format, so "one
serializer" is a fact about this dict rather than a claim in a doc. KAN-541 adds ``toon`` here *and*
to ``Format``; a format in this dict is merely renderable, not advertised."""

CLI_FORMATS: tuple[str, ...] = tuple(fmt.value for fmt in Format)
"""What ``--format`` may be given, in declaration order — ``human`` first because it is the default.

Derived from ``Format`` rather than written out again, so the enum stays the single place the
published vocabulary is decided. This is what KAN-541 hands to argparse's ``choices``."""
