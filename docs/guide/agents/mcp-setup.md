<!--
title: "Connect an agent over MCP"
description: Connect an MCP client to kaya's hosted /mcp endpoint, or run the local stdio server when you self-host.
-->

# Connect an agent over MCP

kaya serves the same six MCP tools two ways. The hosted endpoint is the one to reach for first: it
lives at `/mcp` on your kaya deployment, so there is nothing to install. The local stdio server,
covered [further down](#self-hosting-and-offline-the-stdio-server), is the fallback for
self-hosting and offline work. If your agent would rather shell out, the [CLI](../cli/index.md) is
the other top option, and `kaya auth login` signs it in.

Both servers are thin adapters over `kaya-client`
([ADR 0004](https://github.com/leejianrong/kaya/blob/main/docs/adr/0004-shaping-lives-in-the-shared-client.md))
and expose the same tools. What the tools can and cannot do compared with the CLI is stated once in
[`mcp/README.md`](https://github.com/leejianrong/kaya/blob/main/mcp/README.md).

## The hosted endpoint

The endpoint is `https://<your-kaya-origin>/mcp`, for example `https://kaya-jian.fly.dev/mcp`. It
speaks MCP's Streamable HTTP transport and is authorised with OAuth 2.1
([ADR 0013](https://github.com/leejianrong/kaya/blob/main/docs/adr/0013-device-flow-and-hosted-mcp.md),
[ADR 0014](https://github.com/leejianrong/kaya/blob/main/docs/adr/0014-oauth-authorization-code-pkce-grant.md)).
A client that supports remote MCP only needs the URL:

1. The client calls `/mcp` with no token and gets a `401` whose `WWW-Authenticate` header points at
   the endpoint's protected-resource metadata (RFC 9728).
2. It reads the metadata, finds kaya as the authorization server, and registers itself with
   dynamic client registration (`POST /auth/register`, RFC 7591) or a client ID metadata document.
3. It sends you to `/auth/authorize` in the browser with a PKCE challenge (`S256` only). You sign
   in with GitHub if you are not already, approve the access the client asked for (`write` unless the client requests `read` or
   `write-no-delete`). With `read`, the read tools work and `create_note` and `edit_note` fail with a
   `403`; with `write-no-delete` every write tool works and a delete is refused.
4. The client exchanges the code for a token at the token endpoint and uses it as a bearer.

The token you end up with is an ordinary `kaya_pat_…` token. It does not expire and there is no
refresh token, so the client simply keeps it. It appears under **Settings > Tokens** named
`<client name> (authorization code)`, and revoking it there disconnects that
client.

### Claude Code

```bash
claude mcp add --transport http kaya https://kaya-jian.fly.dev/mcp
```

Add `--scope project` to write it to a `.mcp.json` at your repository root so the whole team gets
it, which produces this entry:

```json
{
  "mcpServers": {
    "kaya": {
      "type": "http",
      "url": "https://kaya-jian.fly.dev/mcp"
    }
  }
}
```

Start Claude Code and run `/mcp` to see the server's status and to sign in. The browser opens for
the approval described above, and the tools appear once you finish.

If you would rather skip the browser, mint a token under Settings > Tokens and pass it as a
header. kaya accepts any valid `kaya_pat_…` bearer on `/mcp`:

```bash
claude mcp add --transport http kaya https://kaya-jian.fly.dev/mcp \
  --header "Authorization: Bearer kaya_pat_…"
```

That writes the token into your Claude Code config, so use the user or local scope and keep it out
of a committed `.mcp.json`.

### Claude desktop and other clients

Use your client's option for adding a remote MCP server by URL. In the Claude apps that is a custom
connector, and the client's own documentation covers where to find it. Give it the `/mcp` URL. A client that only
speaks stdio can run the local server below instead.

Any client that implements the MCP authorization spec, or that lets you set an `Authorization`
header, can connect. See [modelcontextprotocol.io](https://modelcontextprotocol.io) for the
client side of the protocol. The server metadata is public if you want to check what a client will
see:

```
GET /.well-known/oauth-protected-resource/mcp
GET /.well-known/oauth-authorization-server
```

## Self-hosting and offline: the stdio server

`kaya-mcp` is a local process your MCP host launches and talks to over stdio. It holds no state of
its own, so running it is just running a process that can reach a kaya deployment. Use it when you
self-host and would rather not expose `/mcp`, when you work offline against a local stack, or when
a host cannot do remote MCP. Its environment variables and tool behaviour are documented in
[`mcp/README.md`](https://github.com/leejianrong/kaya/blob/main/mcp/README.md).

There's no published package or container image for it yet. `kaya-mcp` isn't on PyPI, and its
Docker image (`mcp/Dockerfile`) is a local build only, proven with `make mcp-image`, never pushed to
a registry. Two ways to run it instead, both from a checkout or a git URL rather than a pulled image.

### Pick how to run it

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
            "KAYA_TOKEN": "kaya_pat_…"
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
            "KAYA_TOKEN": "kaya_pat_…"
          }
        }
      }
    }
    ```

    `--directory ./mcp` is relative to wherever the client launches the server — for Claude Code,
    that's your repository root. Use an absolute path if you launch it from elsewhere.

Claude Code discovers project-scoped servers from a `.mcp.json` at the root of your repository.
Other MCP clients read their own config file, but the server entry is the same shape either way.

### The three settings

The stdio `kaya-mcp` reads exactly what the CLI reads: the same `kaya_client.config` module, the same two
tiers, checked independently per key — environment first, then the user config file
(`~/.config/kaya/config.json`). See [Configuration](../cli/configure.md#where-settings-come-from)
for the full precedence.

| Variable | What it does | Default |
| --- | --- | --- |
| `KAYA_API_URL` | The kaya deployment to talk to. | `http://localhost:8000` — what `make up`/`make dev` serve. |
| `KAYA_TOKEN` | Your `kaya_pat_…` personal access token. | None. Required — missing or wrong gives a `no_credential` refusal or a `401`. |
| `KAYA_MAX_TEXT_CHARS` | How much of a note's `body` a read returns before the truncation hint. `0` disables truncation entirely. | `500` |

!!! tip "Already signed in with the CLI?"

    `kaya-mcp` reads the same config file the CLI writes. If you've already saved a token with
    `kaya auth login` or `kaya config set --token …`, the server picks it up with no `env` block at all — you only need
    to repeat `KAYA_TOKEN` in `.mcp.json` if the file isn't reachable from wherever the host runs
    the server (a container, or a machine with no `$HOME` the process can see), or if you want this
    one server pointed at a different deployment than your CLI's default.

    kaya has no third tier that reads `.mcp.json` directly — that file is your MCP *host's*
    configuration, and it's the host, not kaya, that decides which environment variables the
    subprocess inherits. See [Configuration](../cli/configure.md#where-settings-come-from) for why
    that third tier is named but deliberately not built.

### The server key names your tools

Whatever you call the server in `mcpServers` becomes the namespace for every tool it registers. With
the key `kaya` above, `list_notes` is really `mcp__kaya__list_notes`. A skill, a prompt, or a
`settings.json` allowlist that names a tool has to match whatever key you actually chose.

### Verify it

Restart your client so it reloads its config, approve the server when prompted, then ask it to call
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

1. For a hosted kaya, add `https://<your-kaya-origin>/mcp` as a remote MCP server and approve the
   connection in the browser. In Claude Code that is one `claude mcp add --transport http` line.
2. Self-hosting or offline, install `kaya-mcp` with `uv tool install`, or point your host at
   `uv run --directory ./mcp python -m kaya_mcp` from a checkout, and set `KAYA_API_URL` and
   `KAYA_TOKEN` in the host's `env` block.
3. Ask the client to list your notes.

Next: the [tool reference](mcp-tools.md), or the [workflows](workflows.md) worth handing an agent.
