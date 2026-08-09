"""PLAN §Config's environment tier: which deployment, whose bearer, and what a missing one costs.

The interesting assertions here are the negative ones. A configuration layer is where a credential
is most likely to be leaked by accident — into a diagnostic, into an exception message, into a
"helpful" default — and ADR 0002 buys kaya the property that it holds no replayable credential with
everything that decision costs. So this file asserts what the module *does not* do at least as hard
as what it does.
"""

import httpx
import pytest

from kaya_client import (
    DEFAULT_TEXT_LIMIT,
    MissingCredential,
    UsageError,
    api_url,
    max_text_chars,
    open_client,
)
from kaya_client.config import (
    API_URL_ENV,
    DEFAULT_API_URL,
    MAX_TEXT_CHARS_ENV,
    TOKEN_ENV,
    token,
)

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


# --------------------------------------------------------------- the text limit (KAN-547)


def test_the_text_limit_comes_from_the_environment() -> None:
    assert max_text_chars({MAX_TEXT_CHARS_ENV: "120"}) == 120


def test_an_unset_text_limit_is_the_documented_default() -> None:
    """SLICES §V2b's "default 500", taken from `truncation.DEFAULT_TEXT_LIMIT` rather than written
    again here — two copies of one number is how a config layer starts disagreeing with the thing it
    configures."""
    assert max_text_chars({}) == DEFAULT_TEXT_LIMIT
    assert DEFAULT_TEXT_LIMIT == 500


def test_zero_survives_as_a_value(monkeypatch) -> None:
    """``0`` disables truncation — ADR 0005's ``--full`` as a deployment setting — so it has to
    survive a falsy check that an unset variable does not. The tempting ``or DEFAULT`` is exactly
    the bug: it would make ``KAYA_MAX_TEXT_CHARS=0`` silently mean 500."""
    assert max_text_chars({MAX_TEXT_CHARS_ENV: "0"}) == 0

    monkeypatch.setenv(MAX_TEXT_CHARS_ENV, "0")
    assert max_text_chars() == 0


@pytest.mark.parametrize("value", ["", "   "])
def test_a_blank_text_limit_is_treated_as_unset(value: str) -> None:
    """An exported-but-empty variable is the common shape of a misconfigured shell profile, and the
    same reading `api_url` and `token` already take."""
    assert max_text_chars({MAX_TEXT_CHARS_ENV: value}) == DEFAULT_TEXT_LIMIT


@pytest.mark.parametrize("value", ["lots", "5.5", "500 chars", "1e3"])
def test_a_text_limit_that_is_not_a_whole_number_is_a_usage_error(value: str) -> None:
    """Exit `2`, ADR 0005 §contract 4: the caller's input was rejected. A ``KayaError``, and not
    the ``TypeError`` `truncation.check_text_limit` raises at the seam — ``main``'s funnel catches
    only the first, and a shell someone can correct should not arrive as a traceback."""
    with pytest.raises(UsageError):
        max_text_chars({MAX_TEXT_CHARS_ENV: value})


def test_a_negative_text_limit_is_a_usage_error() -> None:
    """``0`` already spells "disabled", so ``-1`` is not "extra disabled"."""
    with pytest.raises(UsageError, match="0 or more"):
        max_text_chars({MAX_TEXT_CHARS_ENV: "-1"})


def test_the_refusal_names_the_variable_to_fix() -> None:
    """ADR 0005 §contract 3's ``arg`` slot is the thing the refusal is about, which here is the key
    — the same shape `MissingCredential` uses, so one consumer rule reads both."""
    with pytest.raises(UsageError) as raised:
        max_text_chars({MAX_TEXT_CHARS_ENV: "lots"})

    assert raised.value.arg == MAX_TEXT_CHARS_ENV
    assert MAX_TEXT_CHARS_ENV in str(raised.value)


def test_the_text_limit_is_read_at_call_time(monkeypatch) -> None:
    monkeypatch.setenv(MAX_TEXT_CHARS_ENV, "7")

    assert max_text_chars() == 7


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


def test_a_session_over_an_injected_transport_still_carries_the_shipped_deadline() -> None:
    """The one path that could have kept httpx's 5 s default, and no other test would have said so.

    ``KayaClient`` cannot set a timeout on a client it was handed — that is the asymmetry its
    ``__init__`` warns about — so the deadline has to be put on the client *here*, at the only place
    in shipped code that builds one to inject. A `MockTransport` never blocks, so this is invisible
    to behaviour: it is asserted on the object because it could only ever be caught there.

    The number itself is KAN-716's invariant, which a 5 s deadline would break by a factor of eight
    on the one code path a future adapter is most likely to reach for.
    """
    from kaya_client.client import DEFAULT_TIMEOUT

    env = {API_URL_ENV: "https://kaya.example", TOKEN_ENV: TOKEN}
    with open_client(env, transport=httpx.MockTransport(lambda _: httpx.Response(200))) as client:
        assert client._client.timeout == DEFAULT_TIMEOUT


def test_open_client_refuses_before_it_builds_anything() -> None:
    """No client, no connection, no request. A session object that existed without a credential
    would be one an adapter could use, and the failure would then arrive from the API as a `401`
    rather than from here as a `1`."""
    with pytest.raises(MissingCredential):
        open_client({API_URL_ENV: "https://kaya.example"})
