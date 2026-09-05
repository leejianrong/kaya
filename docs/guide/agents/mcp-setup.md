<!--
title: "Set up the MCP server"
description: What kaya-mcp needs to run, how to point an MCP host at it, and how to verify the connection.
-->

# Set up the MCP server

`kaya-mcp` is a thin adapter over `kaya-client`
([ADR 0004](https://github.com/leejianrong/kaya/blob/main/docs/adr/0004-shaping-lives-in-the-shared-client.md)).
It holds no state of its own — running it is just running a process that can reach a kaya
deployment, over stdio, the transport an MCP host launches a server subprocess with.

There's no published package or container image for it yet. `kaya-mcp` isn't on PyPI, and its
Docker image (`mcp/Dockerfile`) is a local build only, proven with `make mcp-image`, never pushed to
a registry. Two ways to run it instead, both from a checkout or a git URL rather than a pulled image.

## Pick how to run it

=== "uv tool install"

    Needs [uv](https://docs.astral.sh/uv/) but no checkout kept around afterwards. `uv` clones the
    repository once to resolve `kaya-mcp`'s sibling `kaya-client` dependency, installs the
    `kaya-mcp` console script, and discards the clone — the same trick
    [get started](../get-started/index.md#install-the-cli) uses for the CLI itself:

    ```bash
    uv tool install "git+https://github.com/leejianrong/kaya.git#subdirectory=mcp"
    ```

    ```json
    {
      "mcpServers": {
        "kaya": {
          "command": "kaya-mcp",
          "env": {
            "KAYA_API_URL": "https://kaya-jian.fly.dev",
            "KAYA_TOKEN": "pandan_pat_…"
          }
        }
      }
    }
    ```

=== "From a checkout"

    Needs a clone of the repository and [uv](https://docs.astral.sh/uv/). Runs straight out of
    `mcp/`, so there's nothing to build or install first:

    ```json
    {
      "mcpServers": {
        "kaya": {
          "command": "uv",
          "args": ["run", "--directory", "./mcp", "python", "-m", "kaya_mcp"],
          "env": {
            "KAYA_API_URL": "https://kaya-jian.fly.dev",
            "KAYA_TOKEN": "pandan_pat_…"
          }
        }
      }
    }
    ```

    `--directory ./mcp` is relative to wherever the client launches the server — for Claude Code,
    that's your repository root. Use an absolute path if you launch it from elsewhere.

Claude Code discovers project-scoped servers from a `.mcp.json` at the root of your repository.
Other MCP clients read their own config file, but the server entry is the same shape either way.

## The three settings

`kaya-mcp` reads exactly what the CLI reads: the same `kaya_client.config` module, the same two
tiers, checked independently per key — environment first, then the user config file
(`~/.config/kaya/config.json`). See [Configuration](../cli/configure.md#where-settings-come-from)
for the full precedence.

| Variable | What it does | Default |
| --- | --- | --- |
| `KAYA_API_URL` | The kaya deployment to talk to. | `http://localhost:8000` — what `make up`/`make dev` serve. |
| `KAYA_TOKEN` | Your `pandan_pat_…` personal access token. | None. Required — missing or wrong gives a `no_credential` refusal or a `401`. |
| `KAYA_MAX_TEXT_CHARS` | How much of a note's `body` a read returns before the truncation hint. `0` disables truncation entirely. | `500` |

!!! tip "Already run `kaya config set`?"

    `kaya-mcp` reads the same config file the CLI writes. If you've already saved a token with
    `kaya config set --token …`, the server picks it up with no `env` block at all — you only need
    to repeat `KAYA_TOKEN` in `.mcp.json` if the file isn't reachable from wherever the host runs
    the server (a container, or a machine with no `$HOME` the process can see), or if you want this
    one server pointed at a different deployment than your CLI's default.

    kaya has no third tier that reads `.mcp.json` directly — that file is your MCP *host's*
    configuration, and it's the host, not kaya, that decides which environment variables the
    subprocess inherits. See [Configuration](../cli/configure.md#where-settings-come-from) for why
    that third tier is named but deliberately not built.

## The server key names your tools

Whatever you call the server in `mcpServers` becomes the namespace for every tool it registers. With
the key `kaya` above, `list_notes` is really `mcp__kaya__list_notes`. A skill, a prompt, or a
`settings.json` allowlist that names a tool has to match whatever key you actually chose.

## Verify it

Restart your client so it reloads `.mcp.json`, approve the server when prompted, then ask it to call
a tool. In Claude Code:

> Use the kaya tools to list my notes.

Seeing your notes back (or `no notes` if you have none yet) proves the token resolved and the server
can reach your deployment. If nothing comes back:

| Symptom | Cause |
| --- | --- |
| Tools don't appear at all | The client hasn't reloaded, or `.mcp.json` is invalid JSON — check for a trailing comma. |
| A tool-level error naming `no_credential` | `KAYA_TOKEN` isn't set in the `env` block, and isn't visible to the server process through the config file either. |
| A tool-level error naming `401` | The token is wrong or revoked. |
| Connection refused | Wrong `KAYA_API_URL` — the default assumes `make up`/`make dev` is running on `localhost:8000`. |

## Recap

1. Install with `uv tool install`, or point your host at `uv run --directory ./mcp python -m
   kaya_mcp` from a checkout.
2. Set `KAYA_API_URL` and `KAYA_TOKEN` in the host's `env` block — or skip the token if the server
   process can already see the config file `kaya config set` wrote.
3. Restart your client, approve the server.
4. Ask it to list your notes.

Next: the [tool reference](mcp-tools.md), or the [workflows](workflows.md) worth handing an agent.
