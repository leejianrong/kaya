"""The health endpoint, and the fact that the app boots at all.

This is the unit layer, so it must need no infrastructure: no Postgres, no pandan, no network.
Importing ``app.main`` at module top is fine *here* — it is only forbidden in the integration
layer, where a top-level import would bind the engine before the fixture sets ``DATABASE_URL``.
"""

from fastapi.testclient import TestClient

from app import __version__
from app.main import app

client = TestClient(app)


def test_health_reports_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "kaya", "version": __version__}


def test_openapi_schema_is_served() -> None:
    """The app boots far enough to describe itself. `/docs` is part of the contract (PLAN §S4)."""
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "kaya"


def test_health_does_not_require_a_database() -> None:
    """Liveness must not touch Postgres.

    Point the settings at a database that cannot exist and check `/health` still answers. If
    someone later adds a session dependency to the route, this fails.
    """
    from app.config import get_settings
    from app.db import reset_engine

    original = get_settings().database_url
    try:
        reset_engine()
        get_settings().database_url = "postgresql+psycopg://nobody@127.0.0.1:1/nothing"
        assert client.get("/health").status_code == 200
    finally:
        get_settings().database_url = original
        reset_engine()
