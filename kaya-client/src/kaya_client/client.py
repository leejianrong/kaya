"""The only thing in the suite that speaks to ``/api/v1``.

Two read methods in V2a — ``list_notes`` and ``get_note`` — matching SLICES §V2a's deliberately
minimal verb set, because the slice is about the layer and not the breadth. The writes arrive with
the rest of the verbs in V2b.

**Every method returns a ``Payload``, never a response body.** That is ADR 0004 applied at its
sharpest point. Pandan's client returns a raw dict, its CLI shapes that dict, and its MCP adapter —
calling the same client — inherited none of the shaping and pays 11.4× per task for it. A ``dict``
crossing this boundary is an invitation for the next adapter to format it locally, and the
invitation is always accepted. So the schema knowledge that shaping needs (which fields are prose,
which make the default row, what the envelope is called) is attached *here*, where the call was
made, and travels with the data.

### The transport seam

``client`` is injectable, the same shape as ``PandanIdentityUpstream`` in
`backend/app/auth/upstream.py`, and it carries the same asymmetry warning for the same reason.
Tests drive it with an ``httpx.MockTransport``: no network, no live backend, no PAT anywhere near
this repository.

It is also the named place retry-with-backoff would land if KAN-666's measurement asks for it — see
``_request``. Nothing retries today, and nothing should start to without that measurement, because
a retry over a 21.8 s cold introspection makes an outage take a multiple of the timeout to report.
"""

from typing import Any

import httpx

from kaya_client.errors import ApiError, TransportError
from kaya_client.payloads import Payload

DEFAULT_TIMEOUT = 30.0
"""Generous on purpose. A kaya request can sit behind a cold pandan introspection, measured at
21.8 s (PLAN §Open risks, KAN-539). A client deadline under that turns a slow-but-working upstream
into a client-side failure the server never hears about, which is strictly worse than waiting."""

NOTES_PATH = "/api/v1/notes"

NOTE_NOUN = "note"
NOTE_ENVELOPE = "notes"
"""The API's own list key (``{"notes": [...]}``), per PLAN §Implementation decisions."""

NOTE_PROSE_FIELDS = frozenset({"body"})
"""V2b's truncation allow-list for a note. ``body`` is the one unbounded ``TEXT`` column in
migration ``0001``; ``title`` and ``path`` are ``String(255)`` and ``String(1024)`` and are capped
by the schema, so truncating them would cut something a `422` already bounds."""

NOTE_LIST_COLUMNS = ("ref", "title", "path")
"""The default human row. Narrow deliberately: ADR 0005 says ``--fields`` *widens* it, and a row
that already showed everything would leave V2b's byte-identity pin with nothing to protect."""

NOTE_COLUMNS = ("ref", "title", "path", "created_at", "updated_at", "body")
"""A single note shows everything, ``body`` last — it is what the reader opened the note for.
``id`` is omitted: ADR 0008 says a note's identity is its ``ref``, and printing a second identifier
next to it invites a caller to store the wrong one."""


