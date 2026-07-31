# ADR 0010 — No hosted deployment in the MVP: build the artifact and the manifests, and let the k8s homelab be kaya's first deploy

- **Status:** Accepted
- **Date:** 2026-08-01
- **Deciders:** Jian (fork F2)
- **Context source:** pandan ADR 0004 (Fly + Neon), pandan ADR 0018 §"The deploy identity: DEFERRED, not
  executed", board cards `KAN-439` (migrate to a self-hosted k8s homelab, 13pts, not started) and `KAN-424`
  (rebrand the deploy identity, deferred behind it).

## Context

Pandan runs on Fly.io + Neon and is moving to a self-hosted k8s homelab (`KAN-439`). That pending migration
has already changed one decision: pandan's own rebrand-the-deploy slice (`KAN-424`) was **deferred** rather
than executed, because a Fly→Fly cutover would have paid the same migration twice — two new OAuth Apps, two
DNS cuts, two verification passes — for an interim hostname with a short remaining life. The accepted cost is
that pandan's URL still reads `simple-kanban-jian.fly.dev`, which ADR 0018 calls the ugliest surviving seam of
the rebrand and accepts knowingly.

Standing kaya up on Fly now would reproduce that reasoning with a second app, and would make it worse: a new
Fly app, a new Neon database, a new GitHub OAuth App if browser login were wanted, a new certificate and DNS
entry, all of which get migrated again within months. Kaya would become the second thing blocking `KAN-439`
rather than the first thing to arrive cleanly on it.

## Decision

**Kaya has no hosted deployment in the MVP. It is built deploy-ready and deployed locally.**

- **One OCI artifact from V1.** A single container serving the built SPA and the API from one origin (pandan
  ADR 0003), with pinned base image digests and provenance labels (ADR 0007).
- **Kubernetes manifests from V1**, versioned in the repo: Deployment, Service, Ingress, ConfigMap, plus the
  Postgres story. Written against the homelab as the target, not against Fly.
- **Exercised against a local cluster.** `k3d` (or `kind`) in a make target, so the manifests are known to
  apply and the pod is known to boot and serve. A manifest set that has never been applied is a guess.
- **`make up` remains the primary loop** — docker compose, database plus app image, one command, per
  `/dev-playbook`. Every slice in SLICES.md is demonstrable on localhost.
- **The homelab (`KAN-439`) is kaya's first real deploy**, and kaya's arrival is a forcing function for it
  rather than a debt against it.
- **Fly stays explicitly open**, not closed. Jian noted he's still open to it later. Because the artifact is
  a plain container and the config is environment variables, a Fly deploy is roughly a `fly.toml` and a
  secrets push — an escape hatch measured in a day, available at any point if the homelab slips or a public
  URL is wanted sooner.

### What this defers with it

**Browser single sign-on** (Q7, ADR 0002). A shared cookie session needs both apps under one owned apex
domain so the cookie can carry `Domain=.<apex>`. Two `*.fly.dev` origins **cannot** share a cookie at all,
because `fly.dev` sits on the Public Suffix List and every browser refuses `Domain=.fly.dev`. So the shared
apex arrives with the homelab, and cookie SSO arrives with it.

This costs the MVP less than it appears. **PAT authentication works cross-origin from anywhere**, and the PAT
path is the one the primary actor uses (PLAN §Users). The browser story for the MVP is "sign in on pandan,
mint a PAT, paste it into kaya once" — which is what an agent does anyway.

## Alternatives considered

| Option | Why not |
|--------|---------|
| **Fly + Neon now, migrate with pandan later** | Pays the migration twice, for a hostname with a short life. It is the exact trade `KAN-424` was deferred over, and doing it for a *new* app is harder to justify than doing it for an existing one. |
| **Wait for the homelab before building anything** | `KAN-439` is 13 points and not started. Blocking a whole product on an infrastructure card is how planning momentum dies, and nothing in the MVP slices needs a public origin. |
| **Deploy to the homelab as it's built, in parallel** | Couples kaya's slice cadence to an unstarted infrastructure project. The local cluster gives the same manifest confidence without the coupling. |
| **Skip the manifests; write them when there's somewhere to apply them** | This is the cheap-looking option that produces a "just needs deploying" project that then needs a week. Writing them alongside the code, against a local cluster, is what makes the homelab deploy a configuration change. |

## Consequences

- **Positive:** zero throwaway infrastructure and zero double migration. Kaya arrives on the homelab as its
  first and only deploy, with manifests already proven to apply. No second OAuth App, no second DNS cut, no
  second certificate. Fly remains a one-day option rather than a foreclosed one.
- **Neutral:** every MVP demo is a localhost demo. Given the actors, that's honest — an agent driving `kaya`
  against `localhost:8000` exercises the same code path as one driving it against a public origin.
- **Negative / accepted knowingly:** **"cloud-hosted" is aspirational for the MVP**, which is a real gap
  against the vision doc's one-liner and the largest single scope cut in this plan. Nothing is proven under a
  real origin, real TLS, a real ingress, or a real cookie until the homelab lands, so a class of
  configuration bug (proxy headers, `Secure` cookies, TLS termination — precisely the class that bit pandan's
  OAuth callback in ADR 0011) stays undiscovered until then. The hedge is the local cluster and the
  manifests; it is a hedge, not a proof. Recorded as an open risk in PLAN.
- **Now has to be true:** `KAN-439` is on the critical path for kaya being a *product* rather than a
  *codebase*. If it slips badly, revisit Fly deliberately rather than by drift — and this ADR gets an
  amendment rather than a quiet reversal.
