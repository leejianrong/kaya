"""``KayaClient`` against an ``httpx.MockTransport``. No network, no live backend, no PAT.

The transport seam is injectable for the same reason `app/auth/upstream.py`'s is: faking at the HTTP
boundary is what keeps a runtime dependency out of the test suite. Reachable from here without a
server: a `200`, a `404`, a `401`, a `502` that is not even JSON, and a connection that never opens.

Two assertions in this file are about what must **not** happen. The bearer is forwarded byte for
byte and never appears in an exception message — kaya's whole ADR 0002 bargain is that it holds no
replayable credential, and an exception string reaches a log, a traceback and, under the CLI's
error contract, stdout.
"""

import httpx
import pytest
from conftest import GROCERIES, NOTE_LIST_BODY

from kaya_client import ApiError, KayaClient, Kind, TransportError, render
from kaya_client.client import DEFAULT_CONNECT_TIMEOUT, DEFAULT_READ_TIMEOUT, DEFAULT_TIMEOUT

BASE_URL = "https://kaya.example"
TOKEN = "kanban_pat_notarealtokenatall"
"""Deliberately pre-rebrand-shaped. ADR 0002 gives kaya no token format and no prefix logic —
pandan still accepts these, and a ``startswith`` guard would be pandan ADR 0018's bug one layer
out. This client must forward it without an opinion."""


def client_over(handler: object) -> KayaClient:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    return KayaClient(BASE_URL, TOKEN, client=httpx.Client(transport=transport))


def responder(status: int, json_body: object = None, *, text: str | None = None):
    def handle(request: httpx.Request) -> httpx.Response:
        handle.seen = request  # type: ignore[attr-defined]
        if text is not None:
            return httpx.Response(status, text=text)
        return httpx.Response(status, json=json_body)

    return handle


def test_list_notes_returns_a_collection_payload() -> None:
    with client_over(responder(200, NOTE_LIST_BODY)) as client:
        payload = client.list_notes()
    assert payload.kind is Kind.COLLECTION
    assert [record["ref"] for record in payload.records] == ["NOTE-12", "NOTE-3"]


def test_list_notes_preserves_the_api_order() -> None:
    """``updated_at DESC, id DESC`` is the API's, tie-break included. Nothing re-sorts it here."""
    reversed_body = {"notes": list(reversed(NOTE_LIST_BODY["notes"]))}
    with client_over(responder(200, reversed_body)) as client:
        payload = client.list_notes()
    assert [record["ref"] for record in payload.records] == ["NOTE-3", "NOTE-12"]


def test_list_notes_hits_the_notes_route() -> None:
    handler = responder(200, NOTE_LIST_BODY)
    with client_over(handler) as client:
        client.list_notes()
    assert str(handler.seen.url) == f"{BASE_URL}/api/v1/notes"  # type: ignore[attr-defined]


def test_get_note_returns_an_entity_payload() -> None:
    with client_over(responder(200, GROCERIES)) as client:
        payload = client.get_note("NOTE-12")
    assert payload.kind is Kind.ENTITY
    assert payload.record == GROCERIES


@pytest.mark.parametrize("ref", ["NOTE-12", "note-12", "12"])
def test_a_ref_is_forwarded_untouched(ref: str) -> None:
    """ADR 0008 resolves every spelling in **one** place, `backend/app/api/refs.py`.

    Normalising here would be a second resolver, and the first thing a second resolver does is
    disagree: ``#NOTE-12`` is a `400` from the API, and a client that helpfully stripped the ``#``
    would turn it into a silent success against a different note.
    """
    handler = responder(200, GROCERIES)
    with client_over(handler) as client:
        client.get_note(ref)
    assert handler.seen.url.path == f"/api/v1/notes/{ref}"  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("ref", "sent"),
    [
        ("#NOTE-12", "/api/v1/notes/%23NOTE-12"),
        ("12?q=x", "/api/v1/notes/12%3Fq%3Dx"),
        ("a/b", "/api/v1/notes/a%2Fb"),
        ("NOTE 12", "/api/v1/notes/NOTE%2012"),
        ("NOTE-12", "/api/v1/notes/NOTE-12"),
    ],
)
def test_a_ref_that_is_url_syntax_still_reaches_the_ref_resolver(ref: str, sent: str) -> None:
    """The bug KAN-541 found the moment a verb could actually send one. **Written failing first.**

    Interpolating a ref into the path *looks* like passing it through and is not: httpx parses the
    result, so ``#NOTE-12`` became an empty final segment plus a fragment that is never transmitted,
    ``12?q=x`` became a query string, and ``a/b`` became two segments. Every one of them reached a
    **different endpoint** than the caller named — ``GET /api/v1/notes/``, which is not even the
    single-note route — so ADR 0008's promise that ``#NOTE-12`` is a `400` from one resolver was
    quietly false for every caller of this method.

    The previous version of this test asserted ``str(url).endswith(f"/notes/{ref}")`` and passed,
    because httpx keeps the fragment in the URL's *string* while never putting it on the wire. That
    is CLAUDE.md's warning about watching what a mutation actually reaches: the assertion was on a
    value the request does not send. It is on ``url.path`` now, which is what a server sees.
    """
    handler = responder(200, GROCERIES)
    with client_over(handler) as client:
        client.get_note(ref)

    # `raw_path` is what goes on the wire; `path` is httpx's decoding of it. Both are asserted
    # because the claim has two halves: one path segment, and that segment decoding back to the
    # exact ref the caller typed — which is what `app/api/refs.py` is then handed.
    assert handler.seen.url.raw_path.decode() == sent  # type: ignore[attr-defined]
    assert handler.seen.url.query == b""  # type: ignore[attr-defined]