class KayaClient:
    """A caller's session against one kaya deployment.

    The bearer is forwarded byte-for-byte and never parsed. ADR 0002 gives kaya no token format and
    no prefix logic — pandan still accepts pre-rebrand ``kanban_pat_…`` tokens, and a
    ``startswith`` guard here would be the same bug pandan ADR 0018 had to correct, one layer out.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        # `timeout` configures the client this builds; it does **not** apply to one passed in,
        # which arrives carrying its own. Only tests pass `client`, and they pass a MockTransport
        # that never blocks — but the asymmetry is easy to misread, so: if you inject a client,
        # set its timeout on the client. (Same warning, same reason, as `app/auth/upstream.py`.)
        self._client = client if client is not None else httpx.Client(timeout=timeout)
        self._owns_client = client is None

    # ---------------------------------------------------------------- verbs

    def list_notes(self) -> Payload:
        """Every note the caller owns, newest first — the API's order, not re-sorted here.

        ``GET /api/v1/notes`` orders by ``updated_at DESC, id DESC`` and the second column is a
        deliberate tie-break (`app/api/notes.py`). Re-sorting client-side would be a second opinion
        about ordering that only one of the two adapters could stay consistent with.
        """
        body = self._request("GET", NOTES_PATH)
        return Payload.collection(
            noun=NOTE_NOUN,
            envelope_key=NOTE_ENVELOPE,
            records=body.get(NOTE_ENVELOPE, []),
            columns=NOTE_LIST_COLUMNS,
            prose_fields=NOTE_PROSE_FIELDS,
        )

    def get_note(self, ref: str) -> Payload:
        """One note, addressed as ``NOTE-12``, ``note-12`` or bare ``12``.

        The identifier is passed through untouched. ADR 0008 puts every spelling of a ref through
        one resolver in `backend/app/api/refs.py`, so that a missing note is the same `404` byte for
        byte whichever spelling asked for it. Normalising here would be a second resolver, and the
        first thing a second resolver does is disagree — ``#NOTE-12`` is a `400` from the API and
        would become a silent success from a client that "helpfully" stripped the ``#``.
        """
        body = self._request("GET", f"{NOTES_PATH}/{ref}")
        return Payload.entity(
            noun=NOTE_NOUN,
            envelope_key=NOTE_ENVELOPE,
            record=body,
            columns=NOTE_COLUMNS,
            prose_fields=NOTE_PROSE_FIELDS,
        )

    # ------------------------------------------------------------- transport

    def _request(self, method: str, path: str) -> Any:
        """One request, one place. Every failure leaves here as a ``KayaError``.

        **This is the seam KAN-666's fallback would use.** If splitting the backend's introspection
        timeout by phase turns out not to be enough, retry-with-backoff wraps this method — one
        call site, one place to bound the attempts, and ``TransportError`` is already the only thing
        a retry would be retrying. Do not scatter retries into the verbs above.
        """
        try:
            response = self._client.request(
                method,
                self._base_url + path,
                headers={"Authorization": f"Bearer {self._token}"},
            )
        except httpx.HTTPError as exc:
            # `from exc` is safe: httpx puts the URL in its messages, never the headers. The same
            # reasoning `app/auth/upstream.py` relies on, and the reason no bearer can reach a log
            # line through this path.
            raise TransportError(f"{self._base_url} is unreachable") from exc

        if response.status_code >= 400:
            raise ApiError(response.status_code, _error_payload(response))

        if response.status_code == 204 or not response.content:
            return {}

        try:
            return response.json()
        except ValueError as exc:
            # A 200 the client cannot read is an outage wearing a success code — a proxy
            # interstitial, most often. Never the body in the message; it is unvetted and this
            # string is printed.
            raise TransportError(f"{self._base_url} returned a body kaya could not read") from exc

    # -------------------------------------------------------------- lifecycle

    def close(self) -> None:
        """Close the transport, but only the one this client built.

        Closing an injected client would be this object disposing of something it does not own —
        the caller may still be using it, and in tests the same ``MockTransport`` is often shared.
        """
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "KayaClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def _error_payload(response: httpx.Response) -> dict[str, Any]:
    """The API's ``{"error": {…}}`` object, or a stand-in when the failure came from elsewhere.

    `app/api/errors.py` guarantees the shape for everything kaya itself refuses, *including*
    Starlette's own `404`/`405`. What it cannot guarantee is a `502` from a proxy in front of kaya,
    which is HTML. Synthesising the same shape here means an adapter has exactly one error object
    to read and never a branch for "the body wasn't JSON".
    """
    try:
        body = response.json()
    except ValueError:
        body = None

    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        return body

    return {
        "error": {
            "code": "http_error",
            "message": f"the API answered {response.status_code}",
            "status": str(response.status_code),
        }
    }
