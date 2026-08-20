"""What ADR 0006 §3's compaction costs and saves, re-measurable without a credential.

    cd mcp && uv run --with tiktoken python scripts/measure_schema_compaction.py

`tiktoken` is supplied for the run only, the same arrangement `kaya-client/scripts/
measure_toon_delta.py` documents: `kaya-mcp` depends on `kaya-client` and `mcp`, and a measurement
script must not add a third.

Two figures, and quoting only one of them would be misleading in either direction.

- **The input schemas alone** is the biggest honest percentage, and it is the narrower thing: it is
  what changes, but not what a host holds.
- **The whole `tools/list` reply** is what a host holds resident, descriptions included — and the
  descriptions here are the tool docstrings, which compaction does not touch. So this figure is
  smaller and is the one to compare against ADR 0006 §3's ~16%.

Neither is the per-read payload cost, which is the other number V6 owes and which **KAN-574 owns**.
ADR 0006 §3's proportions are the frame: compacting the JSON saves ~16%, narrowing a read to five
useful fields saves 84%, and this script measures the first one.

Prints markdown with `--markdown`, matching the toon script so a PR body can paste it.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

import anyio
from mcp.server.mcpserver import MCPServer

from kaya_mcp.server import server


def _blob(value: Any) -> str:
    """Compact JSON, which is what a transport sends and so what a size should be measured on."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _listings() -> tuple[list[Any], list[Any]]:
    """The uncompacted listing and the advertised one.

    `MCPServer.list_tools(server)` is `SchemaCompactingServer`'s override stepped past, which is
    pydantic's own schema — see that class's docstring for why the two objects are separate.
    """
    before = anyio.run(lambda: MCPServer.list_tools(server))
    after = anyio.run(server.list_tools)
    return before, after


def _rows() -> list[tuple[str, str, str]]:
    before, after = _listings()
    schemas_before = _blob([tool.input_schema for tool in before])
    schemas_after = _blob([tool.input_schema for tool in after])

    def listing(tools: list[Any]) -> str:
        return _blob(
            [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.input_schema,
                }
                for tool in tools
            ]
        )

    return [
        ("input schemas only", schemas_before, schemas_after),
        ("whole tools/list reply", listing(before), listing(after)),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--markdown", action="store_true", help="emit a table for a PR body")
    parser.add_argument("--encoding", default="o200k_base", help="tiktoken encoding name")
    args = parser.parse_args()

    encoding = None
    try:
        import tiktoken

        encoding = tiktoken.get_encoding(args.encoding)
    except ImportError:  # pragma: no cover - the script's own advice
        print("no tiktoken; reporting bytes only (see this file's docstring for the run command)")

    def counts(text: str) -> tuple[int, int | None]:
        return len(text.encode("utf-8")), (len(encoding.encode(text)) if encoding else None)

    if args.markdown:
        print(f"| what | bytes | tokens (`{args.encoding}`) |")
        print("|---|---|---|")

    for label, before, after in _rows():
        before_bytes, before_tokens = counts(before)
        after_bytes, after_tokens = counts(after)
        byte_delta = (after_bytes - before_bytes) / before_bytes * 100
        token_note = "n/a"
        if before_tokens and after_tokens:
            token_delta = (after_tokens - before_tokens) / before_tokens * 100
            token_note = f"{before_tokens} → {after_tokens} ({token_delta:+.1f}%)"
        byte_note = f"{before_bytes} → {after_bytes} ({byte_delta:+.1f}%)"
        if args.markdown:
            print(f"| {label} | {byte_note} | {token_note} |")
        else:
            print(f"{label}:\n  bytes  {byte_note}\n  tokens {token_note}")


if __name__ == "__main__":
    main()
