"""Every `Settings` field has a recorded production disposition (KAN-1763), in the spirit of
`test_token_scope_decision.py`.

On 2026-09-27 the live app ran on `KAYA_AUTH_SECRET`'s insecure default because nothing forced
anyone to decide how that field reaches production. The table lives in
`settings_dispositions.py` beside this file; `docs/runbooks/deploy-checklist.md` is the narrative.

Fails when: a field has no row, a row names no field, a credential-shaped field is `default-ok` or
`dev-only`, a `fly-env` field is missing from `fly.toml`'s `[env]`, a `fly-secret` field sits in it,
or `[env]` holds a key the table does not call `fly-env`.

Mutating the guard: add a field to `Settings` without a row and this fails naming it.
"""

import tomllib
from pathlib import Path

from settings_dispositions import DEFAULT_OK, DEV_ONLY, DISPOSITIONS, FLY_ENV, FLY_SECRET

from app.config import _EXCLUDED_FROM_STARTUP_LOG, Settings

FLY_TOML = Path(__file__).resolve().parents[3] / "fly.toml"

MUST_BE_SET_IN_PRODUCTION = {
    "database_url",
    "kaya_auth_secret",
    "kaya_cookie_secure",
    "kaya_github_oauth_client_id",
    "kaya_github_oauth_client_secret",
    "r2_bucket",
    "r2_endpoint_url",
    "r2_access_key_id",
    "r2_secret_access_key",
}
"""Fields whose default is insecure, a placeholder, or unset. Never `default-ok`."""


def env_name(field: str) -> str:
    return str(Settings.model_fields[field].validation_alias)


def fly_env_keys() -> set[str]:
    return set(tomllib.loads(FLY_TOML.read_text())["env"])


def disposition(field: str) -> str:
    return DISPOSITIONS.get(field, ("", ""))[0]


def env_names_with(kind: str) -> set[str]:
    fields = [f for f in DISPOSITIONS if f in Settings.model_fields]
    return {env_name(f) for f in fields if disposition(f) == kind}


def test_every_field_has_a_disposition() -> None:
    missing = sorted(set(Settings.model_fields) - set(DISPOSITIONS))
    assert not missing, (
        f"Settings fields with no production disposition: {missing}. Add a row to "
        "tests/unit/settings_dispositions.py (fly-secret, fly-env, default-ok or dev-only) and "
        "follow docs/runbooks/deploy-checklist.md, 'Adding a Settings field'."
    )


def test_no_stale_rows() -> None:
    stale = sorted(set(DISPOSITIONS) - set(Settings.model_fields))
    assert not stale, f"rows for fields that no longer exist, delete them: {stale}"


def test_dispositions_are_one_of_the_four() -> None:
    allowed = {FLY_SECRET, FLY_ENV, DEFAULT_OK, DEV_ONLY}
    bad = {k: v[0] for k, v in DISPOSITIONS.items() if v[0] not in allowed}
    assert not bad, bad


def test_production_fields_are_never_default_ok() -> None:
    wrong = sorted(
        f for f in MUST_BE_SET_IN_PRODUCTION if disposition(f) not in {FLY_SECRET, FLY_ENV}
    )
    assert not wrong, f"must be fly-secret or fly-env, not default-ok/dev-only: {wrong}"


def test_a_credential_shaped_field_is_a_fly_secret() -> None:
    """Anything `_EXCLUDED_FROM_STARTUP_LOG` hides is a credential, so it is a Fly secret."""
    wrong = sorted(f for f in _EXCLUDED_FROM_STARTUP_LOG if disposition(f) != FLY_SECRET)
    assert not wrong, wrong


def test_the_table_agrees_with_fly_toml() -> None:
    in_toml = fly_env_keys()
    declared_env = env_names_with(FLY_ENV)
    plain_secrets = env_names_with(FLY_SECRET) & in_toml

    assert declared_env <= in_toml, (
        f"table says fly-env but fly.toml [env] lacks: {sorted(declared_env - in_toml)}"
    )
    assert not plain_secrets, (
        f"table says fly-secret but fly.toml [env] sets it in plain text: {sorted(plain_secrets)}"
    )
    assert in_toml <= declared_env, (
        f"fly.toml [env] has keys the table does not call fly-env: {sorted(in_toml - declared_env)}"
    )
