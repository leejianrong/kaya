# ADR 0016 — Short-lived access tokens with rotating refresh tokens

- **Status:** Accepted
- **Date:** 2026-10-11
- **Deciders:** Jian
- **Context source:** the 2026-10-11 auth-parity discussion (EPIC-326 on board 18, cards KAY-171 to
  KAY-173). Amends [ADR 0014](0014-oauth-authorization-code-pkce-grant.md), which chose long-lived
  tokens on purpose, and [ADR 0013](0013-device-flow-and-hosted-mcp.md). Mirrors pandan
  [ADR 0026](https://github.com/leejianrong/pandan/blob/main/docs/adr/0026-oauth-authorization-code-pkce-grant.md)
  for the token side, and goes one step past it for the CLI (below).

## Context

ADR 0014 declined pandan's rotating refresh tokens: every kaya credential was a long-lived
`kaya_pat_…` until revoked, and "one credential type" was the reason. It also said to revisit if a
real need showed up. The maintainer now wants no long-lived credential minted by an interactive flow.
A leaked CLI config or MCP client token should stop working on its own.

Two facts about pandan matter, because "mirror pandan" is the working rule:

1. Pandan issues short-lived tokens (1 hour access, 30 day refresh, single-use rotation) only from its
   `authorization_code` grant. Its device flow (the CLI login) still mints a non-expiring PAT, and the
   pandan client has no refresh code at all.
2. Tokens-UI PATs in pandan never expire unless the user sets `expires_at`. They are the intended
   credential for scripts and CI.

## Decision

**Every token minted by an interactive grant is short-lived and comes with a rotating refresh token.
Manual PATs stay as they are.**

- **Both grants.** `authorization_code` (the hosted `/mcp` clients) and `device_code` (`kaya auth login`)
  mint an access token and a refresh token. The CLI case goes beyond pandan; the token side is a direct
  copy.
- **Access token** is an ordinary `personal_access_token` row, so `get_principal` is unchanged, with
  `expires_at = now + 1 hour`. Scope (`read`, `write`, `write-no-delete`) is fixed at consent and a
  refresh can never widen it.
- **Refresh token**: new table `oauth_refresh_token`, mirroring pandan's `OAuthRefreshToken`. `token_hash`
  is HMAC-SHA256 keyed with `KAYA_AUTH_SECRET`, as for a PAT. It points at its current
  `personal_access_token` with `ON DELETE CASCADE`, so revoking a token in Settings also kills its
  refresh token. It carries `client_id`, `expires_at` (30 days) and `consumed_at`.
- **Rotation, single use.** `POST /auth/device/token` with `grant_type=refresh_token` consumes exactly
  one row, stamps `consumed_at`, and inserts a fresh PAT and a fresh refresh row. A consumed token fails
  on a second use. The old access token is left to expire; it is not force-revoked.
- **`client_id` is re-checked on every refresh.** A refresh token works only for the client it was issued
  to. The device flow has no registered client, so its tokens use the fixed literal `kaya-cli`.
- **A refresh token has a prefix, `kaya_rt_`.** This departs from pandan, whose refresh token is a bare
  string. Kaya's log scrubber (`app/observability/redaction.py`) and the secret scan recognise
  credentials by pattern, and a bare string would be invisible to both. `redaction.py`'s pattern and the
  gitleaks rules are extended in the same card as the table.
- **Manual PATs are unchanged.** The Tokens UI still mints `kaya_pat_…` with an optional expiry, for
  scripts and CI. Existing long-lived tokens stay valid until revoked. Nothing is migrated or expired.
- **The SPA needs no change.** It authenticates every call with its `kayaauth` cookie and never mints a
  token: `App.svelte` only reads `GET /users/me` on mount, and `lib/auth.ts`'s bearer seam holds only a
  token a person pasted on the Tokens page, which is a manual PAT and unaffected. (This ADR first said
  the SPA silently minted a `kaya_pat_…` on load. It stopped doing that before this ADR was written;
  the claim came from a stale comment in `app/identity/backend.py`, corrected with this amendment.)
- **Discovery.** The RFC 8414 metadata lists `refresh_token` in `grant_types_supported`, and the token
  response carries `expires_in` and `refresh_token`.

### The CLI refreshes itself, under a lock

A single-use rotation has a failure mode a plain PAT does not: two processes holding the same refresh
token both try to rotate it, the second one fails, and the user is logged out. A CLI used from several
shells, or the CLI beside a local MCP server sharing one config file, will hit this.

`kaya-client` therefore refreshes transparently, once, on a `401 invalid_token`, and does it under a
cross-process file lock beside the config file. The holder of the lock re-reads the config before
refreshing; if another process has already rotated, it uses the new token instead of rotating again.
The refresh token is written to the config with the same read-modify-write and permissions as the access
token and is never printed (`config show` prints `set`/`not set`). The refresh logic lives in
`kaya-client` only, per ADR 0004; the CLI and MCP adapters gain nothing.

## Consequences

- **Positive:** a stolen token is useful for at most an hour, and a stolen refresh token for at most one
  use before the real client's next refresh exposes the theft. The hosted MCP gets standard OAuth
  behaviour that Claude.ai and Cursor already handle.
- **A breaking change for old CLIs.** A CLI that does not know about refresh would store the one-hour
  access token and fail an hour later, and logging in again would give it the same one-hour token.
  So the client change ships and is released **before** the server starts issuing short tokens, and the
  CLI's release notes say to upgrade. A `kaya` older than that release is unusable after login, by
  design. The maintainer is the only known user, so this is accepted rather than gated behind a flag.
- **Reuse detection is pandan's, not stronger.** A reused refresh token fails; it does not revoke the
  family. RFC 9700 recommends revoking the family. That is deferred, because with the file lock a
  legitimate race should be rare, and a family revocation would turn any remaining race into a full
  logout. Revisit if a real theft or a real race shows up.
- **Per-process storage is not involved.** Everything is in Postgres, so rotation is correct across
  Fly machines, unlike the rate limiter (KAY-169).
- **Cost:** one table, one migration, and a lock in the client. `kaya-client`, `kaya-cli` and `mcp`
  each bump a version (ADR 0007).

## Alternatives considered

- **Keep long-lived tokens and add expiry to them.** Rejected: that is a worse refresh token. It forces a
  human through consent every time one lapses.
- **Short-lived for `/mcp` only, matching pandan exactly.** Rejected by the maintainer's explicit
  instruction. The CLI config file is the credential most likely to leak (dotfiles, backups, screen
  shares).
- **Revoke the whole family on reuse.** See above; deferred, not rejected.
- **A grace window that accepts the just-consumed token for a few seconds.** Rejected: it weakens the
  single-use property to paper over a race the file lock already solves.
