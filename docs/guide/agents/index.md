<!--
title: "Agents and MCP"
description: How kaya's MCP server shares kaya-client's payload shaping with the CLI, and how to choose between the two.
-->

# Agents and MCP

kaya ships two ways for a program to reach it: the CLI (`kaya`) and an MCP server (`kaya-mcp`). Both
are adapters over the same package, `kaya-client` — the one place that opens an HTTP session, shapes
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

kaya's MCP server exposes six tools; the CLI has nine verb groups, several with sub-verbs of their
own. Every MCP tool has a CLI verb behind it, deliberately never the other way round — the full
argument, the tool-to-verb mapping, and the test that proves it live in one canonical place:
[`mcp/README.md`](https://github.com/leejianrong/kaya/blob/main/mcp/README.md). Read it before
assuming MCP can do something the CLI can't. This page and the next three link to it rather than
restating it.

## Two ways in

<div class="grid cards" markdown>

-   **MCP server**

    For an agent host that speaks [MCP](https://modelcontextprotocol.io) — Claude Code, Claude
    Desktop, or anything else with an MCP client. Six tools, one per `KayaClient` read or write.

    [Set it up](mcp-setup.md)

-   **The CLI**

    For an agent that shells out, or a script. Every verb the API has, not only the six the MCP
    surface froze.

    [CLI guide](../cli/index.md)

</div>

Both read the same configuration and accept the same pandan token, so nothing about which one you
use changes what you're allowed to do — only how many of kaya's verbs you can reach without a shell.
Some setups want both: an agent that mostly calls MCP tools can still shell out to the CLI for the
handful of verbs that never became one of the six.

## Authentication

An agent authenticates with a pandan personal access token, the same `pandan_pat_…` secret a human
pastes into `kaya config set --token`. kaya has no login of its own and no agent-specific credential
type
([ADR 0002](https://github.com/leejianrong/kaya/blob/main/docs/adr/0002-identity-pandan-as-provider.md))
— every request is forwarded to pandan's `GET /api/v1/me` and trusted or refused based on pandan's
answer. Mint a token per agent from pandan's Tokens tab if you want to revoke one independently of
the others; see [get started](../get-started/index.md#get-a-token) for how.

## Next

<div class="grid cards" markdown>

-   **[Set up the MCP server](mcp-setup.md)**

    What the server needs to run, and a worked host config.

-   **[Tool reference](mcp-tools.md)**

    The six tools, what each does, and their `fields`/truncation behavior.

-   **[Agent workflows](workflows.md)**

    Searching, reading backlinks, and where MCP hands off to the CLI.

</div>
