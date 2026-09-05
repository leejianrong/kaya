<!--
title: "Deploy it"
description: Docker Compose for a single host, the deploy/k8s manifests for Kubernetes, and how both differ from the maintainer's own Fly.io deploy.
-->

# Deploy it

One image, one process, one Postgres database. If you can run a container with a couple of
environment variables, you can deploy kaya.

## The image

The repository root `Dockerfile` builds the frontend, then copies the static bundle alongside the
backend into one Python image. The result serves the API and the SPA from one origin.

Build it with `scripts/image-build.sh`, not a bare `docker build` — that script is what computes the
provenance labels ([ADR 0007](https://github.com/leejianrong/kaya/blob/main/docs/adr/0007-release-provenance-from-the-first-release.md)),
and a bare `docker build` leaves them reading `unknown`, which is honest but less useful than a
commit sha. Every base image is pinned by digest rather than tag, checked by
`scripts/check-image-pins.sh` in CI and the pre-push hook.

```bash
scripts/image-build.sh          # produces kaya:dev with real provenance labels
docker run -p 8000:8000 \
  -e DATABASE_URL=postgresql+psycopg://user:pass@host/db \
  -e KAYA_PANDAN_URL=https://your-pandan-instance \
  kaya:dev
```

## Migrations run separately, before the app

Migrations are not run by the app on startup. They're a distinct step that has to succeed first:

```bash
cd backend
DATABASE_URL=… uv run alembic upgrade head
```

`docker-compose.yml`'s `migrate` service and `deploy/k8s/base/deployment.yaml`'s `initContainer` both
do exactly this — same image, different command — so a failed migration is a failed container with an
exit code and a log, never an app that boots and 500s on the first query.

## Docker Compose: `make up`

The fastest way to see a real deployment shape working, and the same compose file CI trusts:

```bash
make up
```

This builds the image (via `scripts/image-build.sh`), starts Postgres, runs the migration, then
starts the app — one command, one origin, `:8000`. `docker-compose.yml`'s `app.environment:` block
forwards exactly two variables into the container: `DATABASE_URL` and `KAYA_PANDAN_URL`. Every other
setting in [configuration](configuration.md) silently takes its default under `make up`, however you
export it in your shell.

Running a second stack alongside another one on the same machine (a second worktree, say) needs its
own project name and ports, since they'd otherwise share a database:

```bash
COMPOSE_PROJECT_NAME=kaya-myfeature KAYA_DB_PORT=5433 KAYA_APP_PORT=8001 make up
```

## Kubernetes: `deploy/k8s/`

The manifests under `deploy/k8s/base/` are written against a real cluster (the maintainer's own
k8s homelab, per [ADR 0010](https://github.com/leejianrong/kaya/blob/main/docs/adr/0010-no-hosted-deploy-until-the-homelab.md)),
not against any particular local tool — and they're proven by actually being applied, not just
written. `make k3d` does that:

```bash
make k3d          # create if absent, build, import, apply, and smoke-test
make k3d-down      # delete the local cluster
```

`scripts/k3d-up.sh` builds the image, imports it directly into the k3d node's containerd store (no
registry involved), applies `deploy/k8s/overlays/local/`, and finishes by making real HTTP requests
against the running pod — proving it serves, not just that `kubectl apply` accepted the YAML.

**What the base manifests contain**, sized to what ADR 0010 asks the manifests to prove:

| File | What it is |
| --- | --- |
| `namespace.yaml` | Its own namespace, so `kubectl delete namespace kaya` is a complete uninstall. |
| `configmap.yaml` | Non-secret configuration — `KAYA_PANDAN_URL` and the pandan timeout pair, `KAYA_LOG_LEVEL`. |
| `postgres.yaml` | A `StatefulSet` with one replica and a `PersistentVolumeClaim` — deliberately not an operator, a Helm chart, or a replicated cluster. kaya is one user's notes; an operator is a second thing to run and upgrade for failover nobody asked for. |
| `deployment.yaml` | One replica (the migration `initContainer` has no lock of its own, so two replicas racing `alembic upgrade head` is how a schema ends up half-applied), all three probes hitting `/health` — which touches no database and makes no upstream call, so pandan or Postgres being down never takes kaya itself out of service ([ADR 0003](https://github.com/leejianrong/kaya/blob/main/docs/adr/0003-cross-linking-one-way-soft.md)). |
| `service.yaml` | One `ClusterIP` Service for both the API and the SPA — one origin, one port. |
| `ingress.yaml` | Path routing, `cert-manager` annotation, and a placeholder homelab hostname. |

**What the base deliberately omits**, and why: the `kaya-database` Secret is referenced everywhere
and defined nowhere in `base/` — a credential committed to git is a credential leaked, whatever it
protects. A real deployment supplies it out of band (a `kubectl create secret`, a secrets operator,
whatever your cluster already uses); `kubectl apply -k base` alone leaves pods `Pending` on a missing
Secret, which is correct, not a defect.

**What the local overlay changes**, and what that costs — `deploy/k8s/overlays/local/kustomization.yaml`
is deliberately small, and every difference from `base/` is something the local run does *not* prove
about a real deploy:

- Swaps the image for one `k3d image import`ed straight into the node (no registry) and sets
  `imagePullPolicy: Never`, so a failed import is a loud `ErrImageNeverPull` instead of a silent pull
  of something with the same name.
- Generates a throwaway `kaya-database` Secret from literal values, since this database lives for one
  `make k3d` run and dies with the cluster.
- Strips TLS, the `cert-manager` annotation, and the ingress hostname — there's no DNS entry for the
  placeholder hostname on a laptop and no cert-manager in a k3d cluster, so keeping either would make
  the Ingress match nothing. This is the overlay's one real gap: TLS termination and the
  cert-manager annotation are not exercised by `make k3d`, and ADR 0010 accepts that knowingly.
- Loosens the CPU request so a single-node cluster scheduling kaya alongside Postgres has room to
  breathe.

Deploying to a real cluster means applying `base/` with your own overlay in place of `local/` —
supplying the Secret out of band, and pointing the Ingress at a hostname and TLS issuer that are
actually yours.

## How this differs from the maintainer's own deploy

Nothing above is specific to the maintainer's infrastructure. `docker-compose.yml`, the `Dockerfile`,
and `deploy/k8s/` are all meant to be run by anyone, and none of them talk to Fly.io. The maintainer's
own hosted instance is a separate, independent thing — provisioned outside this repository's
manifests, tracked in ADR 0010's 2026-09-02 amendment (`KAN-1044` onward) — and self-hosting kaya
does not mean reproducing that Fly.io setup. It means running the container and the manifests above
against your own Postgres and your own pandan instance.

## Recap

- One image serves the API and the SPA on one origin — build it with `scripts/image-build.sh`.
- Run migrations as their own step; `docker-compose.yml`'s `migrate` service and the Deployment's
  `initContainer` both do this before the app starts.
- `make up` is the fastest single-host loop; `make k3d` proves the Kubernetes manifests against a
  real, if throwaway, cluster.
- Set `DATABASE_URL` and `KAYA_PANDAN_URL` to your own values — the defaults point at a local
  Postgres and the maintainer's own hosted pandan, in that order.
- The manifests target a real cluster; the local overlay's gaps (TLS, cert-manager) are named, not
  hidden.
