<!--
title: "About"
description: The architecture decision records behind kaya's design, one line each, and where to read the full reasoning.
-->

# About

kaya behaves the way it does on purpose, and these architecture decision records carry the full
reasoning — the alternatives considered, the trade-offs accepted, and later amendments where a
decision was revisited rather than re-litigated. They're engineering documents rather than user
documentation, so they aren't rendered on this site; each row below links to the real file in the
repository.

| ADR | Decision |
| --- | --- |
| [0001 — Reuse pandan's stack verbatim, with three named deviations](https://github.com/leejianrong/kaya/blob/main/docs/adr/0001-stack-inherited-from-pandan.md) | Same stack as pandan — FastAPI, sync SQLAlchemy over psycopg v3, Postgres, Alembic, Svelte 5, `uv`/`npm`, one deployable artifact — rather than re-deciding a stack pandan had already settled. |
| [0002 — Pandan is the identity provider; kaya resolves tokens by introspection](https://github.com/leejianrong/kaya/blob/main/docs/adr/0002-identity-pandan-as-provider.md) | Superseded by ADR 0012. kaya once resolved every caller by forwarding their bearer to pandan's `GET /api/v1/me`. |
| [0003 — Cross-linking is a soft, one-way read: kaya → pandan, and pandan never learns kaya exists](https://github.com/leejianrong/kaya/blob/main/docs/adr/0003-cross-linking-one-way-soft.md) | kaya reads pandan's public API to resolve `[[KAN-n]]`-style wikilinks. Pandan gains no new capability and carries no awareness that kaya exists. Nothing in kaya may block on pandan, and since ADR 0012 that includes sign-in. |
| [0004 — Payload shaping lives in `kaya-client`, not in the adapters](https://github.com/leejianrong/kaya/blob/main/docs/adr/0004-shaping-lives-in-the-shared-client.md) | Every decision about what a response looks like — projection, truncation, aggregates — lives in the shared `kaya-client` package. An adapter (the CLI, the MCP server) owns only how it gets its arguments. |
| [0005 — The machine-facing contract is designed in from the first CLI slice](https://github.com/leejianrong/kaya/blob/main/docs/adr/0005-born-agent-conformant.md) | The CLI is born with its finished, agent-conformant contract rather than growing one later — `render()`'s signature lands before behavior goes inside it, and the slice order enforces that sequencing. |
| [0006 — The MCP surface is born narrow and frozen, and the CLI↔MCP relationship is pinned by a test](https://github.com/leejianrong/kaya/blob/main/docs/adr/0006-mcp-surface-born-narrow.md) | The MCP server exposes a deliberately narrow, incomplete subset of the CLI's verbs — `MCP ⊆ CLI`, never the reverse — and a test pins that relationship rather than leaving it to convention. |
| [0007 — `--version` identifies the build, and a release refuses to ship an artifact that can't](https://github.com/leejianrong/kaya/blob/main/docs/adr/0007-release-provenance-from-the-first-release.md) | `--version` prints the exact commit a build came from (or says plainly that it's a source checkout), from the CLI's first release onward — a binary that can't say what it is is indistinguishable from stale source. |
| [0008 — A note is identified by an immutable `NOTE-n` ref; its path is mutable metadata](https://github.com/leejianrong/kaya/blob/main/docs/adr/0008-note-identity.md) | A note's identity is its ref, never its path or title. Moving a note is a `PATCH` to one column, with no link rewriting anywhere. |
| [0009 — Concurrent note edits are rejected, not silently merged](https://github.com/leejianrong/kaya/blob/main/docs/adr/0009-optimistic-concurrency-on-note-bodies.md) | Optimistic concurrency on note bodies, enforced server-side via `if_updated_at` — a real conflict returns `409` rather than one writer's edit silently overwriting another's. |
| [0010 — No hosted deployment in the MVP: build the artifact and the manifests, and let the k8s homelab be kaya's first deploy](https://github.com/leejianrong/kaya/blob/main/docs/adr/0010-no-hosted-deploy-until-the-homelab.md) | kaya ships a container and Kubernetes manifests, proven against a local cluster, without standing up a hosted deployment in the MVP. Two later amendments record the maintainer's own independent Fly.io deploy, pursued without waiting on the k8s homelab. |
| [0011 — Team-scoped notes: a second, softer rung under `authorize_note`](https://github.com/leejianrong/kaya/blob/main/docs/adr/0011-team-scoped-notes.md) | A note gains an optional, nullable team-scoped access rung — sourced from a live call to pandan's team membership and allowed to fail soft — alongside the existing single-owner model. |
| [0012 — Standalone identity: kaya becomes its own authorization server](https://github.com/leejianrong/kaya/blob/main/docs/adr/0012-standalone-identity.md) | GitHub sign-in for people and kaya's own `kaya_pat_…` tokens for agents, with no runtime dependency on pandan. Board embeds use a separate, explicitly linked pandan credential. |
| [0013 — Device-flow CLI login and a hosted remote MCP server](https://github.com/leejianrong/kaya/blob/main/docs/adr/0013-device-flow-and-hosted-mcp.md) | `kaya auth login` signs the CLI in through the browser, and the MCP server is also hosted over HTTP, with the stdio package kept as a self-hosting fallback. |
| [0014 — OAuth authorization_code + PKCE grant for hosted MCP clients](https://github.com/leejianrong/kaya/blob/main/docs/adr/0014-oauth-authorization-code-pkce-grant.md) | The grant a browser-based MCP client runs against `/mcp`. It mints an ordinary long-lived token, with no refresh-token rotation. |

## Where else the reasoning lives

The ADRs are the *why*. `docs/PLAN.md` is the slice-by-slice plan they support, and
`docs/ENGINEERING_NOTES.md` carries the full incident and measurement history behind rules that don't
show up in any single ADR — both live in the repository alongside the ADRs themselves, for the same
reason: engineering history, not user-facing documentation.

**[github.com/leejianrong/kaya/tree/main/docs/adr](https://github.com/leejianrong/kaya/tree/main/docs/adr)**
