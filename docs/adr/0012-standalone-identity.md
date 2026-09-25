# ADR 0012 — Standalone identity: kaya becomes its own authorization server

- **Status:** Accepted — **supersedes ADR 0002** ("Pandan is the identity provider; kaya resolves
  tokens by introspection")
- **Date:** 2026-09-25
- **Context source:** Maintainer planning session on CLI/MCP/agent authentication, run jointly across
  pandan and kaya (2026-09-25); pandan ADR 0011 (GitHub cookie sessions), pandan ADR 0014 (self-serve
  PATs), pandan ADR 0024 (device flow + scoped tokens). Tracked as
  [EPIC-283](https://github.com/leejianrong/kaya) on board 18 ("kaya — Notes"), KAN-1738..1742.

## Context

ADR 0002 made kaya deliberately incapable of authenticating anyone on its own: it mints no tokens, has
no OAuth app, and resolves every bearer by asking pandan's `GET /api/v1/me`. That decision correctly
optimized for the product property in play at the time — "one account, one PAT spanning both apps" —
and explicitly rejected full standalone auth for costing "two logins, two tokens... maximum work for
the worst outcome."

The goal has since changed. Kaya is meant to be **a product that runs by itself** — installable,
authenticatable, and operable with zero involvement from pandan. Under that goal, ADR 0002's central
cost (a hard runtime dependency on pandan for cold authentication — the "sharpest cost... accepted
knowingly," per its own Consequences section, and the trigger for two later amendments measuring and
bounding that cost) stops being an acceptable trade. The convenience of one shared credential is being
given up on purpose in exchange for kaya having no dependency on pandan's availability, ever, for any
of its own core functions including login.

## Decision

**Kaya becomes its own identity provider, mirroring pandan's shape rather than sharing its code.**

- **Human login:** GitHub OAuth App (kaya's own, a new registration — not pandan's), `fastapi-users`,
  a second async engine alongside kaya's existing sync one, and revocable DB-backed cookie sessions —
  the same shape as pandan ADR 0011, reimplemented independently in kaya's own codebase.
- **Agent auth:** a `personal_access_token` table of kaya's own, prefixed `kaya_pat_…`, HMAC-hashed,
  with the same `read`/`write` scope split as pandan ADR 0014, plus a Tokens UI. Kaya's PATs are
  **account-wide** — kaya has no board-equivalent entity to scope a token to, so pandan ADR 0024's
  board/workspace allow-list has no analogue here.
- **Reimplemented, not shared.** No common auth package between the two backends. This costs some
  duplicated code but keeps both apps independently releasable — the same value ADR 0002 itself praised
  ("two independently releasable services") and the same reasoning ADR 0002 used to reject a shared
  `AUTH_SECRET`/shared database. Building this from pandan's *pattern*, not pandan's *code*, is
  consistent with how the two apps have related to each other throughout.
- **The introspection path is retired.** `get_principal`'s pandan-forwarding branch, the
  `sha256(token)` TTL cache, the single-flight coalescing (`app/auth/single_flight.py`), and the split
  connect/read deadline (`KAYA_PANDAN_CONNECT_TIMEOUT_SECONDS`/`KAYA_PANDAN_READ_TIMEOUT_SECONDS`) all
  existed solely to make that dependency survivable — they become dead code once kaya authenticates
  itself, and are deleted rather than kept dormant.
- **The embedded pandan-board preview breaks its free ride.** It currently works because the same PAT
  happens to authenticate both apps; once kaya has its own separate login, that preview needs an
  explicit **"connect your Pandan account"** step (a kaya-side record of a pandan PAT/OAuth token the
  user supplies for that one feature) rather than an implicit shared credential.

## Alternatives considered

Restated from ADR 0002, re-evaluated against the changed goal:

| Option | Why not (now) |
|---|---|
| **Keep ADR 0002 unchanged, add standalone login only as an alternate path** | Leaves the hard runtime dependency on pandan in place for every user who doesn't opt into the new path, and keeps two auth systems live in one codebase indefinitely. Rejected as more moving parts for less independence than the goal calls for. |
| **Extract a shared internal auth library both backends depend on** | Would cut the duplication this ADR accepts, but recouples the two apps' release cycles — a shared library means an auth bug fix or dependency bump in one app forces a coordinated release in the other, which is exactly the coupling ADR 0002's own rejected "shared database" option was faulted for, one layer up the stack. |
| **Use pandan as a real federated IdP (kaya offers "Sign in with Pandan" via OAuth, pandan issues the token kaya trusts)** | This is close to a more formal version of what ADR 0002 already did (introspection), and still leaves cold-start login dependent on pandan being reachable — the exact cost this ADR exists to remove. May be worth revisiting later as an *additional* login option, once kaya has its own independent path working. |

## Consequences

- **Positive:** kaya can be installed, deployed, and logged into with no pandan instance running or
  even existing. Removes a whole class of measured, previously-amended failure modes (cold-pandan
  timeouts, stampede coalescing) by deleting the code path that needed them.
- **Neutral:** two GitHub OAuth Apps, two logins, two PATs across the suite — the exact cost ADR 0002
  weighed and rejected, now accepted because independence is the stated goal.
- **Negative / deferred:** the embedded board-preview feature temporarily regresses in convenience
  (an extra connect step) until EPIC-283's card for it lands. `KAYA_PANDAN_*` env vars and the
  introspection code they configure should be removed in the same PR that lands the new auth, not left
  as dead configuration.

## Amendment (2026-09-25): the board-embed reconnect step, shipped (KAN-1741)

The Decision above named the fix without building it. `KAN-1741` builds it: a `pandan_link` table
(one row per `kaya_account`, unique on `user_id`), an `/api/v1/pandan-link` router (`GET`/`POST`/
`DELETE`, gated on `get_principal` — no chicken-and-egg here the way minting kaya's *first* PAT has,
since reaching this route at all already means holding a working kaya credential), and a `/pandan`
SPA page to drive it.

**Encrypted, not hashed — the one place this ADR's own PAT design (hash, never store the secret)
does not apply.** A linked pandan PAT must be handed back to pandan raw on every board-embed render,
so a one-way hash is the wrong primitive; `Fernet`, keyed from `KAYA_AUTH_SECRET` (already doing
double duty for OAuth CSRF signing and kaya's own PAT hashing — this is its third use), is the
smallest honest answer. Rotating that secret invalidates every stored link exactly the way it
already invalidates every cookie session and PAT hash — expected, not a bug.

**Verified before storage.** `POST /api/v1/pandan-link` checks the pasted token against pandan's own
`GET /api/v1/me` (the endpoint this ADR's predecessor, ADR 0002, added to pandan for kaya's own
now-retired resolver — still live and useful standalone) before persisting anything: a rejected
token is a `422`, pandan being unreachable is a `503`, and the two are not conflated (Q9's rule,
mirrored here — a wrong guess about a credential is worse than an honest "couldn't check").

**A caller with no link is a third, distinct outcome from "pandan is unreachable."**
`BoardEmbedResult`/`BoardEmbedResponse` grew a `not_connected` flag, never `true` at the same time as
`unavailable`: the two are actionable differently (go connect an account, versus nothing the caller
can do), and `PreviewPane.svelte` renders a "connect your pandan account" prompt for the first and
the generic "could not be reached" notice for the second.

**Deliberately narrow scope, and the narrowing is recorded rather than hidden.**
`app/integrations/card_resolution.py` (wikilink resolution) forwards the caller's own kaya-side
bearer the exact same way the board-embed preview used to, and has the identical defect — it is
**not** fixed by this amendment. It degrades to "unresolved" rather than failing loudly (ADR 0003),
which made it the lower-priority of the two broken call sites, not an oversight; a future card should
give it the same `pandan_link` lookup this one gave the board-embed preview.
