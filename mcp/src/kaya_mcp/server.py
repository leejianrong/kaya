"""kaya's MCP server (KAN-569): six tools over `KayaClient`, and nothing else.

ADR 0006 froze the tool set before there was a server to put it on. This module is what stands one
up: a single `MCPServer` instance and six `@server.tool()` registrations, each a thin wrapper
around one `kaya_mcp.tools` call and one call to `render()`. There are six independent call sites
for `render` rather than the CLI's one, because an MCP host calls a tool by name directly — there
is no shared dispatch function here the way `kaya_cli.__main__.main` is for the CLI's nine verbs —
but every site still does the one thing ADR 0004 asks of an adapter: it never projects, truncates,
counts or formats anything itself. `fields` and truncation are inherited from `render()` for free,
which is this card's whole point (ADR 0006 §1, and the ~84% saving pandan had to file as a
follow-up rather than ship with).

### `fmt="data"`, not `fmt="json"`

`render()`'s `data` format returns the shaped dict itself (`kaya_client.serialization.
AdapterFormat.DATA`), which is exactly what an MCP tool's `structuredContent` wants — see that
module's docstring for why `json.loads(render(..., fmt="json"))` would be the ADR 0004 leak in an
MCP-shaped costume. Every tool function below is annotated `-> dict[str, Any]`, which is what makes
this SDK build a `RootModel`-backed output schema and hand the dict back as `structuredContent`
**unwrapped** — no `{"result": …}` envelope — see
`mcp.server.mcpserver.utilities.func_metadata._try_create_model_and_schema`'s `dict`-with-`str`-
keys branch, read from the installed package while writing this file.

### `fields`, on every read and only on the reads

ADR 0006 §1: every read tool takes `fields`, forwarded to `render()` unmodified — the CLI's
`--fields` and MCP's `fields` are one parameter through one seam (see `Payload.narrowed_to`'s
docstring in `kaya_client`). `create_note` and `edit_note` are writes and take none, matching that
same section's literal scope: a `fields` argument on a write would have nothing to narrow before
the request is made, and the note it echoes back is exactly the note the caller just wrote, so
omitting `fields` there costs nothing a caller is likely to want trimmed.

### The advertised schemas are compacted, and that is not the big win

ADR 0006 §3's free hygiene, landed by KAN-571: `SchemaCompactingServer` below applies
`kaya_mcp.schema.compact_schema` at `list_tools`, so a host is told
`{"type": ["string", "null"]}` where pydantic wrote `{"anyOf": [{"type": "string"}, {"type":
"null"}], "title": "Body"}`. Measured on these six tools with `o200k_base`: the input schemas alone
go **428 → 265 tokens (−38.1%)**, and the whole `tools/list` reply — descriptions included, which is
what a host actually holds resident — goes **948 → 785 (−17.2%)**, landing on the ~16% ADR 0006 §3
predicted. Read that number beside the other one in the same section: **narrowing a read to five
useful fields saves 84%**, and the tools above have taken that since KAN-569. This is the small
half, and the ADR's Finding 1 is that trimming the resident surface optimises the ~4% line item
while the 22% one sits beside it.

Two traps make this less cosmetic than it sounds, both named in the ADR and both tested next door
(`tests/test_schema_traversal.py`, `tests/test_schema_compaction.py`): a nullable **enum** must not
be collapsed, because the collapsed form rejects `null`; and `title` is an annotation *and* an
argument name — `create_note` and `edit_note` each take one — so the traversal is driven by JSON
Schema keywords rather than by the spelling of a key. `kaya_mcp.schema`'s docstring is where that
argument lives.

### Truncation, resolved the same way a CLI session resolves it

There is no `--full` flag surface here, but truncation is not optional: `_text_limit()` reads
`kaya_client.config.max_text_chars()` at call time — the same resolver that module's docstring
promises "both adapters truncate identically" through (`KAYA_MAX_TEXT_CHARS`, environment then the
user config file, then 500). Applied to every tool, reads and writes alike, matching
`kaya_cli.__main__.main`'s own rule: a write's echoed-back note can hold exactly as much prose as a
read's.

### Errors: every `KayaError` becomes a structured tool-level failure, never a traceback

`render_error(failure, fmt="data")` is `render`'s failure twin — the same `{"code", "message",
"arg", …}` object the CLI's stdout row and a raw `error_body` on the wire both carry — and `_fail`
below is where it meets *this SDK's* idiomatic failure surface. Read from the installed package
while writing this file: `mcp.server.mcpserver.tools.base.Tool.run` catches every exception a
`@server.tool()` function raises and re-raises it as a `ToolError`; `mcp.server.mcpserver.server.
MCPServer._handle_call_tool` catches that (and anything else that reaches it) and returns
`CallToolResult(is_error=True, content=[TextContent(text=str(exc))])` — a **tool-level** failure a
client can read and recover from, as distinct from a top-level JSON-RPC error, which is reserved
for `MCPError` and its subclasses and which nothing here raises. So the adapter's entire job is
choosing *what* to raise: `_fail` raises `ToolError` carrying the JSON-encoded `error_payload`
object as its message, so the same three-keys-always-present contract the CLI's stdout row carries
survives into the SDK's own error channel instead of a channel this package invented.
`note edit --if-updated-at` on a stale precondition is the case SLICES §V6's demo names
explicitly: `ApiError`'s `409` carries `attempted` and `stored` unflattened
(`kaya_client.errors.ApiError`), so both whole notes are still inside that JSON blob for a caller
to act on — a bare `str(exc)` holding only a message would have thrown that away.
"""

