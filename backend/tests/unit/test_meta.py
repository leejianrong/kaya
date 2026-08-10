"""``GET /api/v1/meta`` — public by necessity, and one key forever (KAN-555).

The landing state has to name pandan's origin before the visitor has a credential, so this route is
the one thing under ``/api/v1`` that answers with no ``Authorization`` header. Three properties are
worth a test each, and all three are properties somebody could remove without noticing:

1. It returns what ``KAYA_PANDAN_URL`` is configured to, not a hard-coded string.
2. It needs **no** credential — and does not merely tolerate the absence of one while still trying
   to talk to pandan or to Postgres.
3. It returns **exactly one key**. That is the guard against a meta endpoint growing into a config
   dump, which is the whole risk of publishing a route with no credential in front of it.

No infrastructure, per SLICES §V1's fast layer. Importing ``app.main`` at module top is fine here
(unit layer only — the integration layer's fixture has to set ``DATABASE_URL`` first).
"""

from fastapi.testclient import TestClient

from app.api.meta import Meta
from app.config import get_settings
from app.main import app

client = TestClient(app)

UNREACHABLE = "http://127.0.0.1:1"
"""A port nothing listens on. Used as a *pandan* origin, so any attempt to introspect fails."""


def test_meta_reports_the_configured_pandan_origin() -> None:
    settings = get_settings()
    original = settings.pandan_url
    try:
        settings.pandan_url = "https://pandan.example.test"
        response = client.get("/api/v1/meta")
    finally:
        settings.pandan_url = original

    assert response.status_code == 200
    assert response.json() == {"pandan_url": "https://pandan.example.test"}


def test_meta_needs_no_credential_and_makes_no_upstream_call() -> None:
    """No header, and pandan pointed somewhere nothing is listening.

    Both halves matter. A route with an *optional* credential would also answer without a header —
    and would then try to resolve the one it was given, or worse, resolve nothing and reach for a
    database session. Pointing ``pandan_url`` at a closed port means an introspection attempt would
    surface as Q9's `503` inside the connect budget rather than as a pass.
    """
    settings = get_settings()
    original = settings.pandan_url
    try:
        settings.pandan_url = UNREACHABLE
        response = client.get("/api/v1/meta")
    finally:
        settings.pandan_url = original

    assert response.status_code == 200
    assert response.json() == {"pandan_url": UNREACHABLE}


def test_meta_ignores_a_bearer_rather_than_validating_it() -> None:
    """A garbage credential is not a refusal here.

    This is the difference between "public" and "authenticated, and the SPA happens not to send a
    header": a route behind ``get_principal`` would answer `401 invalid_token` for this request. The
    landing state reaches this route while a *stale* token is still in the tab (that is the `401`
    recovery path), so it has to answer regardless of what the tab is carrying.
    """
    response = client.get(
        "/api/v1/meta",
        headers={"Authorization": "Bearer not-a-real-token-and-never-introspected"},
    )

    assert response.status_code == 200
    assert set(response.json()) == {"pandan_url"}


def test_meta_returns_exactly_one_key() -> None:
    """The anti-config-dump guard, asserted twice over.

    Over the **response**, because that is what reaches the internet, and over the **model**,
    because a field added with a default would keep every other assertion in this file green while
    publishing a new fact. If you are here because this test went red, read ``app/api/meta.py``'s
    docstring: adding a key is allowed, but it is a decision with an argument, not a tidy-up.
    """
    body = response_body()
    assert set(body) == {"pandan_url"}
    assert len(body) == 1

    assert tuple(Meta.model_fields) == ("pandan_url",)


def test_meta_does_not_publish_anything_else_from_settings() -> None:
    """Named values that must never appear, whatever shape a future key takes.

    ``database_url`` carries a password in every real deployment, and the two timeout knobs plus the
    log level are operational detail an anonymous caller has no business reading. This is a
    belt-and-braces companion to the one-key test: it fails on the *content* even if somebody
    changes the key count deliberately.
    """
    settings = get_settings()
    body = client.get("/api/v1/meta").text

    assert settings.database_url not in body
    assert str(settings.log_level) not in body
    assert "database" not in body.lower()


def test_meta_is_documented_in_the_openapi_schema() -> None:
    """`/docs` is part of the contract (PLAN §S4), and a public route is worth advertising there."""
    schema = client.get("/openapi.json").json()

    assert "/api/v1/meta" in schema["paths"]


def response_body() -> dict[str, object]:
    response = client.get("/api/v1/meta")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, dict)
    return payload
