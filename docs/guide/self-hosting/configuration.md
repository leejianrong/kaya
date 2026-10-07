<!--
title: "Configuration"
description: Every environment variable backend/app/config.py's Settings reads, its default, and what it does.
-->

# Configuration

Every setting kaya reads lives in one place, `backend/app/config.py`'s `Settings` class, and this
page mirrors it field for field. Two variables matter to get right before a real deployment;
everything else has a sensible default and exists to tune a specific timeout or feature.

`DATABASE_URL` is deliberately unprefixed — it's the name Alembic, `docker-compose.yml` and the test
fixtures already use. Every other application setting carries a `KAYA_` prefix.

## Set these for a real deployment

| Variable | Default | Why it matters |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+psycopg://kaya:kaya@localhost:5432/kaya` | Point this at your own Postgres. The `+psycopg` suffix selects psycopg v3 — [ADR 0001](https://github.com/leejianrong/kaya/blob/main/docs/adr/0001-stack-inherited-from-pandan.md) pins it, and it is not interchangeable with `+psycopg2`. |
| `KAYA_GITHUB_OAUTH_CLIENT_ID` | unset | Client id of your own GitHub OAuth App. Its callback URL is `<origin>/auth/github/callback`. Not shared with pandan's App. Unset means the GitHub sign-in routes don't register and nobody can sign in through the browser. |
| `KAYA_GITHUB_OAUTH_CLIENT_SECRET` | unset | Paired with the id above. A credential, never logged. Both must be set to enable sign-in. |
| `KAYA_AUTH_SECRET` | an insecure development value | Signs the OAuth state token and session cookies, and peppers the hash of every `kaya_pat_…` token. Set a long random value (at least 32 characters, for example `openssl rand -hex 32`) in production. Rotating it invalidates every cookie session and every token. |
| `KAYA_COOKIE_SECURE` | off | `1` or `true` marks the session cookie `Secure`. Set it when you serve over HTTPS. It also marks the deployment as production: with it on, kaya refuses to start while `KAYA_AUTH_SECRET` is the insecure default or shorter than 32 characters, and logs a CRITICAL line (never the value) when the GitHub OAuth id or secret is unset. |

