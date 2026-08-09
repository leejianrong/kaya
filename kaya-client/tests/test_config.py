"""PLAN §Config's environment tier: which deployment, whose bearer, and what a missing one costs.

The interesting assertions here are the negative ones. A configuration layer is where a credential
is most likely to be leaked by accident — into a diagnostic, into an exception message, into a
"helpful" default — and ADR 0002 buys kaya the property that it holds no replayable credential with
everything that decision costs. So this file asserts what the module *does not* do at least as hard
as what it does.
"""

import httpx
import pytest

from kaya_client import MissingCredential, api_url, open_client
from kaya_client.config import API_URL_ENV, DEFAULT_API_URL, TOKEN_ENV, token

TOKEN = "kanban_pat_notarealtokenatall"


# ------------------------------------------------------------------------ the origin


def test_the_api_url_comes_from_the_environment() -> None:
    assert api_url({API_URL_ENV: "https://kaya.example"}) == "https://kaya.example"


def test_an_unset_api_url_is_the_local_origin() -> None:
    """``make up`` serves the whole stack on `:8000` from one origin, so this is the address a
    checkout is already using rather than a guess."""
    assert api_url({}) == DEFAULT_API_URL
    assert DEFAULT_API_URL == "http://localhost:8000"


@pytest.mark.parametrize("value", ["", "   "])
def test_a_blank_api_url_is_treated_as_unset(value: str) -> None:
    """An exported-but-empty variable is the common shape of a misconfigured shell profile, and an
    empty base URL would turn every request into a relative one httpx refuses."""
    assert api_url({API_URL_ENV: value}) == DEFAULT_API_URL


def test_the_environment_is_read_at_call_time(monkeypatch) -> None:
    """So a test's ``monkeypatch.setenv`` and a real shell are the same code path — the reasoning
    `kaya_cli.failures.report` uses for its ``stream`` default."""
    monkeypatch.setenv(API_URL_ENV, "https://later.example")

    assert api_url() == "https://later.example"


# ------------------------------------------------------------------------- the token


def test_the_token_comes_from_the_environment() -> None:
    assert token({TOKEN_ENV: TOKEN}) == TOKEN


def test_a_token_is_forwarded_byte_for_byte() -> None:
    """ADR 0002: kaya has no token format and no prefix logic. Pandan still accepts pre-rebrand
    ``kanban_pat_…`` tokens, and a ``startswith`` guard anywhere in this suite would be the bug
    pandan ADR 0018 had to correct. Surrounding whitespace is shell noise, not part of the value."""
    assert token({TOKEN_ENV: f"  {TOKEN}  "}) == TOKEN


@pytest.mark.parametrize("env", [{}, {TOKEN_ENV: ""}, {TOKEN_ENV: "   "}])
def test_a_missing_token_is_a_refusal_not_a_request(env: dict[str, str]) -> None:
    """A blank bearer would otherwise reach the API and come back a `401` — exit `3`, telling the
    caller to re-authenticate a credential they never set."""
    with pytest.raises(MissingCredential):
        token(env)


def test_the_refusal_names_the_variable_to_set() -> None:
    """ADR 0005 §contract 3's ``arg`` slot is the thing the refusal is *about*, and here that is the
    key, so the row a consumer reads names the fix."""
    with pytest.raises(MissingCredential) as raised:
        token({})

    assert raised.value.arg == TOKEN_ENV
    assert TOKEN_ENV in str(raised.value)


def test_the_refusal_has_the_documented_code() -> None:
    """Exit `1` in `kaya_cli.failures`, per SLICES §V2a's failure table. Pinned as a string here
    because the exit table is keyed on it and the two files must agree."""
    assert MissingCredential.code == "no_credential"


def test_no_message_on_this_path_can_contain_a_fragment_of_a_token() -> None:
    """The rule in `errors.py` and `app/observability/`, asserted where a config layer would break
    it — the tempting diagnostic is "token %r is not valid", and a truncated token is still a token
    (Q41/Q42). Every contiguous fragment of six characters or more is checked.
    """
    fragments = {
        TOKEN[start:stop]
        for start in range(len(TOKEN))
        for stop in range(start + 6, len(TOKEN) + 1)
    }
    with pytest.raises(MissingCredential) as raised:
        token({TOKEN_ENV: "   "})
    reported = f"{raised.value} {raised.value.arg}"

    assert not [fragment for fragment in fragments if fragment in reported]


# ------------------------------------------------------------------------ the session


def test_open_client_builds_a_session_for_the_configured_origin() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"notes": []})

    env = {API_URL_ENV: "https://kaya.example", TOKEN_ENV: TOKEN}
    with open_client(env, transport=httpx.MockTransport(handler)) as client:
        client.list_notes()

    assert str(seen[0].url) == "https://kaya.example/api/v1/notes"
    assert seen[0].headers["Authorization"] == f"Bearer {TOKEN}"


def test_open_client_refuses_before_it_builds_anything() -> None:
    """No client, no connection, no request. A session object that existed without a credential
    would be one an adapter could use, and the failure would then arrive from the API as a `401`
    rather than from here as a `1`."""
    with pytest.raises(MissingCredential):
        open_client({API_URL_ENV: "https://kaya.example"})
