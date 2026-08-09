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

**KAN-541 added ``toon`` to both ``_SERIALIZERS`` and ``Format``** — the registry so it renders, the
enum so it is offered — and to ``_ERROR_SERIALIZERS`` at the bottom of this module, so a refusal
renders in it too. ``tests/test_serialization.py`` fails if it lands in only one of them, and the
literal pin on ``CLI_FORMATS`` there made publishing it a conscious edit rather than a side effect.

### Which formats exist, and which audience each is for

``human``, ``json`` and ``toon`` are user-facing; ``data`` is adapter-facing. Adding a fourth
user-facing format is four edits — ``Format``, ``_SERIALIZERS``, ``_ERROR_SERIALIZERS``, and the
literal in ``tests/test_serialization.py`` — and every one of them is guarded by a test that fails
loudly rather than by a note somebody has to read.

``toon`` deliberately arrived as a *registration* rather than as a stub that raises: two ways for a
format to be unavailable would mean two branches in every adapter. Before KAN-541 it was simply not
a known format, and ``render(payload, fmt="toon")`` raised the same ``UnknownFormat`` a typo does.

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

It is also what makes ``toon``'s measurement honest. ``scripts/measure_toon_delta.py`` compares
``toon`` against **this** — compact JSON, the thing the flag actually competes with — rather than
against an indented baseline that would flatter it by sixteen percent before the encoder did
anything at all.

### Errors serialize here too, over the same vocabulary

ADR 0005 §contract 3 is an *output* contract, and V43's record in ADR 0005's context section is
explicit that "an output layer that only shapes successes is half a contract". So a failure renders
through ``serialize_error`` against ``_ERROR_SERIALIZERS`` — a second registry, keyed on exactly the
same format names. ``tests/test_error_contract.py`` asserts the two registries have identical keys,
which is what stops KAN-541 from teaching ``toon`` to render a note list and not a `404`.

Two registries rather than one, because the two are not the same function: a successful ``human``
render is an aligned table, and a failed one is ``error<TAB>code<TAB>message<TAB>arg`` — a row a
program reads, on stdout, next to nothing else. One dispatcher with an ``if is_error`` inside it
would have to be handed a union type that no step of ADR 0004's pipeline produces.
"""

import json
from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Any

from kaya_client.errors import ARG_KEY, CODE_KEY, MESSAGE_KEY, UnknownFormat
from kaya_client.payloads import Kind, Shaped
from kaya_client.toon import encode as encode_toon

COLUMN_GAP = "  "
"""Two spaces between columns. Fixed, because the default human row is pinned byte-identically."""


class Format(StrEnum):
    """**The user-facing vocabulary** — the values a person may type after ``--format``.

    This enum is a published contract (ADR 0005 §contract 1, SLICES §V2a: ``{human,json,toon}``), so
    a member added here is a member that cannot be cheaply withdrawn. Adapter-only formats live in
    ``AdapterFormat`` and are absent from here on purpose: iterating this enum for an argparse
    ``choices`` list is the obvious thing to write, and it has to be the right thing to write.

    Declaration order is the order argparse prints ``choices`` in, so ``human`` — ``render``'s
    default — leads.
    """

    HUMAN = "human"
    JSON = "json"
    TOON = "toon"


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


def _as_toon(shaped: Shaped) -> str:
    """The same shaped dict as ``_as_json``, in TOON. See `kaya_client.toon` for what that is.

    One line of code, and that is the point of the module docstring's argument: a format is a
    function in a registry. The encoder knows nothing about notes and the shaping steps know nothing
    about TOON, so the win on a uniform `note list` is a property of the *payload* rather than of a
    rule someone wrote for it.
    """
    return encode_toon(shaped.as_dict())


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
    Format.TOON: _as_toon,
    AdapterFormat.DATA: _as_data,
}
"""The **full** registry, user-facing and adapter-facing alike. One entry per format, so "one
serializer" is a fact about this dict rather than a claim in a doc. A format in this dict is merely
renderable, not advertised; what advertises it is membership of ``Format``."""

CLI_FORMATS: tuple[str, ...] = tuple(fmt.value for fmt in Format)
"""What ``--format`` may be given, in declaration order — ``human`` first because it is the default.

Derived from ``Format`` rather than written out again, so the enum stays the single place the
published vocabulary is decided. This is what KAN-541 hands to argparse's ``choices``."""


