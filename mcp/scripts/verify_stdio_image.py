"""Prove a built `kaya-mcp` image actually serves the six tools over stdio, not just that
`docker build` exited 0.

    cd mcp && uv run python3 scripts/verify_stdio_image.py <image-tag>

Spawns `docker run -i --rm <image-tag>` as the MCP server subprocess — the exact shape an MCP host
uses to launch this image (`mcp/Dockerfile`'s `ENTRYPOINT ["kaya-mcp"]`, no shell, no TTY) — and
drives a real `initialize` + `tools/list` over its stdin/stdout using the same SDK client transport
`tests/test_protocol_e2e.py` drives over an in-memory pair. No PAT and no live kaya backend: a tool
*call* would need one, but `tools/list` does not, since ADR 0006's frozen six are static
registrations (`server.py`) and the compaction KAN-571 applied runs with no upstream in scope
either (`schema.py`).

Exits non-zero and prints why on any of: the container failing to start, `initialize` timing out or
erroring, or the returned tool set disagreeing with `kaya_mcp.TOOL_NAMES` — the same set
`test_frozen_tool_set.py` and `test_server.py` pin, read here rather than re-typed, so this script
cannot drift from what the unit suite already calls the truth.
"""

from __future__ import annotations

import argparse
import sys

import anyio
from mcp import StdioServerParameters
from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client

from kaya_mcp import TOOL_NAMES

# Generous: a cold `docker run` on a first pull/build can take longer than a warm in-memory
# handshake ever would, and this script is a build-time smoke test, not a latency budget.
HANDSHAKE_TIMEOUT_SECONDS = 30


async def _list_tools_over_docker(image: str) -> list[str]:
    params = StdioServerParameters(command="docker", args=["run", "-i", "--rm", image])
    with anyio.fail_after(HANDSHAKE_TIMEOUT_SECONDS):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return sorted(tool.name for tool in result.tools)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", help="the built image tag, e.g. kaya-mcp:dev")
    args = parser.parse_args()

    print(f"▸ initialize + tools/list against docker run -i --rm {args.image}")
    try:
        names = anyio.run(_list_tools_over_docker, args.image)
    except TimeoutError:
        print(f"✗ no response within {HANDSHAKE_TIMEOUT_SECONDS}s — the container did not answer")
        return 1
    except Exception as exc:  # noqa: BLE001 - this script's whole job is to report this clearly
        print(f"✗ the handshake failed: {exc!r}")
        return 1

    expected = sorted(TOOL_NAMES)
    if names != expected:
        print(f"✗ tool set mismatch\n    got:      {names}\n    expected: {expected}")
        return 1

    print(f"✓ initialize + tools/list succeeded; all {len(names)} frozen tools present: {names}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
