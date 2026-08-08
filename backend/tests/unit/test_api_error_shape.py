"""The API error contract: one shape, whoever raised it.

This is the decision KAN-536 was handed and told to make on purpose (``app/auth/resolver.py``
§``error_body``): FastAPI's default handler wraps a raise site's ``detail``, so kaya's own
``{"error": {…}}`` was reaching the wire as ``{"detail": {"error": {…}}}``. It is un-nested, and
these tests are what stops it drifting back — the nesting would return the moment somebody removes
the handler, and every assertion here would still *read* fine against three different shapes if it
only checked status codes.

No database and no settings: the handlers are installed onto a bare ``FastAPI()`` alongside routes
that raise on demand. That is the same property ``app/auth/`` has and for the same reason — the
whole HTTP contract is exercisable in the fast layer.
"""

from typing import Any

import pytest
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.api.errors import code_for_status, install_error_handlers
from app.auth import error_body


class Payload(BaseModel):
    count: int


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/structured")
    def structured() -> None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error_body("note_forbidden", "this note belongs to another user"),
        )

    @app.get("/with-headers")
    def with_headers() -> None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_body("authentication_required", "a bearer token is required"),
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.get("/bare-string")
    def bare_string() -> None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="something is in the way")

    @app.post("/validated")
    def validated(payload: Payload) -> Payload:
        return payload

    return TestClient(app)


def error(response: Any) -> dict[str, Any]:
    return response.json()["error"]


# --- The shape ------------------------------------------------------------------------------------


def test_a_structured_refusal_reaches_the_wire_un_nested(client: TestClient) -> None:
    """The decision itself. ``detail`` is FastAPI's word, not part of kaya's contract."""
    response = client.get("/structured")

    assert response.status_code == 403
    assert response.json() == {
        "error": {"code": "note_forbidden", "message": "this note belongs to another user"}
    }
    assert "detail" not in response.json()


def test_every_failure_answers_in_the_same_shape(client: TestClient) -> None:
    """Including the ones kaya did not raise itself.

    An unknown path and a wrong method come from Starlette with a bare string, and a body that fails
    validation comes from FastAPI as a list. A client should not need three parsers to read three
    refusals from one API, which is the whole reason ``error_body`` was a single builder to begin
    with.
    """
    responses = [
        client.get("/structured"),
        client.get("/bare-string"),
        client.get("/no-such-route"),
        client.post("/structured"),
        client.post("/validated", json={"count": "not a number"}),
    ]

    for response in responses:
        body = response.json()
        assert set(body) == {"error"}, f"{response.url} answered {body}"
        assert isinstance(error(response)["code"], str)
        assert isinstance(error(response)["message"], str)
        assert error(response)["code"] != ""


def test_a_refusal_raised_without_a_code_still_gets_a_stable_one(client: TestClient) -> None:
    """Derived from the status phrase rather than a table, so a status nobody anticipated still
    arrives with something a script can branch on instead of ``null``."""
    assert error(client.get("/bare-string"))["code"] == "conflict"
    assert error(client.get("/bare-string"))["message"] == "something is in the way"

    assert error(client.get("/no-such-route"))["code"] == "not_found"
    assert error(client.post("/structured"))["code"] == "method_not_allowed"


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (404, "not_found"),
        (405, "method_not_allowed"),
        (503, "service_unavailable"),
        (599, "http_error"),
    ],
)
def test_the_fallback_code_is_greppable_and_never_empty(status_code: int, expected: str) -> None:
    assert code_for_status(status_code) == expected


def test_headers_that_are_part_of_a_contract_survive(client: TestClient) -> None:
    """`WWW-Authenticate` on a `401` and `Retry-After` on Q9's `503` are the contract, not
    decoration. A handler that rebuilds the response is exactly where they get dropped."""
    response = client.get("/with-headers")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


# --- Validation -----------------------------------------------------------------------------------


def test_a_malformed_body_names_the_field(client: TestClient) -> None:
    response = client.post("/validated", json={"count": "not a number"})

    assert response.status_code == 422
    assert error(response)["code"] == "invalid_request"
    assert error(response)["field"] == "count", "the leading `body` segment is dropped"
    assert "count" in error(response)["message"]


def test_every_complaint_survives_into_the_message(client: TestClient) -> None:
    """The default `422` carries a list under ``detail``; folding it into one string keeps the
    information without adding a third shape for a client to special-case."""
    response = client.post("/validated", json={})

    assert response.status_code == 422
    assert "count" in error(response)["message"]


def test_the_error_object_stays_flat_and_all_strings(client: TestClient) -> None:
    """What ``error_body`` promises, and what lets ADR 0005's CLI render a refusal as one row."""
    for response in (
        client.get("/structured"),
        client.get("/no-such-route"),
        client.post("/validated", json={}),
    ):
        assert all(isinstance(value, str) for value in error(response).values())
