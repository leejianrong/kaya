"""`PandanHttpVerifier`, faked at the HTTP boundary — the same technique
`test_board_embed_upstream.py`/`test_card_resolution_upstream.py` use, for the same reason:
`httpx.MockTransport` means the request under assertion is the real one httpx would put on the
wire.
"""

import httpx
import pytest

from app.integrations.pandan_link import ME_PATH, PandanHttpVerifier, PandanLinkUnreachable

BASE_URL = "https://pandan.invalid"
TOKEN = "pandan_pat_FAKEa-token-this-module-never-inspects"


def verifier_returning(handler: object) -> PandanHttpVerifier:
    client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    return PandanHttpVerifier(BASE_URL, timeout=1.0, client=client)


def test_a_200_from_me_is_accepted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "some-uuid", "email": "e@example.com"})

    assert verifier_returning(handler).verify(TOKEN) is True


def test_a_401_from_me_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "authentication required"})

    assert verifier_returning(handler).verify(TOKEN) is False


def test_hits_the_me_path_with_the_bearer_forwarded_verbatim() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "x", "email": "e@example.com"})

    verifier_returning(handler).verify(TOKEN)

    assert seen[0].url.path == ME_PATH
    assert seen[0].headers["authorization"] == f"Bearer {TOKEN}"


def test_a_transport_failure_raises_unreachable_not_false() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(PandanLinkUnreachable):
        verifier_returning(handler).verify(TOKEN)
