# ADR 0014 — OAuth authorization_code + PKCE grant for hosted MCP clients

- **Status:** Accepted
- **Date:** 2026-09-26
- **Context source:** ADR 0012 (standalone identity), ADR 0013 (device-flow CLI login + hosted MCP)
  — this ADR fills a gap ADR 0013 left open, the identical shape pandan hit and resolved in its own
  ADR 0026 (mirrored independently per ADR 0012's reimplement-not-share stance — same gap, same fix,
  two codebases). Discovered while building KAN-1744: EPIC-284's hosted-MCP card turned out to be
  unbuildable without it. Tracked against EPIC-284 on board 18 ("kaya — Notes"), KAN-1744.

## Context

ADR 0013 built an RFC 8628 **Device Authorization Grant** for the CLI (`kaya auth login`, KAN-1743)
and specified a hosted remote MCP endpoint (RFC 9728 discovery, RFC 7591 DCR, RFC 8707 resource
binding) — but, like pandan's ADR 0025 before its own ADR 0026 amendment, it named only the
**resource-server** half of hosting that endpoint and silently assumed an authorization-server flow
already existed behind it. It doesn't: device flow has no redirect target and cannot be what a
browser-embedded client (Claude.ai, ChatGPT, Cursor's remote-MCP mode) completes. Every RFC 9728/7591
piece of KAN-1744 is otherwise buildable, but a client that discovers kaya's authorization server has
no grant it can actually run against it — the identical gap pandan's own build hit, caught the same
way: escalated into a new ADR rather than improvised inline.

## Decision

**Add a standard OAuth 2.1 authorization_code + PKCE grant, reusing KAN-1743's consent screen and
`personal_access_token` table, with one deliberate simplification from pandan's own ADR 0026:**

- **`GET /auth/authorize`** — `response_type=code`, `client_id` (DCR-registered or a CIMD URL),
  `redirect_uri`, `code_challenge` + `code_challenge_method=S256` (**mandatory** — OAuth 2.1 drops
  `plain` entirely), `resource` (RFC 8707, the MCP endpoint's canonical URI), `scope`, `state`.
  Requires an existing GitHub-OAuth cookie session (ADR 0012); an unauthenticated visitor reaches
  `/device`'s sign-in prompt first, same as the device flow's consent screen already does.
- **`redirect_uri` validated by exact match only** against the client's registered URI list — no
  wildcard, no prefix. Getting this wrong is an open redirect (RFC 6749 §4.1.2.1); an unknown
  `client_id` or an unregistered `redirect_uri` is answered directly, never delivered via a redirect
  to that same untrusted URI.
- **The consent screen is `DeviceApproval.svelte`, unchanged in kind**, reached via a second entry
  path (`?client_id=&redirect_uri=…` alongside device flow's `?user_code=`) rather than rebuilt — no
  board/workspace picker to reuse (kaya has none), so this path is strictly simpler than pandan's:
  scope choice only.
- **Approval mints a short-lived, single-use authorization `code`** (≤60s), bound to the
  `code_challenge`, `redirect_uri`, `resource` and the approved scope — extending
  `device_authorization` (KAN-1743) with the columns pandan's identical row shape already proved out,
  rather than a parallel table. Redirects back to `redirect_uri` with `?code=&state=`.
- **`POST /auth/device/token` gains `grant_type=authorization_code`**: takes `code`, `redirect_uri`,
  `client_id`, `code_verifier`, `resource`; verifies PKCE (`SHA256(code_verifier) == code_challenge`),
  the exact `redirect_uri`/`resource` match, then mints a token. This is where RFC 8707 binding
  actually happens — ADR 0013 named the requirement, this is its enforcement point.
- **Client registration is both RFC 7591 DCR (`POST /auth/register`) and Client ID Metadata Documents
  (CIMD)**, resolved through one function regardless of which produced the client — matching pandan's
  own build exactly, and settling ADR 0013's "whichever pandan settles on" the same way pandan itself
  settled it: not a single answer, both mechanisms, DCR as the required baseline (every current MCP
  client but Claude.ai is DCR-only) and CIMD layered on top for callers that support it.

### The deliberate simplification: no refresh-token rotation

Pandan's ADR 0026 pairs this grant with **short-lived access tokens + rotating, single-use refresh
tokens** (a new `oauth_refresh_token` table), because an OAuth-issued token there is deliberately
shorter-lived than a Tokens-UI/device-flow PAT. Kaya does not build that half.

**A token minted by this grant is an ordinary, long-lived `kaya_pat_…`** — the exact same
`app.identity.pat.generate_token` call `POST /auth/device/token`'s device-code branch already makes
(KAN-1743), with no `expires_at` and no paired refresh token. This is not an oversight; it is kaya's
existing PAT model (ADR 0012) applied without a special case: every kaya credential is long-lived
until explicitly revoked, and inventing a second, shorter-lived credential shape for exactly one
minting path would be the same kind of token-model fragmentation ADR 0012's "one credential type"
posture already refuses elsewhere. The response omits `expires_in`/`refresh_token` entirely — both
are OPTIONAL in RFC 6749 §5.1, and their absence is a spec-legal way to say "this token does not
expire," which a compliant client tolerates by simply keeping the token it was given.

### A necessary, narrow exception to ADR 0001's dependency arrow

Hosting `kaya-mcp`'s Streamable HTTP transport on kaya's own backend (the same single-origin
deploy shape ADR 0010 already commits to) means `backend` imports `kaya_mcp.server.server` — the
same `MCPServer` instance and its six registered tools the stdio transport already runs unchanged.
That is a real, if narrow, exception to "nothing depends on an adapter": `kaya-mcp` is normally
consumed only by whatever process launches it as a subprocess, never imported by `backend` or
`kaya-client`.

It is accepted here rather than avoided, for the same reason pandan's own identical build
(`backend/app/mcp_host.py` importing `pandan_mcp.server`) accepted it: there is no way to host an
existing tool registry over HTTP on this process without importing that registry, and building a
*second*, duplicate tool registration inside `backend` for the hosted case alone would be exactly
the kind of drift ADR 0004 exists to prevent, one layer over. The dependency is one-directional and
narrow — `backend/app/identity/mcp_host.py` is the only file that imports anything from `kaya_mcp`,
and what it imports is the finished server object and its own request-scoped auth bridge
(`kaya_mcp.request_auth`), never anything from `kaya-cli`. `kaya-client` itself gains no new
dependency; the arrow ADR 0004 actually cares about (adapters depend on the client, never the
reverse) is untouched.

## Consequences

- **Positive:** KAN-1744 is now fully specified — transport, RFC 9728/8414 discovery, RFC 7591 DCR +
  CIMD, and RFC 8707 binding all have a concrete grant to run against. The consent screen and PAT
  model are reused rather than duplicated a second time.
- **Neutral:** `POST /auth/device/token` now serves two grant types (`device_code` from ADR 0013,
  `authorization_code` from this ADR) behind one endpoint, differentiated by `grant_type` — standard
  OAuth practice, not a divergence from spec.
- **Negative / deferred:** no refresh-token rotation means a revoked/leaked hosted-MCP token has the
  same lifetime as any other kaya PAT — revoke it from the Tokens UI, the same remedy every other
  kaya credential already has, rather than a rotation window catching it sooner. If a real incident
  ever shows that gap mattering in practice, revisit this ADR; nothing here is one-way. This ADR does
  not resolve DCR vs. CIMD as a preference either, matching pandan's own ADR 0026 — both are built,
  and `resolve_client` doesn't care which produced a given `client_id`. Also deferred: pandan's own
  `personal_access_token.oauth_client_id` FK (so the Tokens UI can identify/bulk-revoke every token
  a specific connected app minted) is not built here — an authorization_code-minted `kaya_pat_…`
  already carries a distinguishing `name` (`"{client name} (authorization code)"`), which is enough
  for a human reading the Tokens UI to tell it apart and revoke it individually; a `client_id`-keyed
  bulk operation is additive whenever a real need for one shows up.
