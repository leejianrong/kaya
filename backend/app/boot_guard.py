"""Refuse to boot a production deployment on a credential-shaped default (KAN-1763).

On 2026-09-27 the live app ran on `KAYA_AUTH_SECRET`'s committed insecure default with no GitHub
OAuth App configured, and nothing failed loudly. This is the loud failure.

"Production" means `KAYA_COOKIE_SECURE=true`. It is the one setting a real deployment sets (the
session cookie must be HTTPS-only) and that dev, `make up`, docker-compose, the e2e overlay and
the test fixtures never do, since they serve plain http. Self-hosters who turn it on are by
definition serving over HTTPS and should have a real secret anyway.

`credential_problems` is pure: settings in, problems out. `app.main`'s lifespan is its only
caller. A problem names the setting, never its value.
"""

from dataclasses import dataclass

from app.config import Settings

MIN_SECRET_LENGTH = 32
"""`openssl rand -hex 32` gives 64; anything under 32 characters is not a generated secret."""


@dataclass(frozen=True)
class Problem:
    setting: str
    message: str
    fatal: bool


def credential_problems(settings: Settings) -> list[Problem]:
    """Every credential problem in a production deployment; an empty list outside production."""
    if not settings.kaya_cookie_secure:
        return []

    problems: list[Problem] = []
    default = Settings.model_fields["kaya_auth_secret"].default
    secret = settings.kaya_auth_secret
    if secret == default:
        problems.append(
            Problem(
                "KAYA_AUTH_SECRET",
                "KAYA_AUTH_SECRET is still the committed insecure default. Set a generated "
                "value with `fly secrets set`; see docs/runbooks/deploy-checklist.md.",
                fatal=True,
            )
        )
    elif len(secret) < MIN_SECRET_LENGTH:
        problems.append(
            Problem(
                "KAYA_AUTH_SECRET",
                f"KAYA_AUTH_SECRET is shorter than {MIN_SECRET_LENGTH} characters. Generate one "
                "with `openssl rand -hex 32`.",
                fatal=True,
            )
        )

    for env_name, value in (
        ("KAYA_GITHUB_OAUTH_CLIENT_ID", settings.kaya_github_oauth_client_id),
        ("KAYA_GITHUB_OAUTH_CLIENT_SECRET", settings.kaya_github_oauth_client_secret),
    ):
        if not value:
            problems.append(
                Problem(
                    env_name,
                    f"{env_name} is not set, so GitHub sign-in cannot work in this deployment.",
                    fatal=False,
                )
            )
    return problems