from __future__ import annotations

import json
from typing import Any, NoReturn

from kaya_client import KayaError, config, render, render_error
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import Tool as AdvertisedTool

from kaya_mcp import __version__, tools
from kaya_mcp.schema import compact_schema

SERVER_NAME = "kaya"
"""The MCP server's advertised name — a fact about the server, never one of ADR 0006's tool
names."""


class SchemaCompactingServer(MCPServer):
    """An `MCPServer` that advertises ADR 0006 §3's compacted schemas (KAN-571).

    `list_tools` is the **one place** a tool's input schema leaves this process. Read from the
    installed package while writing this: `MCPServer.list_tools` is the only consumer of
    `Tool.parameters`, and the object that *validates* an incoming call is a different one —
    `Tool.fn_metadata.arg_model`, built by `func_metadata` at registration, from which
    `Tool.parameters` was derived once and never again. `MCPServer._handle_list_tools` reaches the
    listing through `self.list_tools()`, so a host over stdio and a test calling the method see the
    same bytes.

    That is why the compaction is applied *here* rather than by rewriting the registration:
    ADR 0006 §3's saving is a fact about what a host is **told**, and doing it at the advertisement
    makes "compaction cannot change what is accepted" structural — the validating model is not
    reachable from this method — instead of a promise the traversal has to keep. It also leaves
    pydantic's own schema in place beside the compacted one, which is what
    `tests/test_schema_compaction.py` diffs to assert the two still agree on the argument names,
    their required-ness and their nullability.

    Public rather than private for one reason: kaya's six tools contain **no nullable enum**, so
    GUARD 1 has to be asserted over a *constructed* tool, and a test builds one of these to drive
    that tool through the real SDK rather than hand-writing the schema it would have produced.
    """

    async def list_tools(self) -> list[AdvertisedTool]:
        """The advertised listing, each input schema compacted (ADR 0006 §3)."""
        return [
            tool.model_copy(update={"input_schema": compact_schema(tool.input_schema)})
            for tool in await super().list_tools()
        ]


server: SchemaCompactingServer = SchemaCompactingServer(name=SERVER_NAME, version=__version__)
"""The one server instance. `kaya_mcp.__main__.main` runs it over stdio, the transport an MCP host
launches a server subprocess with; nothing here assumes a particular one."""


