"""The boot-time credential guard (KAN-1763), as a pure function of `Settings`.

Production is detected by `KAYA_COOKIE_SECURE=true`: it is the one setting production sets and
nothing in dev, `make up`, docker-compose, the e2e overlay or the test fixtures does (they all
serve plain http). In that mode a guessable or short `KAYA_AUTH_SECRET` refuses the boot, and
missing GitHub OAuth credentials are a warning, since the app still serves but nobody can sign in.

Mutating the guard: drop the default-secret check in `app/boot_guard.py` and the first prod test
fails.
"""

from app.boot_guard import MIN_SECRET_LENGTH, Problem, credential_problems
from app.config import Settings

GOOD = "x" * MIN_SECRET_LENGTH


def settings(**kw: object) -> Settings:
    base = {
        "kaya_cookie_secure": True,
        "kaya_auth_secret": GOOD,
        "kaya_github_oauth_client_id": "id",
        "kaya_github_oauth_client_secret": "shh",
    }
    return Settings.model_construct(**{**base, **kw})


def names(problems: list[Problem], fatal: bool) -> list[str]:
    return [p.setting for p in problems if p.fatal is fatal]


def test_good_production_settings_have_no_problems() -> None:
    assert credential_problems(settings()) == []


def test_default_secret_in_production_is_fatal() -> None:
    default = Settings.model_fields["kaya_auth_secret"].default
    problems = credential_problems(settings(kaya_auth_secret=default))
    assert names(problems, True) == ["KAYA_AUTH_SECRET"]


def test_short_secret_in_production_is_fatal() -> None:
    problems = credential_problems(settings(kaya_auth_secret="a" * (MIN_SECRET_LENGTH - 1)))
    assert names(problems, True) == ["KAYA_AUTH_SECRET"]


def test_dev_mode_is_never_a_problem() -> None:
    default = Settings.model_fields["kaya_auth_secret"].default
    dev = settings(
        kaya_cookie_secure=False,
        kaya_auth_secret=default,
        kaya_github_oauth_client_id=None,
        kaya_github_oauth_client_secret=None,
    )
    assert credential_problems(dev) == []


def test_missing_oauth_in_production_is_a_warning_not_fatal() -> None:
    problems = credential_problems(
        settings(kaya_github_oauth_client_id=None, kaya_github_oauth_client_secret=None)
    )
    assert names(problems, False) == [
        "KAYA_GITHUB_OAUTH_CLIENT_ID",
        "KAYA_GITHUB_OAUTH_CLIENT_SECRET",
    ]
    assert names(problems, True) == []


def test_half_configured_oauth_names_only_the_missing_half() -> None:
    problems = credential_problems(settings(kaya_github_oauth_client_secret=None))
    assert names(problems, False) == ["KAYA_GITHUB_OAUTH_CLIENT_SECRET"]


def test_messages_never_contain_the_secret_value() -> None:
    secret = "short-but-distinctive"
    text = " ".join(p.message for p in credential_problems(settings(kaya_auth_secret=secret)))
    assert secret not in text
