<!--
title: "Agents and MCP"
description: The two ways an agent reaches kaya, the hosted MCP endpoint and the CLI, plus the stdio server for self-hosting.
-->

# Agents and MCP

kaya ships two ways for a program to reach it: the CLI (`kaya`) and an MCP server, which runs hosted
on kaya's own origin or as a local process (`kaya-mcp`). All of them are adapters over the same
package, `kaya-client`, the one place that opens an HTTP session, shapes
a response and turns a failure into a structured object
([ADR 0004](https://github.com/leejianrong/kaya/blob/main/docs/adr/0004-shaping-lives-in-the-shared-client.md)).

## What that buys an MCP host

Because the adapter is thin, an MCP tool call gets three things by construction rather than by a
follow-up patch:

- **`fields`** — narrow a read to the columns you actually want, the same projection
  `kaya note list --fields ref,title` applies.
- **Truncation** — long prose (a note's `body`) is cut at `KAYA_MAX_TEXT_CHARS` (500 characters by
  default) with a hint saying how much was dropped, resolved the same way for a tool call as for a
  CLI invocation.
- **The `{"count": n}` aggregate** — every list-shaped tool result carries the size of the set it
  actually returned, so a caller never has to count rows to answer "how many did I get back?"

None of that is MCP-specific code. It's `render()`, the one function every result in kaya passes
through, called from `kaya_mcp.server` the same way `kaya_cli.__main__.main` calls it for the CLI
([ADR 0006](https://github.com/leejianrong/kaya/blob/main/docs/adr/0006-mcp-surface-born-narrow.md)).
An MCP tool that had to reimplement projection or truncation would be the thing ADR 0004 exists to
prevent.

## The direction: `MCP ⊆ CLI`

The relationship between the two surfaces is `MCP ⊆ CLI`. The argument, the tool-to-verb mapping and
the test that pins it live in one canonical place:
[`mcp/README.md`](https://github.com/leejianrong/kaya/blob/main/mcp/README.md). Read it before
assuming MCP can do something the CLI can't. This page and the next three link to it rather than
restating it.

## Your options

<div class="grid cards" markdown>

-   **Hosted MCP endpoint**

    For an agent host that speaks [MCP](https://modelcontextprotocol.io) over HTTP. Point it at
    `/mcp` on your kaya deployment, approve the connection in a browser once, and there is nothing
    to install. Six tools, one per `KayaClient` read or write.

    [Connect to it](mcp-setup.md)

-   **The CLI**

    For an agent that shells out, or a script. Every verb the API has, not only the six the MCP
    surface froze. `kaya auth login` signs it in through a browser.

    [CLI guide](../cli/index.md)

-   **The stdio MCP server**

    A local `kaya-mcp` process the host launches. It is the fallback for self-hosting, offline use
    and hosts that cannot do remote MCP.

    [Set it up](mcp-setup.md#self-hosting-and-offline-the-stdio-server)

</div>

Start with the hosted endpoint if your host supports remote MCP, and with the CLI if your agent can
run shell commands. All three reach the same notes with the same shaping, so which one you use
changes how many of kaya's verbs you can reach, not what you're allowed to do. Some setups want
both: an agent that mostly calls MCP tools can still shell out to the CLI for the handful of verbs
that never became one of the six.

## Authentication

kaya mints and checks its own credentials, and pandan is not involved
([ADR 0012](https://github.com/leejianrong/kaya/blob/main/docs/adr/0012-standalone-identity.md)).
A person signs in to the web app with GitHub. An agent uses a `kaya_pat_…` personal access token,
which is account-wide and has a `read` or `write` scope. There are three ways one gets minted:

- `kaya auth login` runs a device flow in your browser and stores the token for the CLI
  ([ADR 0013](https://github.com/leejianrong/kaya/blob/main/docs/adr/0013-device-flow-and-hosted-mcp.md)).
- A hosted MCP client runs an OAuth authorization code flow with PKCE and keeps the token it is
  given ([ADR 0014](https://github.com/leejianrong/kaya/blob/main/docs/adr/0014-oauth-authorization-code-pkce-grant.md)).
- You create one by hand under **Settings > Tokens** in the web app, which is also where you revoke
  any of them.

Every one of these is an ordinary long-lived token. There is no refresh token and no expiry, so a
token you no longer trust has to be revoked under Settings > Tokens. Mint or connect one token per
agent if you want to revoke them independently. See [get started](../get-started/index.md#sign-in)
for the sign-in steps.

pandan is optional. If you link a pandan account under Settings > Pandan connection, board embeds
and `[[KAN-n]]` wikilink resolution use that separate credential. Without it, kaya works the same
and card links render as unresolved.

## Next

<div class="grid cards" markdown>

-   **[Connect an agent over MCP](mcp-setup.md)**

    The hosted endpoint first, then the stdio server for self-hosting.

-   **[Tool reference](mcp-tools.md)**

    The six tools, what each does, and their `fields`/truncation behavior.

-   **[Agent workflows](workflows.md)**

    Searching, reading backlinks, and where MCP hands off to the CLI.

</div>