def _fail(failure: Exception) -> NoReturn:
    """Raise the SDK's tool-level failure, carrying `render_error`'s object as its message.

    See this module's docstring for why `raise` is the whole contract, and why `ToolError` rather
    than a bare `Exception`: it is the SDK's own base class for "a tool ran and it failed", so a
    caller reading a traceback (in a test, or in the host's own logs) can tell this apart from an
    adapter bug rather than reading an opaque `Exception`.
    """
    error = render_error(failure, fmt="data")
    raise ToolError(json.dumps(error["error"], ensure_ascii=False)) from failure


def _text_limit() -> int:
    """`KAYA_MAX_TEXT_CHARS`, resolved at call time. See the module docstring's truncation
    section."""
    return config.max_text_chars()


@server.tool()
def list_notes(fields: list[str] | None = None) -> dict[str, Any]:
    """List every note the caller owns, newest first. `fields` narrows the result (ADR
    0004/0006)."""
    try:
        payload = tools.list_notes()
        return render(payload, fields=fields, text_limit=_text_limit(), fmt="data")
    except KayaError as failure:
        _fail(failure)


@server.tool()
def get_note(ref: str, fields: list[str] | None = None) -> dict[str, Any]:
    """Read one note, addressed as `NOTE-12`, `note-12` or `12` — every spelling resolves the same
    way (ADR 0008), because the ref reaches the API untouched."""
    try:
        payload = tools.get_note(ref)
        return render(payload, fields=fields, text_limit=_text_limit(), fmt="data")
    except KayaError as failure:
        _fail(failure)


@server.tool()
def create_note(title: str, body: str | None = None, path: str | None = None) -> dict[str, Any]:
    """Create a note from a title, and optionally a body and a path. A write: no `fields`."""
    try:
        payload = tools.create_note(title, body=body, path=path)
        return render(payload, text_limit=_text_limit(), fmt="data")
    except KayaError as failure:
        _fail(failure)


@server.tool()
def edit_note(
    ref: str,
    title: str | None = None,
    body: str | None = None,
    path: str | None = None,
    if_updated_at: str | None = None,
) -> dict[str, Any]:
    """Change a note; fields not named are left alone.

    `if_updated_at` is ADR 0009's precondition, opt-in exactly as `kaya note edit
    --if-updated-at` is: omit it for a plain overwrite, or echo back the `updated_at` an earlier
    read returned, and a note that has moved on answers with a structured `409` — `attempted` and
    `stored`, two whole notes, inside this tool's error text (see the module docstring).
    """
    try:
        payload = tools.edit_note(
            ref, title=title, body=body, path=path, if_updated_at=if_updated_at
        )
        return render(payload, text_limit=_text_limit(), fmt="data")
    except KayaError as failure:
        _fail(failure)


@server.tool()
def search_notes(q: str, fields: list[str] | None = None) -> dict[str, Any]:
    """Notes matching `q`, ranked by relevance (KAN-558) — the same shape `list_notes` returns,
    because `KayaClient.list_notes` is the one call both verbs make (KAN-559)."""
    try:
        payload = tools.search_notes(q)
        return render(payload, fields=fields, text_limit=_text_limit(), fmt="data")
    except KayaError as failure:
        _fail(failure)


@server.tool()
def get_backlinks(ref: str, fields: list[str] | None = None) -> dict[str, Any]:
    """Notes whose body links to `ref` — the same shape `list_notes` returns.

    `/backlinks` answers with the very same `NoteList` a plain list does, so `fields`, truncation
    and the `{"count": n}` aggregate arrive here with nothing written for them (ADR 0004).

    **KAN-569 predicted that landing KAN-566 would change this tool's body and not its signature,
    and the prediction held with room to spare: neither moved.** The parameters are what they were
    (`ref`, and `fields` like every other read), and so is every line of this function — the whole
    change is one body in `kaya_mcp.tools`, which is what "the adapter is thin" is supposed to
    mean. Recorded here rather than deleted because a prediction that held is only worth having
    made if somebody checks it (KAN-964).
    """
    try:
        payload = tools.get_backlinks(ref)
        return render(payload, fields=fields, text_limit=_text_limit(), fmt="data")
    except KayaError as failure:
        _fail(failure)
