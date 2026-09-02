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

## Amendment (2026-08-20, KAN-722): the forcing function arrived, and was answered in prose

The decision above calls kaya's arrival "a forcing function for [`KAN-439`] rather than a debt
against it". That function has now fired, and this records what it was answered with. Nothing in the
decision above is reversed or re-litigated; the open end it named is closed at one end, as an
amendment, because that is what this repository does with an accepted ADR.

**What fired it.** `KAN-545` published a GitHub Release carrying `kaya-linux-x86_64`, and `KAN-719`
put its glibc floor low enough that most of the installed Linux base can run it. So the plain
question could be asked for the first time: can somebody download that binary and use it? No —
`kaya_client.config.DEFAULT_API_URL` is `http://localhost:8000`, and there is no other origin. A
downloadable artifact with nowhere to point it is the gap between *downloadable* and *usable*, and
it is this ADR's open end reached rather than a defect in the release pipeline.

**What it was answered with: documentation, not a deploy.** The maintainer's decision, 2026-08-20,
is that there is still no hosted kaya. The README's §"Where to point it" is the canonical
instruction — that the binary needs an origin, that the only origin is one you start yourself with
`make up` from a checkout with Docker, and that this is a limit on who can use the binary rather
than a step in a happy path. One paragraph, and the cheapest thing that stops the download promising
more than it delivers.

**Both named paths stay open, exactly as written.** The homelab (`KAN-439`) is still kaya's first
real deploy and still the intended one; Fly is still the escape hatch this ADR declined to close.
Nothing in this amendment narrows either, and it is emphatically **not** the "revisit Fly
deliberately" clause in §Consequences being exercised — that clause is about `KAN-439` slipping
badly, which has not been judged either way here.

**What a local origin already retired, which is more than this ADR assumed.** `docker-compose.yml`
points `KAYA_PANDAN_URL` at the live pandan by default, so `make up` plus a real PAT exercises the
genuine introspection path — not a fixture of it. All nine V2b verbs were driven that way on
2026-08-09, ADR 0009's precondition included, surviving a real Postgres `timestamptz` round trip to
the microsecond. §Consequences' "nothing is proven under a real origin" was drawn wider than the
evidence now supports.

**What genuinely stays unproven, and this is the one place that list lives.** Three things, all of
which need a remote origin and none of which this amendment can close:

1. **TLS on the CLI hop and on the browser hop.** Every request either surface has ever made was
   plaintext to `localhost`. The browser hop is new since this ADR was accepted — V3 landed a real
   SPA that pastes a PAT and saves notes — so this is two surfaces now, not one.
2. **Kaya's own cold start.** `KAN-539` and `KAN-666` measured *pandan's* cold introspection, from a
   kaya that was already warm. What a request costs against a kaya that has just been scheduled is
   unmeasured, and on scale-to-zero infrastructure it is the number that decides whether the split
   deadline in ADR 0002's amendment is still the right shape.
3. **The manifests on non-k3d infrastructure.** `make k3d` proves the pod boots and serves, which is
   what this ADR bought with them. It does not prove an ingress with a real certificate, a
   `StorageClass` that is not k3d's, or proxy headers arriving as the app expects — precisely the
   class of bug §Consequences named.

The cookie clause in §Consequences is deliberately not on that list: browser SSO is deferred by Q7
on a fact about the Public Suffix List, so there is no cookie to fail to prove.

**Also settled, because the card that raised this had it backwards.** `KAN-722` was filed while the
CLI was read-only and the config file tier was unbuilt, and argued that a hosted origin plus a
read-only CLI would still not be a usable product. `KAN-551` has since shipped the whole verb set,
the config file tier and `config set`, so on `main` the origin is the **only** thing between the CLI
and a usable product — which is exactly the thing this amendment declines to build. The gap is one
item long and it is known.

**One thing this card did find, which is neither the origin nor this ADR's business to fix.** The
published asset is `v0.5.0`, tagged 2026-08-09, and `kaya-cli` is at `0.11.0`. Its own `--help`
epilogue reads "Reads only: `note list` and `note get`" — so the sentence above is true of the
checkout and false of the download, and a reader who follows the install instructions gets a V2a
build. That is a release cadence question rather than a deploy one, no card on board 18 covers it as
of this amendment, and it is not this ADR's to answer. What this ADR owes it is one thing: the README
must not describe the checkout's CLI as though it were the artifact it just told somebody to `curl`.

## Amendment (2026-09-02, KAN-1044): pursue Fly independently, don't wait on the homelab

The 2026-08-20 amendment above named three things that stay unproven without a remote origin and
left `KAN-439` as the path to one. This amendment answers the question that same amendment posed —
"if it slips badly, revisit Fly deliberately" — not because `KAN-439` has slipped on a deadline (it
never had one), but because a 2026-09-01 planning pass (`docs/roadmap/FRAME.md`, `SHAPING.md`)
concluded that waiting on it was never load-bearing to begin with. Nothing below reverses the original
decision's reasoning about avoiding a *second* migration; it corrects the premise that kaya standing
up its own Fly app and pandan's homelab move are the same migration.

**What changed.** Board 5's `KAN-439` (migrate pandan itself to a self-hosted k8s homelab, 13 points)
is still `todo`, unstarted, and — checked directly for this amendment — pandan-only in scope: new
OAuth App, DNS/TLS cut, Postgres relocation, a rate-limiter assumption that breaks past one replica.
It mentions kaya nowhere, and no coordination artifact ties the two efforts together. They would
likely land on the same physical hardware eventually (one operator, one homelab), but as two
independent migrations sharing an operator, not one migration two ADRs described from different
sides. Treating kaya's deploy as gated on `KAN-439` was coupling kaya's release cadence to an
unstarted, unscoped-for-kaya infrastructure project for no reason this ADR's own text required —
§Consequences called `KAN-439` kaya's forcing function, never the other way around.

**Decision.** Kaya pursues an independently reachable Fly.io deployment now, without waiting on
`KAN-439`. This is exactly the escape hatch §Consequences reserved and priced at "roughly a `fly.toml`
and a secrets push, measured in a day" — being exercised, not invented. Tracked as KAN-1045
(provision the Fly app + Postgres), KAN-1046 (wire CI to deploy on tag push), KAN-1047 (DNS/TLS and a
real end-to-end latency measurement against the hosted origin).

**What this does not change.** The homelab is still the eventual destination this ADR named, and
nothing here forecloses it — Fly is explicitly an interim target (per `SHAPING.md`'s R1), not a
declared final one. The OCI artifact and Kubernetes manifests built for `KAN-439` stay exactly as
useful as they were; a Fly deploy adds a `fly.toml` and secrets alongside them, it does not replace
them. The three items the 2026-08-20 amendment left open — TLS on both hops, kaya's own cold start,
and manifest behavior on non-k3d infrastructure — are still open; a Fly deploy will retire the first
two (a real origin with real TLS, and a real scale-to-zero cold start to measure) but not the third,
since Fly isn't Kubernetes.

**Why now, not earlier.** The 2026-09-01 planning pass was the first time an independent deploy was
weighed against the enterprise-direction work (multi-team, self-hosting) that motivated it, rather
than against `KAN-439` in isolation — see `SHAPING.md` R1 and its Discussion point 3. Sequencing kaya's
own deploy ahead of that larger, multi-month initiative is what makes it worth doing now rather than
waiting for either the homelab or the enterprise design to land first.