kaya mints its own tokens and verifies them against its own tables
([ADR 0012](https://github.com/leejianrong/kaya/blob/main/docs/adr/0012-standalone-identity.md)),
so authentication never calls pandan and no setting here points at an identity provider.

`make up` forwards exactly two variables into the container, `DATABASE_URL` and `KAYA_PANDAN_URL`,
via `docker-compose.yml`'s `app.environment:` block. Every other field below, including the GitHub
and auth settings above, silently takes its default under `make up`, however you've exported it in
your shell. To sign in, or to exercise any other setting, run the backend directly
(`cd backend && KAYA_… uv run uvicorn app.main:app --port 8000`) or set it in your own
deployment's environment.

## pandan (optional)

pandan is an optional integration. Setting `KAYA_PANDAN_URL` only tells kaya where to find a pandan
instance if a user chooses to use one.

| Variable | Default | What it does |
| --- | --- | --- |
| `KAYA_PANDAN_URL` | `https://simple-kanban-jian.fly.dev` (the maintainer's own hosted pandan) | The pandan instance kaya calls for board embeds, `[[KAN-n]]` wikilink resolution and team-default access. Each degrades to "unresolved" or "not found" when pandan is missing or down, and a note always saves and renders. It is not a secret. |
| `KAYA_PANDAN_LINK_CONNECT_TIMEOUT_SECONDS` | `3.0` | Connect budget for checking a pandan token a user pastes under Settings > Pandan connection. kaya verifies it against pandan before storing it. |
| `KAYA_PANDAN_LINK_READ_TIMEOUT_SECONDS` | `3.0` | Read budget for the same check. |

A user opts in by pasting a pandan personal access token under **Settings > Pandan connection**
(the `/pandan` page). kaya stores it encrypted, keyed from `KAYA_AUTH_SECRET`, because it has to hand
the token back to pandan unchanged. That linked credential is separate from the user's kaya tokens
and is the only one kaya ever sends to pandan. A user who never links an account sees card
wikilinks as unresolved and a "connect your pandan account" prompt in place of a board embed.

## Team access (R16, ADR 0011)

| Variable | Default | What it does |
| --- | --- | --- |
| `KAYA_TEAM_ACCESS_CONNECT_TIMEOUT_SECONDS` | `3.0` | Connect budget for resolving a caller's team memberships against pandan's `GET /api/v1/workspaces`, using the caller's linked pandan token. Short, because team-default access is a softer dependency; a teammate's access degrading to "not found" during a slow pandan is accepted, not worth waiting out. |
| `KAYA_TEAM_ACCESS_READ_TIMEOUT_SECONDS` | `3.0` | Read budget for the same call. |
| `KAYA_TEAM_ACCESS_CACHE_TTL_SECONDS` | `60.0` | How long a resolved membership set is trusted. |
| `KAYA_TEAM_ACCESS_NEGATIVE_CACHE_TTL_SECONDS` | `10.0` | How long "pandan couldn't be asked" is remembered before trying again — decays to "no memberships", not a rejection. |

## Wikilink card/epic resolution (R5, KAN-564)

Budgets for resolving `[[KAN-n]]` / `[[EPIC-n]]` wikilinks against pandan when rendering a note.
A render must return promptly with an unresolved link rather than wait on a slow or sleeping pandan
([ADR 0003](https://github.com/leejianrong/kaya/blob/main/docs/adr/0003-cross-linking-one-way-soft.md) —
"slow is worse than down").

| Variable | Default | What it does |
| --- | --- | --- |
| `KAYA_CARD_RESOLUTION_CONNECT_TIMEOUT_SECONDS` | `3.0` | Per-request connect budget. |
| `KAYA_CARD_RESOLUTION_READ_TIMEOUT_SECONDS` | `3.0` | Per-request read budget. |
| `KAYA_CARD_RESOLUTION_TOTAL_DEADLINE_SECONDS` | `8.0` | Wall-clock budget across every request one render makes. Refs still unresolved when this elapses render as unresolved rather than hanging the render. Bounds when a *new* request may start; it doesn't cancel one in flight, so worst case is this plus one request's own timeout. |
| `KAYA_CARD_RESOLUTION_MAX_UPSTREAM_REQUESTS` | `5` | Hard cap on upstream requests per render, regardless of elapsed time — a huge note or board degrades to partially resolved deterministically, not just via the deadline clock. |
| `KAYA_CARD_RESOLUTION_MAX_SELECTORS_PER_REQUEST` | `100` | How many refs go in one batched `GET /api/v1/cards?refs=…` request before chunking. Must not exceed pandan's own combined-selector cap, or an over-sized chunk gets `422` instead of an answer. |
| `KAYA_CARD_RESOLUTION_CACHE_TTL_SECONDS` | `300.0` | How long a resolved (or confirmed-absent) card/epic is trusted. A stale card title is cosmetic, so this can be generous. |

## Board embeds (KAN-1049)

Rendering a `pandan-board` embed is never cached (each render is fresh), so it gets its own short
connect/read budgets rather than reusing card resolution's:

| Variable | Default | What it does |
| --- | --- | --- |
| `KAYA_BOARD_EMBED_CONNECT_TIMEOUT_SECONDS` | `3.0` | Per-request connect budget. |
| `KAYA_BOARD_EMBED_READ_TIMEOUT_SECONDS` | `3.0` | Per-request read budget. |

## Attachments (R14, KAN-1067)

Attachments are stored in Cloudflare R2. Leaving `KAYA_R2_BUCKET` unset means attachments aren't
configured at all — the storage layer raises at first use rather than silently pretending a bucket
exists, the same fail-loudly instinct the app has for a missing `DATABASE_URL`.

| Variable | Default | What it does |
| --- | --- | --- |
| `KAYA_R2_BUCKET` | unset | The bucket attachments are stored in. `None` means attachments are off. |
| `KAYA_R2_ENDPOINT_URL` | unset | R2's S3-compatible endpoint, e.g. `https://<account-id>.r2.cloudflarestorage.com`. Not a secret — a hostname, not a credential. |
| `KAYA_R2_ACCESS_KEY_ID` | unset | R2 API token id. A credential — never logged. |
| `KAYA_R2_SECRET_ACCESS_KEY` | unset | R2 API token secret. Same treatment. |
| `KAYA_R2_REGION` | `auto` | SigV4 needs a region even though R2 isn't regional; Cloudflare's own docs say to send `"auto"`. |
| `KAYA_R2_UPLOAD_MAX_BYTES` | `26214400` (25 MiB) | Per-attachment cap, enforced while the upload streams in. |

## Observability

| Variable | Default | What it does |
| --- | --- | --- |
| `KAYA_LOG_LEVEL` | `INFO` | Threshold for the one stdout JSON handler. `INFO` is one line per request; `DEBUG` adds the liveness probe hit, which is excluded from `INFO` on purpose — a kubelet hits `/health` every few seconds forever and would otherwise be almost the whole log. Not validated against known level names: an unknown value fails loudly at startup with the string it was handed, rather than a config layer silently swallowing a typo. |

!!! danger "Never a header, a request object, or anything built from a bearer reaches a log line"

    Redaction happens at serialization in `app/observability/`, so every call site is covered
    regardless of who wrote it. Nothing in `Settings` controls this — it isn't a knob.

## The single-artifact SPA path

| Variable | Default | What it does |
| --- | --- | --- |
| `KAYA_SPA_DIST` | unset | Directory holding the built SPA, served from the same origin ([ADR 0010](https://github.com/leejianrong/kaya/blob/main/docs/adr/0010-no-hosted-deploy-until-the-homelab.md)). Unset means the app serves the API alone — no directory is guessed at, and no `../frontend/dist` fallback is tried, because silently serving a months-old build is worse than not finding one. The container image sets this; `make dev` does not, since Vite serves the SPA on `:5173` and proxies `/api` back. Set it to `../frontend/dist` to run the single-artifact layout from a checkout. |

## Secrets kaya holds

kaya holds credentials of its own now, and they all arrive through settings: the GitHub OAuth client
secret, `KAYA_AUTH_SECRET`, and the R2 fields above. The tokens it hands out are not settings. They
live in the database as hashes (a linked pandan token is stored encrypted instead), and a caller's
token is never forwarded to anyone.

## A minimal production checklist

```bash
DATABASE_URL=postgresql+psycopg://…       # your database
KAYA_GITHUB_OAUTH_CLIENT_ID=…             # your own GitHub OAuth App
KAYA_GITHUB_OAUTH_CLIENT_SECRET=…
KAYA_AUTH_SECRET=…                        # long and random; rotating it signs everyone out
KAYA_COOKIE_SECURE=1                      # when served over HTTPS
```

Add `KAYA_PANDAN_URL=https://…` only if your users will link a pandan account and you run your own
instance. Everything else is optional tuning. Confirm `GET /health` returns `200` before pointing
real traffic at it.

Next: [deploy it](deploy.md).
