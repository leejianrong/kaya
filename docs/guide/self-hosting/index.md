<!--
title: "Self-hosting"
description: Run your own kaya instance — the Docker image, the k8s manifests, and how this differs from the maintainer's own Fly.io deploy.
-->

# Self-hosting

kaya ships as one deployable artifact: a single container that serves both `/api/v1` and the built
SPA from one origin. There is no separate web server, no CDN, and no CORS to configure
([ADR 0010](https://github.com/leejianrong/kaya/blob/main/docs/adr/0010-no-hosted-deploy-until-the-homelab.md)).

You need that container and a Postgres database. That is the whole system, plus one thing kaya does
not provide itself: identity. kaya has no login and no account system of its own — every request is
authenticated by forwarding the caller's bearer to a pandan instance's `GET /api/v1/me`
([ADR 0002](https://github.com/leejianrong/kaya/blob/main/docs/adr/0002-identity-pandan-as-provider.md)).
Self-hosting kaya means pointing it at a pandan instance, not replacing pandan with something of your
own.

## Two different things: self-hosting and the maintainer's own deploy

It's easy to conflate these, so it's worth being explicit. The maintainer runs one hosted kaya, and
that deploy is not what this page is about:

| | The maintainer's Fly.io deploy | Self-hosting (this page) |
| --- | --- | --- |
| Who runs it | The maintainer | You |
| Where | Fly.io, provisioned independently of pandan's own infrastructure | Wherever you point a container — a laptop, a VM, a k8s cluster |
| Tracked by | An amendment to ADR 0010 (`KAN-1044` onward) | The Docker image and `deploy/k8s/` manifests, both versioned in this repository |
| Identity | Forwards to the maintainer's own hosted pandan by default | Forwards to whichever pandan instance you configure via `KAYA_PANDAN_URL` |

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
| Identity provider | Not part of this system at all. A pandan instance, reachable over HTTP, configured via `KAYA_PANDAN_URL`. |

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

## The one thing you must not skip

`DATABASE_URL` has a working default for local development
(`postgresql+psycopg://kaya:kaya@localhost:5432/kaya`), so an instance boots with almost nothing
configured. `KAYA_PANDAN_URL` also has a default — the maintainer's own hosted pandan
(`https://simple-kanban-jian.fly.dev`) — which is convenient for trying kaya out and almost certainly
wrong for a real deployment: it means every caller's identity is resolved against *that* pandan
instance's user base, not yours.

Set both explicitly once you're past `make up` on a laptop. Details in
[configuration](configuration.md).
