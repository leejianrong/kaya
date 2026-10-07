"""Production disposition of every `app.config.Settings` field (KAN-1763).

This is the table `test_settings_dispositions.py` enforces and `docs/runbooks/deploy-checklist.md`
links to. One row per field, keyed by the field name, with the production disposition and a reason:

- `fly-secret`: set with `fly secrets set` on the `kaya-jian` app; never in a committed file.
- `fly-env`: set in `fly.toml`'s `[env]` block, committed in plain sight. The test cross-checks
  this against the real file.
- `default-ok`: production runs on the default (or on a value the image bakes in). Only for
  fields where the default is a sane production value.
- `dev-only`: never set in production.

Adding a `Settings` field fails the test until you add a row here. Follow the runbook's section on
adding a field with a real production value.
"""

FLY_SECRET = "fly-secret"
FLY_ENV = "fly-env"
DEFAULT_OK = "default-ok"
DEV_ONLY = "dev-only"

DISPOSITIONS: dict[str, tuple[str, str]] = {
    "database_url": (FLY_SECRET, "Neon connection string; carries a password"),
    "pandan_url": (FLY_ENV, "an origin, appears in a 503 body, not a secret"),
    "kaya_auth_secret": (FLY_SECRET, "signs sessions and peppers PAT hashes; default is guessable"),
    "kaya_cookie_secure": (FLY_ENV, "must be true in production; it also arms the boot guard"),
    "kaya_github_oauth_client_id": (FLY_SECRET, "no sign-in without it; set with the secret"),
    "kaya_github_oauth_client_secret": (FLY_SECRET, "a credential, paired with the client id"),
    "r2_bucket": (FLY_SECRET, "unset until attachments are provisioned; set with the R2 keys"),
    "r2_endpoint_url": (FLY_SECRET, "unset until attachments are provisioned; set with the keys"),
    "r2_access_key_id": (FLY_SECRET, "R2 credential"),
    "r2_secret_access_key": (FLY_SECRET, "R2 credential"),
    "r2_region": (DEFAULT_OK, "R2 wants the literal 'auto'"),
    "r2_upload_max_bytes": (DEFAULT_OK, "25 MiB cap is the chosen production value"),
    "spa_dist": (DEFAULT_OK, "the Dockerfile's ENV sets it; unset is correct for `make dev`"),
    "log_level": (DEFAULT_OK, "INFO is the production level"),
    "kaya_e2e_auth_bypass": (DEV_ONLY, "a login bypass; only the e2e overlay sets it"),
    "team_access_connect_timeout_seconds": (DEFAULT_OK, "tuning knob"),
    "team_access_read_timeout_seconds": (DEFAULT_OK, "tuning knob"),
    "team_access_cache_ttl_seconds": (DEFAULT_OK, "tuning knob"),
    "team_access_negative_cache_ttl_seconds": (DEFAULT_OK, "tuning knob"),
    "card_resolution_connect_timeout_seconds": (DEFAULT_OK, "tuning knob"),
    "card_resolution_read_timeout_seconds": (DEFAULT_OK, "tuning knob"),
    "card_resolution_total_deadline_seconds": (DEFAULT_OK, "tuning knob"),
    "card_resolution_max_upstream_requests": (DEFAULT_OK, "tuning knob"),
    "card_resolution_max_selectors_per_request": (DEFAULT_OK, "mirrors pandan's own cap"),
    "card_resolution_cache_ttl_seconds": (DEFAULT_OK, "tuning knob"),
    "board_embed_connect_timeout_seconds": (DEFAULT_OK, "tuning knob"),
    "board_embed_read_timeout_seconds": (DEFAULT_OK, "tuning knob"),
    "pandan_link_connect_timeout_seconds": (DEFAULT_OK, "tuning knob"),
    "pandan_link_read_timeout_seconds": (DEFAULT_OK, "tuning knob"),
}
