"""The `kaya-mcp` console script entry point.

One entry point, the same rule ADR 0007 §4 states for the CLI's console script: `kaya_mcp.server.
server` is the one `MCPServer` instance every tool in this package registers onto (six of them,
ADR 0006), and this module's only job is to run it — over stdio, the transport an MCP host
launches a server subprocess with. PLAN §Config's environment tier is how it finds
`KAYA_API_URL`/`KAYA_TOKEN`: a host that launches a server usually exports the `env` block it was
configured with, which is `kaya_client.config`'s tier one (see that module's docstring for why the
nearest `.mcp.json` tier is not built here).
"""

from kaya_mcp.server import server


def main() -> None:
    server.run()


if __name__ == "__main__":  # pragma: no cover - exercised via the console script
    main()
