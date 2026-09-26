"""`kaya_mcp.tools._client`'s per-request override (ADR 0013, KAN-1744) — the seam that makes the
hosted Streamable HTTP transport safe for one process serving every caller, distinct from the
stdio transport's env-var singleton every other test in this package already exercises via
`fake_api`/`open_client`.
"""

import pytest
from conftest import BASE_URL, TOKEN

from kaya_mcp import tools
from kaya_mcp.request_auth import clear_request_token, get_request_token, set_request_token


@pytest.fixture(autouse=True)
def clear_override_after_each_test():
    yield
    clear_request_token()


def test_no_override_means_no_token_is_set() -> None:
    assert get_request_token() is None


def test_setting_and_clearing_the_override_round_trips() -> None:
    set_request_token("kaya_pat_something")
    assert get_request_token() == "kaya_pat_something"

    clear_request_token()
    assert get_request_token() is None


def test_client_uses_the_override_token_and_the_configured_api_url_when_one_is_set(
    monkeypatch,
) -> None:
    """The hosted transport's whole point: a per-request bearer, not `open_client()`'s
    env-var-configured singleton."""
    monkeypatch.setenv("KAYA_API_URL", BASE_URL)
    seen: list[tuple[str, str]] = []

    class FakeKayaClient:
        def __init__(self, base_url: str, token: str) -> None:
            seen.append((base_url, token))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(tools, "KayaClient", FakeKayaClient)
    set_request_token("kaya_pat_the_callers_own_token")

    with tools._client():
        pass

    assert seen == [(BASE_URL, "kaya_pat_the_callers_own_token")]


def test_client_falls_back_to_open_client_when_no_override_is_set(monkeypatch) -> None:
    """The stdio transport never sets the override, so it must keep taking the
    `open_client()`-singleton branch unchanged."""
    called: list[bool] = []

    def fake_open_client():
        called.append(True)

        class _Ctx:
            def __enter__(self):
                return "the-stdio-client"

            def __exit__(self, *exc):
                return False

        return _Ctx()

    monkeypatch.setattr(tools, "open_client", fake_open_client)

    with tools._client() as client:
        assert client == "the-stdio-client"

    assert called == [True]


def test_the_override_never_leaks_into_open_clients_own_branch(monkeypatch) -> None:
    """Belt-and-braces: even with a real `open_client()` faked via `fake_api`, setting the
    override must switch the branch entirely rather than merely adding a second credential."""
    monkeypatch.setenv("KAYA_API_URL", BASE_URL)
    monkeypatch.setenv("KAYA_TOKEN", TOKEN)
    seen: list[str] = []

    class FakeKayaClient:
        def __init__(self, base_url: str, token: str) -> None:
            seen.append(token)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(tools, "KayaClient", FakeKayaClient)
    set_request_token("kaya_pat_the_hosted_callers_token")

    with tools._client():
        pass

    assert seen == ["kaya_pat_the_hosted_callers_token"], (
        "the stdio KAYA_TOKEN must never be used once a per-request override is live"
    )
