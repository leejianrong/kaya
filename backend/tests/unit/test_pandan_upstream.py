"""The upstream client, faked at the HTTP boundary rather than mocked out.

``httpx.MockTransport`` means the request object under assertion is the real one httpx would have
put on the wire — real URL, real headers — so "the bearer is forwarded unchanged" is checked
against the thing that actually gets sent, not against a call record.

The responses below mirror what pandan really returns, probed live on 2026-08-08:

    200 {"id": "<uuid4>", "email": "<str>"} · 401 {"detail": "authentication required"}

and, importantly, that same 401 body for both a garbage bearer and a missing header. There is no
observation kaya could make that distinguishes malformed from revoked, which is the empirical
grounding for having no prefix logic (ADR 0002) — not merely a stylistic preference.

No real PAT appears here or anywhere else in the suite.
"""

import uuid

import httpx
import pytest
from fakes import TOKEN

from app.auth.principal import UpstreamUnavailable
from app.auth.upstream import ME_PATH, PandanIdentityUpstream

BASE_URL = "https://pandan.invalid"
ALICE_ID = "11111111-1111-4111-8111-111111111111"


def upstream_returning(handler: object) -> PandanIdentityUpstream:
    client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    return PandanIdentityUpstream(BASE_URL, timeout=1.0, client=client)


def json_response(status: int, payload: object) -> object:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    return handler


def test_a_200_becomes_a_principal_with_pandans_uuid() -> None:
    body = {"id": ALICE_ID, "email": "alice@example.com"}

    principal = upstream_returning(json_response(200, body)).introspect(TOKEN)

    assert principal is not None
    assert principal.id == uuid.UUID(ALICE_ID)
    assert principal.email == "alice@example.com"


def test_the_request_hits_me_and_forwards_the_bearer_byte_for_byte() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": ALICE_ID, "email": "alice@example.com"})

    upstream_returning(handler).introspect(TOKEN)

    assert str(seen[0].url) == BASE_URL + ME_PATH
    assert seen[0].headers["authorization"] == f"Bearer {TOKEN}"


def test_a_trailing_slash_on_the_configured_origin_does_not_double_up() -> None:
    """`KAYA_PANDAN_URL=https://…/` is what a person types, and `//api/v1/me` is a 404."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": ALICE_ID, "email": "a@example.com"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    PandanIdentityUpstream(BASE_URL + "/", timeout=1.0, client=client).introspect(TOKEN)

    assert str(seen[0].url) == BASE_URL + ME_PATH


@pytest.mark.parametrize("status", [401, 403])
def test_a_refusal_is_a_rejection_not_an_outage(status: int) -> None:
    upstream = upstream_returning(json_response(status, {"detail": "authentication required"}))
    assert upstream.introspect(TOKEN) is None


@pytest.mark.parametrize("status", [500, 502, 503, 504, 302, 404])
def test_any_other_status_is_an_outage_not_a_rejection(status: int) -> None:
    """The Q9 fork. Reading a 502 as "your token is bad" is the failure mode being designed out."""
    upstream = upstream_returning(json_response(status, {"detail": "nope"}))

    with pytest.raises(UpstreamUnavailable):
        upstream.introspect(TOKEN)


def test_a_transport_failure_is_an_outage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(UpstreamUnavailable):
        upstream_returning(handler).introspect(TOKEN)


def test_a_timeout_is_an_outage() -> None:
    """Pandan scales to zero, so a slow cold start is the likely shape of this in production."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(UpstreamUnavailable):
        upstream_returning(handler).introspect(TOKEN)


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "alice@example.com"},  # no id
        {"id": ALICE_ID},  # no email
        {"id": "not-a-uuid", "email": "alice@example.com"},
        [],
        "a login page, served with a 200 by something in front of pandan",
    ],
)
def test_a_200_kaya_cannot_read_is_an_outage_wearing_a_success_code(payload: object) -> None:
    upstream = upstream_returning(json_response(200, payload))

    with pytest.raises(UpstreamUnavailable):
        upstream.introspect(TOKEN)


def test_no_failure_message_carries_the_token() -> None:
    """These strings reach a 503 body and the application log."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    cases = [
        upstream_returning(refuse),
        upstream_returning(json_response(500, {"detail": "boom"})),
        upstream_returning(json_response(200, {"id": "not-a-uuid"})),
    ]

    for upstream in cases:
        with pytest.raises(UpstreamUnavailable) as raised:
            upstream.introspect(TOKEN)
        chained = repr(raised.value) + repr(raised.value.__cause__)
        assert TOKEN not in chained


def test_the_failure_message_names_the_upstream_so_the_503_can_too() -> None:
    upstream = upstream_returning(json_response(500, {"detail": "boom"}))

    with pytest.raises(UpstreamUnavailable) as raised:
        upstream.introspect(TOKEN)

    assert BASE_URL + ME_PATH in str(raised.value)
    assert "500" in str(raised.value)
