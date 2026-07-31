# ADR 0002 — Pandan is the identity provider; kaya resolves tokens by introspection

- **Status:** Accepted
- **Date:** 2026-08-01
- **Deciders:** Jian (fork F1, decided from a written options brief)
- **Context source:** [`kaya-vision.md`](../kaya-vision.md) §"The integration contract (settle this
  FIRST)"; pandan ADRs 0011 (cookie sessions), 0013 (one principal, one check), 0014 (PAT format and
  hashing), 0015 (retiring the shared-secret bypass), 0018 §"The PAT prefix".
- **Options brief:** <https://claude.ai/code/artifact/5d18d32d-1277-4f33-8cca-60f9548bbf09>

## Context

The vision doc is emphatic that this decision constrains both apps and must be settled before either
commits to a schema. The product property being bought is narrow and non-negotiable: **one account and
one set of PATs spanning both apps**, so an agent maintains a card's spec note with the same credential
it uses to move the card. Two logins and two tokens would make the suite's central story a
configuration chore.

Three ways to deliver that property were weighed. The reframe that settled it: "standalone or
integrated" is four independent dials, not one switch — who owns the account, who mints tokens, whether
a note reads the board live, and whether either app can boot alone. All three options deliver the same
user-facing property, so they differ almost entirely in **what they cost to change afterwards**.

Two facts were verified rather than assumed, and both shaped the decision:

1. **Pandan has no endpoint that resolves a PAT to a user.** `/users/me` is fastapi-users' route on the
   async cookie path and will not accept a bearer; the PAT branch of `get_principal` guards `/api/v1`
   only. Checked against `backend/app/main.py`'s router mounts. So introspection is not free — it costs
   one small addition to pandan.
2. **`fly.dev` sits on the Public Suffix List**, so two `*.fly.dev` origins cannot share a cookie at
   all. Cookie SSO is gated on hosting, not on this decision.

## Decision

**Pandan is the identity provider. Kaya resolves a caller by asking pandan, and implements no token
format of its own.**

### The resolver

A sync FastAPI dependency, `get_principal`, mirroring the structure of pandan ADR 0013's one-resolver
design:

1. Take the bearer verbatim. **Do not inspect its prefix** (see below).
2. Look up `sha256(raw_token)` in a TTL cache.
3. On a miss, call pandan's `GET /api/v1/me` with the bearer forwarded unchanged.
4. On success, ensure a local `user` mirror row exists keyed on **pandan's user UUID**, creating it
   just-in-time on first sight, and return it.
5. `authorize_note(principal, note)` then allows only the owner — `404` for a note that doesn't exist,
   `403` for one that isn't yours, and list endpoints scoped to the caller rather than silently empty.

**Pandan's side is one endpoint: `GET /api/v1/me`**, returning the resolved user's id and email. It is
sync, reuses `get_principal` unchanged, adds no schema and no secret, and is useful to pandan on its
own — there is currently no way for a PAT holder to ask who it is. Nothing else in pandan changes, and
pandan gains no knowledge that kaya exists.

### Kaya mints nothing

No token table, no Tokens UI, no `kaya_pat_` format. One mint point is what "one set of PATs" means.
The token prefix stays `pandan_pat_` and is **not** re-branded: renaming it would be a forced rotation
for cosmetics, which is the same reasoning that keeps the `KAN-` ticket prefix under the pandan name
(pandan ADR 0018 §"What is deliberately NOT renamed").

### Two traps inherited from pandan ADR 0018, made structural

- **No prefix logic anywhere in kaya.** Pandan still accepts pre-rebrand `kanban_pat_…` tokens via an
  accepted-prefix tuple, and a `startswith` guard on the new prefix alone is precisely the bug that ADR
  had to correct — it would have 401'd every already-issued token. Kaya sidesteps the class of bug
  entirely by having no prefix knowledge to get wrong. Load-shedding against stray `Authorization`
  headers is a **negative cache** (10s) instead, which is the property pandan's guard actually wanted.
- **The cache is keyed on a hash, never the raw token.** A heap dump or an errant log line must not
  yield a live credential. Kaya stores `sha256(raw)` → (user UUID, expiry) and nothing else.

### Failure behaviour

**An unreachable pandan on a cache miss returns `503` with a structured error naming the upstream. It
is never a `401`.** A wrong answer about identity is worse than no answer, and a `401` would send a
client into a token-rotation loop over what is actually an upstream outage. Cached principals continue
to work through a short outage, so an active session survives a pandan restart.

### Deferred, on purpose

- **Browser SSO** (Q7). Needs both apps under one owned apex so a cookie can carry `Domain=.<apex>`;
  `*.fly.dev` cannot. It lands with the homelab (ADR 0010). Crucially, it will **still** not need
  `fastapi-users` in kaya: kaya forwards the cookie to the same `/me` endpoint and lets pandan read its
  own session table.
- **Per-note sharing** (Q8). Owner-only for the MVP. Pandan's board-membership model is the template.

## Alternatives considered

| Option | Why not |
|--------|---------|
| **Shared `AUTH_SECRET` + shared database** — kaya computes the same HMAC and reads pandan's `personal_access_token` table itself | The cheapest to build and the fastest at runtime (one indexed lookup, no hop, instant revocation), and the most expensive to undo. Two services sharing tables makes pandan's auth schema part of kaya's contract, turns an `AUTH_SECRET` rotation into a coordinated two-app outage, forces two Alembic histories to coexist on one database without either autogenerate dropping the other's tables, and ends independent deployability. Exiting it means unpicking shared tables first. |
| **Kaya fully standalone** — own GitHub OAuth App, own users, own PATs | Loses the product property outright: two logins, two tokens, two config blocks, and an agent that must be told which credential opens which door. Also imports `fastapi-users`, a second async engine, a second OAuth App per environment, and the `--proxy-headers` redirect_uri trap. Maximum work for the worst outcome. |
| A separate shared auth service both apps call | Cleaner in the abstract, more infrastructure than a two-app suite justifies, and it is where introspection *evolves* to if it ever needs to. Building it now is speculative. |
| Kaya accepts pandan-signed JWTs instead of introspecting | No revocation without a second mechanism, which is the thing pandan deliberately chose DB-backed sessions to get (ADR 0011). Trades an HTTP hop for a revocation problem. |

## Consequences

- **Positive:** one account, one PAT, one mint point, and **two independently releasable services**.
  Kaya has no auth secrets of its own, no token format to get wrong, and no async engine (ADR 0001).
  The exit is a single endpoint swap, which is what makes this the reversible option. Pandan gains a
  `/me` endpoint it was missing.
- **Neutral:** pandan takes one ~20-line change, so kaya's V1 is not strictly zero-touch on the sibling.
  A cache miss costs an HTTP round trip; steady state is a dictionary lookup.
- **Negative / deferred:** **revocation lags by up to the cache TTL** (60s assumed, Q6). For a
  single-maintainer suite that is a good trade for the request-path saving, and it is tunable in one
  place — lower the TTL, or have pandan push revocations, if it ever matters. Kaya now has a **runtime
  dependency on pandan for cold authentication**: an agent whose token isn't cached cannot start work
  while pandan is down. This is the sharpest cost of the decision and it is accepted knowingly; note
  that it is bounded to *authentication*, and ADR 0003 keeps *everything else* in kaya independent of
  pandan's availability.
- **Now has to be true:** pandan ships `GET /api/v1/me` before kaya's V1 can be demonstrated. That is a
  V1 build step, tracked on the board.
