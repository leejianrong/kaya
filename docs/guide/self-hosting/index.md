<!--
title: "Self-hosting"
description: Run your own kaya instance — the Docker image, the k8s manifests, and how this differs from the maintainer's own Fly.io deploy.
-->

# Self-hosting

kaya ships as one deployable artifact: a single container that serves both `/api/v1` and the built
SPA from one origin. There is no separate web server, no CDN, and no CORS to configure
([ADR 0010](https://github.com/leejianrong/kaya/blob/main/docs/adr/0010-no-hosted-deploy-until-the-homelab.md)).

You need that container and a Postgres database. That is the whole system, plus a GitHub OAuth App
if you want people to sign in. kaya runs its own identity: it signs people in with GitHub, keeps its
own sessions, and mints and checks its own `kaya_pat_…` tokens
([ADR 0012](https://github.com/leejianrong/kaya/blob/main/docs/adr/0012-standalone-identity.md)).
It needs no pandan instance to start, to sign anyone in, or to run, and the same container hosts the
remote MCP endpoint at `/mcp`. pandan is an optional integration, covered below.

## Two different things: self-hosting and the maintainer's own deploy

It's easy to conflate these, so it's worth being explicit. The maintainer runs one hosted kaya, and
that deploy is not what this page is about:

| | The maintainer's Fly.io deploy | Self-hosting (this page) |
| --- | --- | --- |
| Who runs it | The maintainer | You |
| Where | Fly.io, provisioned independently of pandan's own infrastructure | Wherever you point a container — a laptop, a VM, a k8s cluster |
| Tracked by | An amendment to ADR 0010 (`KAN-1044` onward) | The Docker image and `deploy/k8s/` manifests, both versioned in this repository |
| Identity | Its own GitHub OAuth App and its own tokens | Your own GitHub OAuth App and your own tokens |
| pandan | The maintainer's own hosted pandan, for board embeds and card links | Optional. Point `KAYA_PANDAN_URL` at yours, or leave it and never link an account |

ADR 0010's original decision was that kaya has **no** hosted deployment in the MVP — build the
artifact and the manifests, prove them against a local cluster, and let a k8s homelab be kaya's first
real deploy. A later amendment (2026-09-02, `KAN-1044`) revisited that and had kaya pursue an
independently reachable Fly.io deployment sooner, without waiting on the homelab. Both amendments are
about the maintainer's *own* instance. Nothing about either changes what's on this page: the artifact
was always meant to be run by anyone, and the manifests were always meant to be applied by anyone,
not only by the maintainer.

## What it is made of

| Piece | What it is |
| --- | --- |
| Application | One container, built from the repository's `Dockerfile`. Serves `/api/v1`, `/docs` (the OpenAPI UI), and the built SPA with a catch-all fallback. |
| Database | Postgres. One synchronous connection pool ([ADR 0001](https://github.com/leejianrong/kaya/blob/main/docs/adr/0001-stack-inherited-from-pandan.md)). |
| Migrations | Alembic. Runs as a one-shot step before the app starts — a `migrate` service in `docker-compose.yml`, an `initContainer` in `deploy/k8s/base/deployment.yaml` — so a failed migration is a failed container with a log, never an app that boots and 500s on the first query. |
| Frontend | Svelte, built to static files the same container serves. Not a separate deployment. |
| Identity | Part of the application. A GitHub OAuth App you register (`KAYA_GITHUB_OAUTH_CLIENT_ID` and `KAYA_GITHUB_OAUTH_CLIENT_SECRET`) handles browser sign-in, and `KAYA_AUTH_SECRET` signs sessions and hashes tokens. |
| Remote MCP | Served by the same container at `/mcp`, authorised with kaya's own tokens ([agents and MCP](../agents/mcp-setup.md)). |
| pandan | Optional. Board embeds, `[[KAN-n]]` wikilink resolution and team-default access call a pandan instance, and each degrades quietly when it is missing or down. |

The single-origin arrangement is load-bearing, not incidental: because the SPA and the API share an
origin, there's no cross-origin request to get wrong, and no second TLS certificate to keep in step
with the first.

## Where to go

<div class="grid cards" markdown>

-   **[Configuration](configuration.md)**

    Every environment variable `Settings` reads, its default, and which ones matter once you're past
    a local checkout.

-   **[Deploy it](deploy.md)**

    `make up` for a single-host Docker Compose deploy, or `make k3d` and the `deploy/k8s/` manifests
    for Kubernetes.

</div>

## What you must not skip

`DATABASE_URL` has a working default for local development
(`postgresql+psycopg://kaya:kaya@localhost:5432/kaya`), so an instance boots with almost nothing
configured. Three more settings matter once you are past `make up` on a laptop:

- **Sign-in.** Register a GitHub OAuth App with the callback URL `<your-origin>/auth/github/callback`
  and set `KAYA_GITHUB_OAUTH_CLIENT_ID` and `KAYA_GITHUB_OAUTH_CLIENT_SECRET`. GitHub allows one
  callback per App, so a dev instance and a production instance need separate Apps. Without both
  values the sign-in routes are not registered, though the app still boots.
- **`KAYA_AUTH_SECRET`.** It has an insecure development default. Set a long random value, and set
  `KAYA_COOKIE_SECURE=1` when you serve over HTTPS. Rotating the secret signs everyone out and
  invalidates every token, so choose it once.
- **`KAYA_PANDAN_URL`.** It defaults to the maintainer's hosted pandan. That only matters if your
  users link a pandan account, in which case board embeds and card wikilinks talk to that
  instance. Point it at your own pandan, or leave it if you do not use pandan at all.

Details in [configuration](configuration.md).
