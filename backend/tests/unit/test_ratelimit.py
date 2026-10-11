"""`app/ratelimit.py` (KAY-169): classification, keying, and the 429 contract.

Unit layer: no database. A bare `FastAPI()` with the real middleware and a few stub routes, so the
test needs neither Postgres nor the real surface. The routes below only have to *exist* for the
middleware to see a request; what they return is irrelevant.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from app import ratelimit
from app.identity.backend import COOKIE_NAME


def _request(method: str, path: str, query: str = "", headers: dict[str, str] | None = None):
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "query_string": query.encode(),
            "headers": raw,
            "client": ("10.0.0.9", 1234),
        }
    )


def test_classify_tiers() -> None:
    c = ratelimit.classify
    assert c(_request("POST", "/auth/device/token")) == "auth"
    assert c(_request("GET", "/auth/github/callback")) == "auth"
    assert c(_request("GET", "/auth/authorize")) == "auth"
    assert c(_request("POST", "/api/v1/notes")) == "write"
    assert c(_request("DELETE", "/api/v1/notes/NOTE-1")) == "write"
    assert c(_request("GET", "/api/v1/notes", "q=x")) == "expensive"
    assert c(_request("GET", "/api/v1/graph")) == "expensive"
    assert c(_request("GET", "/api/v1/notes/NOTE-1/links")) == "expensive"


def test_classify_leaves_cheap_routes_unlimited() -> None:
    c = ratelimit.classify
    assert c(_request("GET", "/api/v1/notes")) is None
    assert c(_request("GET", "/api/v1/notes/NOTE-1")) is None
    assert c(_request("GET", "/health")) is None
    assert c(_request("GET", "/auth/device/ABCD-EFGH")) is None
    assert c(_request("POST", "/mcp")) is None


def test_client_ip_trusts_fly_header_never_xff() -> None:
    spoofed = _request("GET", "/", headers={"x-forwarded-for": "6.6.6.6"})
    assert ratelimit.client_ip(spoofed) == "10.0.0.9"
    fly = _request("GET", "/", headers={"fly-client-ip": "1.2.3.4", "x-forwarded-for": "6.6.6.6"})
    assert ratelimit.client_ip(fly) == "1.2.3.4"


def test_principal_hint_never_contains_the_credential() -> None:
    hint = ratelimit.principal_hint(
        _request("GET", "/", headers={"authorization": "Bearer kaya_pat_secretvalue"})
    )
    assert hint.startswith("t:") and "secretvalue" not in hint
    cookie = ratelimit.principal_hint(
        _request("GET", "/", headers={"cookie": f"{COOKIE_NAME}=abc"})
    )
    assert cookie.startswith("c:") and "abc" not in cookie
    assert ratelimit.principal_hint(_request("GET", "/")) == "anon"


def test_malformed_limit_falls_back_to_default() -> None:
    engine = ratelimit.build_engine(enabled=True, limits_map={"write": "not a limit"})
    assert str(engine.items["write"]) == str(ratelimit.parse("300/minute"))


def _app(engine: ratelimit.RateLimitEngine | None) -> TestClient:
    app = FastAPI()
    ratelimit.install_rate_limiting(app)
    ratelimit.set_engine(engine)

    @app.post("/api/v1/notes")
    def create() -> dict[str, str]:
        return {"ok": "1"}

    @app.get("/api/v1/notes")
    def read() -> dict[str, str]:
        return {"ok": "1"}

    return TestClient(app)


def test_disabled_engine_is_a_pass_through() -> None:
    client = _app(ratelimit.build_engine(enabled=False, limits_map={"write": "1/minute"}))
    assert all(client.post("/api/v1/notes").status_code == 200 for _ in range(5))


def test_over_the_limit_is_a_429_in_the_api_error_shape() -> None:
    client = _app(ratelimit.build_engine(enabled=True, limits_map={"write": "2/minute"}))
    assert client.post("/api/v1/notes").status_code == 200
    assert client.post("/api/v1/notes").status_code == 200

    blocked = client.post("/api/v1/notes")

    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert int(blocked.headers["Retry-After"]) >= 1


def test_unlimited_routes_are_never_counted() -> None:
    client = _app(ratelimit.build_engine(enabled=True, limits_map={"write": "1/minute"}))
    assert all(client.get("/api/v1/notes").status_code == 200 for _ in range(10))


def test_two_principals_behind_one_ip_get_separate_buckets() -> None:
    client = _app(ratelimit.build_engine(enabled=True, limits_map={"write": "1/minute"}))
    a = {"Authorization": "Bearer kaya_pat_a"}
    b = {"Authorization": "Bearer kaya_pat_b"}
    assert client.post("/api/v1/notes", headers=a).status_code == 200
    assert client.post("/api/v1/notes", headers=a).status_code == 429
    assert client.post("/api/v1/notes", headers=b).status_code == 200


def test_two_ips_with_one_token_get_separate_buckets() -> None:
    client = _app(ratelimit.build_engine(enabled=True, limits_map={"write": "1/minute"}))
    h = {"Authorization": "Bearer kaya_pat_a"}
    for ip in ("1.1.1.1", "2.2.2.2"):
        assert client.post("/api/v1/notes", headers={**h, "Fly-Client-IP": ip}).status_code == 200


def teardown_module() -> None:
    ratelimit.set_engine(None)
