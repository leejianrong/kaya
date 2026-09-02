# Deploying kaya to Fly.io

KAN-1044/1045/1046/1047 (ADR 0010's 2026-09-02 amendment): kaya gets its own Fly.io deployment,
backed by Neon Postgres, independent of pandan's own Fly app and of the k8s homelab (`KAN-439`).

This doc is the human-side setup — the two credentials nobody but you can generate, because both
providers gate them behind a browser login. Everything downstream of having them (provisioning the
Neon project, creating the Fly app, setting secrets, deploying, wiring CI) is scriptable and doesn't
need you again until KAN-1047's DNS step.

## 1. A Fly.io API token

The `flyctl` session already on this machine (used for pandan's `simple-kanban-jian` app) has
expired — `flyctl auth whoami` returns "no access token available". Rather than re-running an
interactive `flyctl auth login` (which needs a browser to complete), generate a token that works
headlessly:

1. Go to <https://fly.io/user/personal_access_tokens> (sign in if needed — same account that runs
   `simple-kanban-jian`).
2. **Create token** → give it a name like `kaya-deploy` → an expiry you're comfortable with (a
   token that provisions and deploys, so a shorter-lived one you rotate is reasonable; there is no
   need to make it non-expiring).
3. Copy the value once — Fly only shows it at creation time.

## 2. A Neon API key

The `neonctl` session on this machine has also expired (stale OAuth token). Neon's API keys don't
expire the same way and don't need a CLI login at all:

1. Go to <https://console.neon.tech> (sign in — same account, if you already have one from pandan's
   Neon database; if not, this is where you'd create one).
2. **Account Settings → API Keys → Create new API key**.
3. Copy the value.

## 3. Put both in `.env` at the repo root

```bash
# kaya-notes/.env — gitignored (.gitignore already covers .env and .env.*)
FLY_API_TOKEN=fo1_...
NEON_API_KEY=neon_api_key_...
```

This is a **different** `.env` from `backend/.env` (which the running app itself reads for
`DATABASE_URL`/`KAYA_*` settings, per `app/config.py`) — this root-level one is only for the tooling
that provisions and deploys, never read by the app.

## What happens next (no human needed)

Once both values are in place:

- A Neon project + database gets created via Neon's API, and its connection string becomes the
  Fly app's `DATABASE_URL` secret (`fly secrets set`, never committed).
- The Fly app (`kaya-jian`, per `fly.toml`) gets created and deployed with
  `scripts/fly-deploy.sh` / `make fly-deploy`, which runs `alembic upgrade head` as Fly's
  `release_command` before the new version takes traffic.
- The result is reachable at `https://kaya-jian.fly.dev` until KAN-1047 puts a real domain in front
  of it.

## What still needs you later

- **KAN-1047's DNS step** — pointing a real domain/subdomain at the app is a domain-registrar action
  outside anything an API token here can reach.
- **KAN-1046's CI secret** — deploying on a tag push needs `FLY_API_TOKEN` as a **separate** GitHub
  Actions secret (repo Settings → Secrets and variables → Actions), scoped no wider than
  `release.yml`'s existing `contents: write` is scoped today. Generate a second token for this
  rather than reusing the one above, so revoking CI's access doesn't also break ad hoc deploys from
  a checkout.

## Cost, so it's not a surprise

Fly no longer has an unconditional free tier; a single `shared-cpu-1x`/512MB machine that scales to
zero when idle (`fly.toml`'s `min_machines_running = 0`) runs to a few dollars a month at most for
this traffic level, likely less given how rarely it'll be hit outside active development. Neon's free
tier covers one project with room to spare for a single-owner notes app.
