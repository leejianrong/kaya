# ADR 0013 — Device-flow CLI login and a hosted remote MCP server for kaya

- **Status:** Accepted
- **Date:** 2026-09-25
- **Context source:** Maintainer planning session on CLI/MCP/agent authentication (2026-09-25); ADR
  0012 (standalone identity); pandan ADR 0024 (device flow), pandan ADR 0025 (hosted remote MCP); the
  MCP Authorization spec's stdio-out-of-scope stance (same research basis as pandan ADR 0025). Tracked
  as [EPIC-284](https://github.com/leejianrong/kaya) on board 18 ("kaya — Notes"), KAN-1743..1745.

## Context

ADR 0012 gives kaya its own authorization server. Two onboarding gaps remain, both already solved once
on the pandan side and adopted here as the same pattern rather than shared code, per ADR 0012's
reimplement-not-share stance:

1. `kaya auth login` doesn't exist yet — without it, ADR 0012's new PAT model still requires a human to
   copy a raw secret from a Tokens UI into a config file by hand, the exact friction pandan ADR 0024
   removed on its side.
2. Kaya's MCP server is stdio-transport, same as pandan's was before ADR 0025 — explicitly out of scope
   for the MCP Authorization spec, and reachable only from a client willing to spawn a local subprocess.

## Decision

**Mirror pandan's two ADRs, independently implemented:**

- **`kaya auth login/logout/status`**, an RFC 8628 Device Authorization Grant against kaya's own
  authorization server (ADR 0012) — same mechanics as pandan ADR 0024 (device code + user code +
  polling), same "print a link, open a browser, confirm with a short code" UX. **No board/workspace
  scoping step** in kaya's consent screen — kaya has no board-equivalent entity, so a device-flow-minted
  `kaya_pat_…` is account-wide, matching every PAT kaya mints.
- **A hosted remote MCP endpoint**, Streamable HTTP, implementing RFC 9728 (protected resource
  metadata), RFC 7591 Dynamic Client Registration or its CIMD successor (whichever pandan's EPIC-282
  build settles on, for consistency across the suite), and RFC 8707 resource-indicator token binding —
  the same resource-server shape as pandan ADR 0025, backed by kaya's own authorization server instead
  of pandan's.
- **The existing stdio MCP package stays**, repositioned the same way as pandan's: a documented
  self-hosting/offline fallback, with the hosted endpoint and the CLI as the top-billed options.

## Consequences

- **Positive:** kaya's onboarding story matches pandan's exactly from a user's point of view — same
  commands, same consent-screen shape, same reachability from Claude.ai/ChatGPT/Cursor — while staying
  fully independent underneath, consistent with ADR 0012.
- **Neutral:** this duplicates pandan's device-flow and resource-server implementation rather than
  reusing it, the accepted cost from ADR 0012 extended into this ADR.
- **Negative / deferred:** sequenced after ADR 0012 lands (a device flow needs an authorization server
  to grant against), but not otherwise blocked on pandan's EPIC-281/282 build finishing first — the
  RFC 8628/OAuth 2.1 mechanics are spec-defined, not pandan-implementation-defined, so kaya's build can
  proceed in parallel once ADR 0012's identity layer exists.