def test_the_bearer_is_forwarded_byte_for_byte() -> None:
    handler = responder(200, NOTE_LIST_BODY)
    with client_over(handler) as client:
        client.list_notes()
    assert handler.seen.headers["authorization"] == f"Bearer {TOKEN}"  # type: ignore[attr-defined]


def test_a_trailing_slash_on_the_base_url_does_not_double_up() -> None:
    handler = responder(200, NOTE_LIST_BODY)
    client = KayaClient(
        BASE_URL + "/", TOKEN, client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    client.list_notes()
    assert str(handler.seen.url) == f"{BASE_URL}/api/v1/notes"  # type: ignore[attr-defined]


def test_a_404_carries_the_api_error_object() -> None:
    """`app/api/errors.py` settled the wire shape as flat ``{"error": {…}}`` partly for this call.

    The client forwards the object rather than unwrapping it, so ADR 0009's `409` — which carries
    two whole notes so a caller can diff them — arrives intact at an adapter that has not been
    written yet.
    """
    body = {"error": {"code": "not_found", "message": "no note NOTE-9999", "ref": "NOTE-9999"}}
    with client_over(responder(404, body)) as client, pytest.raises(ApiError) as raised:
        client.get_note("NOTE-9999")

    assert raised.value.status == 404
    assert raised.value.code == "not_found"
    assert raised.value.message == "no note NOTE-9999"
    assert raised.value.payload == body


@pytest.mark.parametrize(("status", "code"), [(401, "unauthenticated"), (403, "forbidden")])
def test_auth_refusals_keep_their_status_and_code(status: int, code: str) -> None:
    """ADR 0005's exit table keys `401`→3 and `403`→4 on meaning, so both facts have to survive."""
    body = {"error": {"code": code, "message": "no"}}
    with client_over(responder(status, body)) as client, pytest.raises(ApiError) as raised:
        client.list_notes()
    assert (raised.value.status, raised.value.code) == (status, code)


def test_a_non_json_failure_still_arrives_in_the_api_error_shape() -> None:
    """A `502` from a proxy in front of kaya is HTML. An adapter must not need a branch for it."""
    handler = responder(502, text="<html>bad gateway</html>")
    with client_over(handler) as client, pytest.raises(ApiError) as raised:
        client.list_notes()
    assert raised.value.status == 502
    assert raised.value.code == "http_error"
    assert "<html>" not in str(raised.value), "an unvetted body must not reach a printed message"


def test_an_unreachable_api_is_not_a_refusal() -> None:
    """The distinction `app/auth/` draws between ``UpstreamUnavailable`` and a `401`.

    Collapsing them tells a caller their token is bad when their wifi is off — and under ADR 0005's
    exit table that is exit `3`, which a script would react to by discarding a working credential.
    """

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with client_over(refuse) as client, pytest.raises(TransportError):
        client.list_notes()


def test_a_200_that_is_not_json_is_an_outage_not_a_payload() -> None:
    """A tunnel or CDN interstitial wearing a success code."""
    handler = responder(200, text="<html>login</html>")
    with client_over(handler) as client, pytest.raises(TransportError) as raised:
        client.list_notes()
    assert "<html>" not in str(raised.value)


@pytest.mark.parametrize(
    "make_failure",
    [
        lambda: responder(401, {"error": {"code": "unauthenticated", "message": "no"}}),
        lambda: responder(502, text="nope"),
        lambda: responder(200, text="nope"),
    ],
)
def test_no_failure_message_contains_any_fragment_of_the_bearer(make_failure: object) -> None:
    """Every contiguous fragment, because a truncated token is still a token (Q41/Q42).

    The same assertion shape as `backend/tests/unit/`'s redaction tests, applied one package out:
    ADR 0002 buys exactly one property — kaya holds no replayable credential — and an exception
    string is the cheapest way to give it away, since the CLI's error contract prints one.
    """
    from kaya_client.errors import KayaError

    client = client_over(make_failure())  # type: ignore[operator]
    with client, pytest.raises(KayaError) as raised:
        client.list_notes()

    message = f"{raised.value!r} {raised.value}"
    fragments = {
        TOKEN[start:stop]
        for start in range(len(TOKEN))
        for stop in range(start + 6, len(TOKEN) + 1)
    }
    assert not [fragment for fragment in fragments if fragment in message]


def test_an_injected_client_is_not_closed_by_this_one() -> None:
    """It belongs to the caller, who may still be using it — the asymmetry ``__init__`` warns of."""
    injected = httpx.Client(transport=httpx.MockTransport(responder(200, NOTE_LIST_BODY)))
    with KayaClient(BASE_URL, TOKEN, client=injected):
        pass
    assert not injected.is_closed


def test_a_client_it_built_itself_is_closed() -> None:
    client = KayaClient(BASE_URL, TOKEN)
    client.close()
    assert client._client.is_closed


BACKEND_CONNECT_BUDGET = 5.0
BACKEND_READ_BUDGET = 30.0
"""`KAYA_PANDAN_CONNECT_TIMEOUT_SECONDS` and `KAYA_PANDAN_READ_TIMEOUT_SECONDS`, the two budgets
KAN-666 split kaya's introspection deadline into (`backend/app/config.py`).

Literals, and stale by construction — this package cannot import the backend and must not learn how
to (ADR 0004's arrow points here, not out). The *live* comparison is
`backend/tests/unit/test_client_deadline_outlasts_auth.py`, which reads the constant below out of
this package's AST and checks it against the backend's actual field defaults. These two are here so
that the assertion below says what it is protecting rather than asserting a bare number, and so that
a reader of this file can see where 40 came from."""


def test_the_default_read_deadline_outlasts_the_backends_authentication() -> None:
    """KAN-716's invariant, from this side.

    A request that misses kaya's principal cache pays the connect budget *and* the read budget
    before kaya looks at a note — 35 s today, of which a cold pandan really has taken 21.8 s
    (KAN-539). Giving up first turns a request the server was about to answer into a client-side
    failure it never hears about, which is strictly worse than waiting.

    Lowering the constant is a change to this package and this is where it goes red; raising the
    *backend's* budget past it is a change to the other package, and the guard named above is where
    that goes red. Neither direction is unwatched, and neither test can watch both.
    """
    assert DEFAULT_READ_TIMEOUT >= BACKEND_CONNECT_BUDGET + BACKEND_READ_BUDGET


def test_a_deadline_this_long_is_not_spent_finding_out_nothing_is_listening() -> None:
    """The other half of the trade, and the reason the long deadline is affordable.

    ADR 0003's spirit is that a degraded dependency fails fast, and a single 40 s number would spend
    all of it on a host that is not answering at all. The phases are separate so that "wait out a
    cold authentication" and "give up on an unreachable server" get different answers — the same
    argument `app/auth/upstream.py`'s `split_timeout` makes about pandan, applied to kaya.
    """
    assert DEFAULT_CONNECT_TIMEOUT < DEFAULT_READ_TIMEOUT / 4


def test_no_phase_of_the_default_deadline_is_left_unbounded() -> None:
    """`httpx.Timeout` returns `None` for any phase omitted once one is given, and `None` means wait
    forever. For a CLI that is a process that never returns, and it is reachable by naming three of
    the four — the trap `test_split_timeout_leaves_no_phase_unbounded` covers in the backend."""
    assert None not in (
        DEFAULT_TIMEOUT.connect,
        DEFAULT_TIMEOUT.read,
        DEFAULT_TIMEOUT.write,
        DEFAULT_TIMEOUT.pool,
    )


def test_a_caller_may_still_hand_over_one_number() -> None:
    """Widening the parameter to `httpx.Timeout | float` must not break the one-number case.

    Asserted on the built client rather than on the constructor not raising: "it did not blow up"
    would also pass if the value were dropped on the floor and the default silently kept.
    """
    client = KayaClient(BASE_URL, TOKEN, timeout=1.5)
    try:
        assert client._client.timeout == httpx.Timeout(1.5)
    finally:
        client.close()


def test_the_client_it_builds_carries_the_split_and_not_one_number() -> None:
    """The constants existing proves nothing if `__init__` does not hand them to httpx."""
    client = KayaClient(BASE_URL, TOKEN)
    try:
        assert client._client.timeout.connect == DEFAULT_CONNECT_TIMEOUT
        assert client._client.timeout.read == DEFAULT_READ_TIMEOUT
        assert client._client.timeout.connect != client._client.timeout.read
    finally:
        client.close()


def test_the_client_feeds_render_directly() -> None:
    """The end-to-end shape of ADR 0004: transport in, shaped output out, no dict in between.

    If this test needed to touch the response body between the two calls, that would be the seam
    an adapter would eventually reimplement.
    """
    with client_over(responder(200, NOTE_LIST_BODY)) as client:
        assert render(client.list_notes()) == (
            "NOTE-12  Groceries       home/groceries.md\nNOTE-3   A reading list\n"
            "\n2 notes\n"
            "\nhelp: kaya note get <ref>\nhelp: kaya note create <title>"
        )
