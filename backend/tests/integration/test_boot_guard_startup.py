"""The app really refuses to start in production mode with the default secret (KAN-1763), and
every ordinary fixture still starts. Imports of `app.*` stay inside bodies (see CLAUDE.md)."""

import pytest


@pytest.fixture
def fresh_settings(monkeypatch: pytest.MonkeyPatch):
    from app.config import get_settings

    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


def test_prod_mode_with_the_default_secret_refuses_to_boot(
    database_url: str, fresh_settings: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    fresh_settings.setenv("KAYA_COOKIE_SECURE", "true")
    fresh_settings.delenv("KAYA_AUTH_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="KAYA_AUTH_SECRET"), TestClient(app):
        pass


def test_prod_mode_with_a_real_secret_boots(
    database_url: str, fresh_settings: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    fresh_settings.setenv("KAYA_COOKIE_SECURE", "true")
    fresh_settings.setenv("KAYA_AUTH_SECRET", "k" * 48)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200


def test_the_default_dev_environment_still_boots(
    database_url: str, fresh_settings: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    fresh_settings.delenv("KAYA_COOKIE_SECURE", raising=False)
    fresh_settings.delenv("KAYA_AUTH_SECRET", raising=False)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
