"""The team-membership upstream client, faked at the HTTP boundary — same technique and same
reason as `test_pandan_upstream.py`: the request object under assertion is the real one httpx
would put on the wire.

The response shape mirrors pandan's actual `TeamRead` (`backend/app/schemas.py`, verified against
pandan's source rather than inferred): `[{"id": <int>, "name": <str>, "role": ..., ...}, ...]`,
`id` an integer — not a UUID the way a `User`'s is.
"""

import httpx
import pytest
from fakes import TOKEN

from app.auth.principal import UpstreamUnavailable
from app.auth.team_upstream import TEAMS_PATH, PandanTeamUpstream

BASE_URL = "https://pandan.invalid"


def upstream_returning(handler: object) -> PandanTeamUpstream:
    client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    return PandanTeamUpstream(BASE_URL, timeout=1.0, client=client)


def json_response(status: int, payload: object) -> object:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    return handler


def test_a_200_becomes_the_set_of_team_ids() -> None:
    body = [
        {"id": 1, "name": "Platform", "role": "editor"},
        {"id": 2, "name": "Design", "role": "viewer"},
    ]

    teams = upstream_returning(json_response(200, body)).member_teams(TOKEN)

    assert teams == frozenset({1, 2})


def test_an_empty_list_is_zero_teams_not_an_error() -> None:
    assert upstream_returning(json_response(200, [])).member_teams(TOKEN) == frozenset()


def test_the_request_hits_teams_and_forwards_the_bearer_byte_for_byte() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[])

    upstream_returning(handler).member_teams(TOKEN)

    assert str(seen[0].url) == BASE_URL + TEAMS_PATH
    assert seen[0].headers["authorization"] == f"Bearer {TOKEN}"


def test_a_trailing_slash_on_the_configured_origin_does_not_double_up() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    PandanTeamUpstream(BASE_URL + "/", timeout=1.0, client=client).member_teams(TOKEN)

    assert str(seen[0].url) == BASE_URL + TEAMS_PATH


@pytest.mark.parametrize("status", [401, 403, 500, 502, 503, 504])
def test_any_non_200_is_an_outage(status: int) -> None:
    """Unlike identity, there is no rejection case here — see `team_upstream.py`'s Protocol
    docstring for why a 401/403 is folded into the same outcome as a 5xx."""
    upstream = upstream_returning(json_response(status, {"detail": "nope"}))

    with pytest.raises(UpstreamUnavailable):
        upstream.member_teams(TOKEN)


def test_a_transport_failure_is_an_outage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(UpstreamUnavailable):
        upstream_returning(handler).member_teams(TOKEN)


def test_a_timeout_is_an_outage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(UpstreamUnavailable):
        upstream_returning(handler).member_teams(TOKEN)


@pytest.mark.parametrize(
    "payload",
    [
        [{"name": "Platform"}],  # no id
        [{"id": "not-an-int"}],
        {"id": 1},  # not a list at all
        "a login page, served with a 200 by something in front of pandan",
    ],
)
def test_a_200_kaya_cannot_read_is_an_outage_wearing_a_success_code(payload: object) -> None:
    upstream = upstream_returning(json_response(200, payload))

    with pytest.raises(UpstreamUnavailable):
        upstream.member_teams(TOKEN)


def test_no_failure_message_carries_the_token() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(UpstreamUnavailable) as raised:
        upstream_returning(refuse).member_teams(TOKEN)

    assert TOKEN not in (repr(raised.value) + repr(raised.value.__cause__))


def test_the_failure_message_names_the_upstream() -> None:
    upstream = upstream_returning(json_response(500, {"detail": "boom"}))

    with pytest.raises(UpstreamUnavailable) as raised:
        upstream.member_teams(TOKEN)

    assert BASE_URL + TEAMS_PATH in str(raised.value)
    assert "500" in str(raised.value)