# --------------------------------------------------------------------------- errors

ERROR_MARKER = "error"
"""The first column of the human error row, and the envelope key of the structured one.

One word for both, so "did this fail?" is the same question in either format: ``line.startswith
("error\\t")`` or ``"error" in body``. It is also what makes the row unambiguous on stdout next to a
successful render — no note row begins with it, because column one of a note row is its ``ref``.
"""

ROW_SEPARATOR = "\t"
"""Tab, per ADR 0005 §contract 3. Not two spaces like ``COLUMN_GAP``: a success row is aligned for a
human to read down, and an error row is parsed by whatever caught it. A tab survives ``cut -f2``
and ``split("\\t")``; alignment padding does not."""

ROW_FIELDS: tuple[str, ...] = (CODE_KEY, MESSAGE_KEY, ARG_KEY)
"""The row after its marker, in order. The same three keys ``CONTRACT_KEYS`` guarantees, so the two
renderings of one failure carry the same facts and a consumer can move between them."""


def serialize_error(payload: Mapping[str, Any], fmt: str) -> str | dict[str, Any]:
    """Render an ``error_payload`` result in ``fmt``. The failure half of ADR 0005 §contract 3.

    Takes the built ``{"error": {…}}`` object rather than the exception, so the shape is decided in
    one place (`errors.error_payload`) and rendered in another, and a test can assert either without
    the other.
    """
    error = payload.get(ERROR_MARKER)
    if not isinstance(error, Mapping):
        raise TypeError(
            "serialize_error takes the {'error': {…}} object from error_payload, not a bare detail"
        )
    try:
        serializer = _ERROR_SERIALIZERS[str(fmt)]
    except KeyError:
        known = ", ".join(CLI_FORMATS)
        raise UnknownFormat(f"unknown format {fmt!r} — known formats are {known}") from None
    return serializer(payload)


def _error_as_data(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {ERROR_MARKER: dict(payload[ERROR_MARKER])}


def _error_as_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(_error_as_data(payload), ensure_ascii=False, separators=(",", ":"))


def _error_as_toon(payload: Mapping[str, Any]) -> str:
    """A refusal in TOON. Not a saving — one error object has no uniform rows to dedupe — but a
    consumer that asked for ``--format toon`` gets one document grammar for both outcomes, which is
    worth more on the failure path than four tokens are."""
    return encode_toon(_error_as_data(payload))


def _error_as_human(payload: Mapping[str, Any]) -> str:
    """``error<TAB><code><TAB><message><TAB><arg>`` — one line, always four fields.

    **Always four**, even when ``arg`` is empty, so the line ends in a tab and
    ``line.split("\\t")[3]`` is a value rather than an ``IndexError``. That is the row's spelling of
    "all keys always present": fixed arity is to a positional format what a guaranteed key is to an
    object one, and a consumer that has to count fields before indexing them is a consumer writing
    the conditional this contract exists to remove.

    Every field is collapsed to a single line. A refusal's message is written by the backend and may
    contain anything — ADR 0009's `409` message names two timestamps, and a future one could contain
    a note title with a newline in it. A raw newline or tab inside a field would silently turn one
    row into two, or shift ``arg`` into ``message``'s place, and the consumer would never know. The
    unmangled text is one ``--format json`` away.
    """
    error = payload[ERROR_MARKER]
    fields = [_one_line(error.get(key, "")) for key in ROW_FIELDS]
    return ROW_SEPARATOR.join([ERROR_MARKER, *fields])


def _one_line(value: Any) -> str:
    """Any value as one line of a tab-separated row. ``None`` and ``""`` are the empty field."""
    if value is None:
        return ""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return " ".join(text.split())


_ERROR_SERIALIZERS: dict[str, Callable[[Mapping[str, Any]], Any]] = {
    Format.HUMAN: _error_as_human,
    Format.JSON: _error_as_json,
    Format.TOON: _error_as_toon,
    AdapterFormat.DATA: _error_as_data,
}
"""One entry per format, and **the same keys as ``_SERIALIZERS``** — pinned by a test.

A format that could render a note list but not a refusal would fail exactly when the user most
needs output, and it would fail as a ``UnknownFormat`` raised from inside an error handler, which
reads as a client bug rather than as a missing encoder. That test is what made KAN-541 register
``toon`` in both dicts rather than in the one it was thinking about."""
