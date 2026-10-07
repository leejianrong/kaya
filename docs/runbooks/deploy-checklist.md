# Deploy checklist

Kaya deploys to Fly (`kaya-jian`) when a `v*` tag is pushed, through `.github/workflows/release.yml`.
Merging to `main` deploys nothing. That gap is the reason this page exists: on 2026-09-27 main sat 14
commits and three weeks ahead of the last tag, so the live app ran pre-cutover code, on a default
`KAYA_AUTH_SECRET`, with no GitHub OAuth App configured, and nothing failed loudly. Three guards now
cover it (KAN-1763), and this page is how to work with them.

## The three guards

- **Release drift.** `.github/workflows/release-drift.yml` keeps one open issue titled "Release
  needed: main is N commits ahead of vX.Y.Z" and closes it when a tag catches up. It opens when a
  commit since the tag touched the deploy-sensitive surface (`backend/app/identity/`,
  `backend/app/auth/`, `backend/app/config.py`, `backend/alembic/`, `fly.toml`, `Dockerfile`,
  `.github/workflows/release.yml`), or when the tag is over 7 days old and a commit changed shipped
  code. Docs-only drift does not count. It never tags or deploys.
- **Settings dispositions.** Every field of `app.config.Settings` has a row in
  [`backend/tests/unit/settings_dispositions.py`](../../backend/tests/unit/settings_dispositions.py)
  saying how it reaches production. A unit test fails when a field has no row, and when the table
  disagrees with `fly.toml`.
- **Boot guard.** `backend/app/boot_guard.py` runs at startup. When `KAYA_COOKIE_SECURE` is true
  (the production signal) it refuses to start if `KAYA_AUTH_SECRET` is the committed default or
  shorter than 32 characters, and it logs a CRITICAL line, naming the setting and never the value.
  It also logs CRITICAL, without refusing, when the GitHub OAuth client id or secret is unset. A
  refused boot means a failed Fly deploy: the new machine never passes its health check.

## After merging a change to auth, identity or config

1. Look for the "Release needed" issue, or run `python3 scripts/lib/release_drift.py` for the same
   answer locally. Any change under the deploy-sensitive paths above means a release is due now.
2. Check `git log` since the last tag for a behavioural change to `kaya-cli`, `kaya-client` or `mcp`.
   ADR 0007 requires its version bump in the same PR, and `scripts/check-version-bump.sh` enforces
   it. Backend-only changes need no bump, but the tag must still equal `v` plus `kaya-cli`'s
   `[project].version`, so a release with no package change means bumping `kaya-cli` anyway.
3. Cut the release as CLAUDE.md describes under "Cutting a release": land the bump, then
   `git tag v0.X.0 <merged-sha> && git push origin v0.X.0`. Never push a tag from a branch.
4. If the merge added or changed a `Settings` field, set its production value before tagging (see
   below). The deploy runs the new code against whatever is configured at that moment.

## Adding a Settings field that has a real production value

1. Decide where it lives. A value that is a credential, or carries one (a URL with a password),
   is a Fly secret. A value that is plain configuration and safe to read in the repo is a
   `fly.toml` `[env]` entry. If the default is already right for production, say so with
   `default-ok`.
2. Add the row to `backend/tests/unit/settings_dispositions.py`. The test
   `test_settings_dispositions.py` fails until you do, and it checks `fly-env` rows against
   `fly.toml`. For a `fly-env` field, add the key to `[env]` in the same PR. If the field's default
   is insecure or unset and production needs a value, add it to `MUST_BE_SET_IN_PRODUCTION` in the
   test too, so it can never be `default-ok`.
3. For a Fly secret, set it before the release that needs it. Read the value from stdin or a file,
   never inline, so it stays out of shell history and the transcript:

   ```bash
   # generate and set a random secret without ever printing it
   openssl rand -hex 32 | tr -d '\n' | fly secrets set -a kaya-jian KAYA_AUTH_SECRET=- --stage

   # or import several from a file kept outside the repo, then delete the file
   fly secrets import -a kaya-jian < /path/outside/repo/secrets.env
   ```

   `--stage` holds the change until the next deploy, which suits setting a secret ahead of a tag.
   Check the exact stdin syntax with `fly secrets set --help` for your flyctl version.
4. `fly secrets list -a kaya-jian` shows names and digests only. Use it to confirm a name is
   present. It cannot show a value, and that is the point.
5. Update [`docs/guide/self-hosting/configuration.md`](../guide/self-hosting/configuration.md) so
   self-hosters see the new field.

## Verifying after a deploy, without printing secrets

Run these against `https://kaya-jian.fly.dev` (the app scales to zero, so the first request can
take a few seconds):

```bash
curl -fsS https://kaya-jian.fly.dev/health                       # 200 and a small JSON body
curl -s -o /dev/null -w '%{http_code}\n' https://kaya-jian.fly.dev/device   # 200
curl -si -X POST https://kaya-jian.fly.dev/mcp | head -n 5       # 401 with a WWW-Authenticate header
```

Then open the site in a browser and confirm the sign-in page loads and the GitHub button reaches
GitHub's consent screen. If the OAuth App is missing, the button is absent and the boot log carries
a CRITICAL line naming `KAYA_GITHUB_OAUTH_CLIENT_ID` or `KAYA_GITHUB_OAUTH_CLIENT_SECRET`.

The boot check is the last step. A healthy deploy means the guard passed, since a refused boot never
becomes healthy. If the release failed, `fly logs -a kaya-jian` shows a CRITICAL line such as
"KAYA_AUTH_SECRET is still the committed insecure default". The log names the setting and never its
value, so it is safe to paste.

## Before the first release that includes the boot guard

The guard is armed by `KAYA_COOKIE_SECURE=true`, which `fly.toml` now sets under `[env]`. So the
first release carrying it will refuse to boot unless `fly secrets list -a kaya-jian` shows a
`KAYA_AUTH_SECRET` that is not the default and is at least 32 characters. Rotated on 2026-09-27 per
KAN-1763, but confirm: a short or default value fails the deploy. Also confirm
`KAYA_GITHUB_OAUTH_CLIENT_ID` and `KAYA_GITHUB_OAUTH_CLIENT_SECRET` are listed, and `DATABASE_URL`.
