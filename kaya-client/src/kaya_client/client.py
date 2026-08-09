"""The only thing in the suite that speaks to ``/api/v1``.

Two read methods in V2a — ``list_notes`` and ``get_note`` — matching SLICES §V2a's deliberately
minimal verb set, because the slice is about the layer and not the breadth. **KAN-551 adds the four
writes**, one per route in `backend/app/api/notes.py`, and there are four rather than five because
``move_note`` is not a route: ADR 0008 makes moving a note a `PATCH` to one column, so it delegates
to ``update_note`` and issues a byte-identical request.

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
from urllib.parse import quote

import httpx

from kaya_client.errors import ApiError, TransportError, UsageError
from kaya_client.payloads import Payload

# --------------------------------------------------------------------------- the deadline
#
# THE INVARIANT (KAN-716):
#
#     DEFAULT_READ_TIMEOUT  >  backend connect budget + backend read budget  +  handling margin
#              40.0 s       >            5.0 s        +        30.0 s        +      5.0 s
#
# The right-hand side is `KAYA_PANDAN_CONNECT_TIMEOUT_SECONDS` and
# `KAYA_PANDAN_READ_TIMEOUT_SECONDS` in `backend/app/config.py`, the two budgets KAN-666 split the
# introspection deadline into. A request that misses the principal cache pays both before kaya has
# looked at a note, so they are a floor under how long the *server* may legitimately take, and a
# client deadline under that floor abandons a request the backend was about to answer — the exact
# failure KAN-666 exists to prevent, one layer out, and reported as a `TransportError` on a working
# credential.
#
# Neither number can see the other: ADR 0004 points the dependency arrow at this package, so the
# backend may not import it, and this package may not import the backend. The alarm therefore lives
# where the change that breaks the invariant would actually be made —
# `backend/tests/unit/test_client_deadline_outlasts_auth.py`, which reads `DEFAULT_READ_TIMEOUT`
# below out of this file's AST and compares it against the live `Settings` defaults. Raising the
# backend's read budget past what this constant tolerates is a red test there, with this file named
# in the message. That guard owns the arithmetic; the numbers written above are today's values and
# are prose.
#
# ---------------------------------------------------------------------------------------------
# AND THE DECISION NOT TO MAKE THIS PER-CALL (KAN-551, recorded here because this is where someone
# would go to do it):
#
# The obvious next request is a per-verb or per-call deadline — "a `delete` should not wait forty
# seconds", "an upload needs longer". Its premise is false for kaya. The dominant term in the
# number above is *authentication*, which every request pays on a cache miss whatever the verb is:
# a `POST /notes` behind a cold introspection waits exactly as long as a `GET`, because both are
# blocked on the same call to pandan before kaya has looked at a note. What genuinely would differ
# is a large upload, and that is httpx's `write` phase — already on the connect budget, for the
# reason DEFAULT_CONNECT_TIMEOUT documents: httpx charges `write` per write operation rather than
# per upload, so a big body does not accumulate against it.
#
# What a knob would cost is the guard. `test_client_deadline_outlasts_auth.py` reads **one**
# constant out of this file's AST and checks it against the backend's two. Per-call overrides mean
# either N constants for it to find or a caller free to pass a number below the floor, and either
# way the coupling KAN-716 existed to make *checkable* is re-broken one layer out — with the added
# insult that the layer doing the breaking is the one the guard was written to protect.
#
# V6 is not prejudged by this. If MCP reads turn out to want a different tolerance, that is a V6
# measurement, and `KayaClient(timeout=…)` is already the seam it would land on: one session, one
# deadline, set where the session is built. What is refused is a per-call parameter, not a per-
# deployment one.

DEFAULT_CONNECT_TIMEOUT = 5.0
"""How long the client waits to *reach* kaya: DNS, the TCP handshake, the TLS handshake.

Short, and short on purpose. This is the phase that says whether kaya's front door is answering, and
it does not get slower because pandan is asleep behind it. A refused connection is instant either
way, but a blackholed one — wrong host, a VPN down, a firewall dropping SYNs — would otherwise hang
for the read budget below, and a CLI that sits there for forty seconds before admitting it cannot
reach the server is the fail-fast behaviour ADR 0003 asks for, thrown away in the one case where it
was easy to keep.

``write`` and ``pool`` take this budget too, for the reason ``split_timeout`` in
`app/auth/upstream.py` gives: `write` blocking past it is a broken socket rather than a busy server
(httpx charges it per write operation, not per upload, so V2b's note bodies do not need the read
budget), and `pool` is contention for a local connection slot, which has nothing to do with how
awake anything is."""

DEFAULT_READ_TIMEOUT = 40.0
"""How long the client waits for kaya's *answer* once the request is on the wire.

Generous on purpose, and the invariant above is what makes it a derived number rather than a
preference. A kaya request can sit behind a cold pandan introspection — measured at 21.8 s, PLAN
§Open risks, KAN-539 — which the backend now budgets 5 s to reach and 30 s to wait out. 35 s of
authentication plus 5 s for the request kaya was actually asked to serve is 40, and the margin is
generous against measurement: the whole warm path, round trip and mirror write included, is 387 ms.

**The cost of the number is smaller than it looks**, which is why fail-fast does not argue it down.
A pandan outage does not reach it: the backend gives up on the connect budget and Q9's `503` comes
back in about 5 s. An unreachable kaya does not reach it either — that is the connect budget
above. What is left is a kaya that accepted the connection and has not answered yet, and waiting is
the correct thing to do with one of those."""

DEFAULT_TIMEOUT = httpx.Timeout(
    connect=DEFAULT_CONNECT_TIMEOUT,
    read=DEFAULT_READ_TIMEOUT,
    write=DEFAULT_CONNECT_TIMEOUT,
    pool=DEFAULT_CONNECT_TIMEOUT,
)
"""The two budgets as httpx sees them, with no phase left to a default.

All four are named because ``httpx.Timeout`` hands back ``None`` for any phase omitted once one is
given, and ``None`` means *wait forever* — a phase nobody thought about is how one of these ends up
unbounded, which for a CLI is a process that never returns."""

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

DELETED_KEY = "deleted"
NOTE_DELETED_COLUMNS = ("ref", DELETED_KEY)
"""What a `204` renders as. See ``delete_note`` for why it is a record rather than nothing."""

TITLE_FIELD = "title"
BODY_FIELD = "body"
PATH_FIELD = "path"
PRECONDITION_FIELD = "if_updated_at"
"""``NoteUpdate``'s field names, spelled once. These are wire keys — `backend/app/api/schemas.py`
fixes them and ``extra="forbid"`` makes a typo a `422` rather than a silently ignored write — so
they are named here rather than written inline at three call sites."""

CONTENT_FIELDS = (TITLE_FIELD, BODY_FIELD, PATH_FIELD)
"""The three columns a `PATCH` may write, in the order a refusal lists them."""


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
        timeout: httpx.Timeout | float = DEFAULT_TIMEOUT,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        # `timeout` configures the client this builds; it does **not** apply to one passed in,
        # which arrives carrying its own. Only tests pass `client`, and they pass a MockTransport
        # that never blocks — but the asymmetry is easy to misread, so: if you inject a client,
        # set its timeout on the client. (Same warning, same reason, as `app/auth/upstream.py`.)
        #
        # A plain float is still accepted and still means one deadline for every phase, which is
        # what a caller who wants one number gets. It is not the default because the default has to
        # satisfy the invariant above, and one number cannot: long enough to outlast a cold
        # authentication is far too long to spend discovering that nothing is listening.
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

        The identifier reaches the API **unchanged in meaning**. ADR 0008 puts every spelling of a
        ref through one resolver in `backend/app/api/refs.py`, so a missing note is the same `404`
        byte for byte whichever spelling asked for it. Normalising here would be a second resolver,
        and the first thing a second resolver does is disagree — ``#NOTE-12`` is a `400` from the
        API and would become a silent success from a client that "helpfully" stripped the ``#``.

        **Which is why the ref is percent-encoded as one path segment** (KAN-541) — see
        ``_note_path``, which every ref-taking method shares so that KAN-551's three new ones
        inherited the fix instead of re-deriving it.
        """
        body = self._request("GET", self._note_path(ref))
        return self._note(body)

    def create_note(
        self,
        title: str,
        *,
        body: str | None = None,
        path: str | None = None,
    ) -> Payload:
        """``POST /api/v1/notes``. The note comes back whole, with the ref Postgres allocated.

        ``title`` is positional because ``NoteCreate`` requires it; ``body`` and ``path`` default to
        ``None`` **and are then omitted from the request** rather than sent as ``""``. That is not
        the same thing: the columns' server defaults are already ``""``, so omitting them lets the
        database say what an unset field is, and it keeps this method's request byte-identical to
        the minimal ``{"title": "…"}`` that `test_migration_0001` says is a complete creation.

        The response is a `201` carrying the full note plus a ``Location`` header. The header is
        ignored on purpose: it holds ``/api/v1/notes/NOTE-12``, which is the ``ref`` the body
        already carries, and a client that read identity out of a header would have a second way to
        learn a note's name (ADR 0008 allows one).
        """
        return self._note(self._request("POST", NOTES_PATH, self._content(title, body, path)))

    def update_note(
        self,
        ref: str,
        *,
        title: str | None = None,
        body: str | None = None,
        path: str | None = None,
        if_updated_at: str | None = None,
    ) -> Payload:
        """``PATCH /api/v1/notes/{ref}``. Omitted fields are left alone; the note comes back whole.

        **``if_updated_at`` is ADR 0009's precondition and it is opt-in, by specification.** Omit it
        and the write is a plain last-write-wins overwrite — that is the route's documented
        behaviour, not a gap this client should paper over. Send the ``updated_at`` you read and a
        note that has moved on is a `409` carrying ``attempted`` and ``stored``, two whole notes,
        which reach an adapter unflattened through ``ApiError.payload``.

        **It is a ``str``, and nothing here parses it.** The comparison on the server is exact to
        the microsecond (`app/api/concurrency.py`), so any datetime object this client built and
        re-serialized would be one more place a microsecond could be lost — and a token that loses
        one refuses *every* correct write while passing any test written against a round-numbered
        timestamp. The caller echoes back the string the API gave it and this method forwards it,
        which is the only arrangement with no format in the middle to get wrong. A malformed value
        is a `422` from ``AwareDatetime``, naming the field.

        **What this client will not do is fetch the precondition itself.** A read-before-write here
        would look safer and would in fact disable the guarantee: the token would then name a
        version this process read microseconds ago rather than the version the *caller's edit was
        based on*, so the `409` would fire only on a race inside that window and never on the case
        ADR 0009 exists for — a human or an agent editing a note somebody else changed an hour ago.
        """
        changes = self._content(title, body, path, required=False)
        if not changes:
            raise UsageError(
                f"nothing to change — name at least one of {', '.join(CONTENT_FIELDS)}",
                arg=NOTE_NOUN,
            )
        if if_updated_at is not None:
            changes[PRECONDITION_FIELD] = if_updated_at
        return self._note(self._request("PATCH", self._note_path(ref), changes))

    def move_note(self, ref: str, path: str) -> Payload:
        """Move a note to ``path``. **The same request ``update_note`` makes**, deliberately.

        ADR 0008: moving a note *is* a `PATCH` to one column, with no link rewriting and no separate
        endpoint, "because there is no separate operation". So this is sugar, and the sugar is
        written as delegation rather than as a second ``_request`` call — which is the whole reason
        it is safe to publish a `move` verb at all. The risk a named verb carries is that its
        existence suggests a named route, and the next person adds ``POST /notes/{ref}/move`` to
        "back it properly"; a one-line delegation is the cheapest available argument that there is
        nothing to back. ``tests/test_client.py`` pins that `move` and `edit --path` put identical
        bytes on the wire, so the day they diverge is a red test rather than a discovery.

        **No precondition parameter**, and that is a decision rather than an omission. ADR 0009
        guards a write only when it touches ``body`` (``NoteUpdate.guards_the_body``), so a
        precondition on a path-only write is *accepted and ignored* by the API by design. Offering
        one here would be offering a flag that silently does nothing, which is worse than not
        offering it: a caller who sent it would believe they had a guarantee they do not have.
        """
        return self.update_note(ref, path=path)

    def delete_note(self, ref: str) -> Payload:
        """``DELETE /api/v1/notes/{ref}``. A `204` with no body, rendered as a definitive record.

        The route answers "nothing left to describe", and an adapter that printed nothing would be
        emitting the empty string — indistinguishable from a crashed pipe, which is the same
        argument `serialization._rows` makes for ``no notes`` and the reason exiting `0` in silence
        is not an option. So the payload is one record, ``{"ref": …, "deleted": true}``: a person
        sees a confirmation and a script reads ``.deleted``.

        ``ref`` is **the identifier the caller addressed**, not a canonical one, because a `204`
        carries nothing to canonicalise from and a second request to find out would be a request
        made only so the output could look tidier. ADR 0008's round-trip rule still holds — ``12``
        and ``note-12`` are both accepted back by the one resolver — and a caller who wants the
        canonical spelling had it in the `get` that preceded the delete.
        """
        self._request("DELETE", self._note_path(ref))
        return Payload.entity(
            noun=NOTE_NOUN,
            envelope_key=NOTE_ENVELOPE,
            record={"ref": ref, DELETED_KEY: True},
            columns=NOTE_DELETED_COLUMNS,
            prose_fields=NOTE_PROSE_FIELDS,
        )

    # ------------------------------------------------------------ note plumbing

    @staticmethod
    def _note_path(ref: str) -> str:
        """One note's URL, with the ref percent-encoded as **one path segment**.

        Every ref-taking method goes through here, which is the point. KAN-541 fixed this as a real
        defect on ``get_note``: interpolating a ref raw looks like passing it through and is not,
        because httpx parses the result as a URL — ``#NOTE-12`` became an empty segment plus a
        fragment that is never sent, ``12?q=x`` became a query string, ``a/b`` became two segments.
        Each reached a *different endpoint* than the caller named, so ADR 0008's `400` never
        happened. A fix living in one method would have been re-broken by the first of KAN-551's
        three new ref-taking methods to be written from memory.
        """
        return f"{NOTES_PATH}/{quote(ref, safe='')}"

    @staticmethod
    def _note(record: Any) -> Payload:
        """One note as the API returned it. Every single-note method's last line."""
        return Payload.entity(
            noun=NOTE_NOUN,
            envelope_key=NOTE_ENVELOPE,
            record=record,
            columns=NOTE_COLUMNS,
            prose_fields=NOTE_PROSE_FIELDS,
        )

    @staticmethod
    def _content(
        title: str | None,
        body: str | None,
        path: str | None,
        *,
        required: bool = True,
    ) -> dict[str, Any]:
        """The content fields that were actually supplied, as a request body.

        **``None`` means "not sent" and is dropped; ``""`` means "clear this" and is kept.** That is
        the distinction `NoteUpdate` is built around — a partial update where a client that forgets
        a field must not silently blank 3,000 words — and it survives only if the absent value never
        reaches the JSON. Sending ``null`` instead would be a `422`: the schema refuses an explicit
        null rather than reading it as either meaning.

        ``required`` is the one difference between the two writers. ``NoteCreate`` needs a title, so
        a ``create`` passes it positionally and it is always present; a ``PATCH`` may name any
        subset, and ``update_note`` refuses the empty one itself so the message can say what to do.
        """
        supplied = {TITLE_FIELD: title, BODY_FIELD: body, PATH_FIELD: path}
        content = {name: value for name, value in supplied.items() if value is not None}
        if required and TITLE_FIELD not in content:
            raise UsageError(f"a {NOTE_NOUN} needs a {TITLE_FIELD}", arg=TITLE_FIELD)
        return content

    # ------------------------------------------------------------- transport

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        """One request, one place. Every failure leaves here as a ``KayaError``.

        **This is the seam KAN-666's fallback would use.** If splitting the backend's introspection
        timeout by phase turns out not to be enough, retry-with-backoff wraps this method — one
        call site, one place to bound the attempts, and ``TransportError`` is already the only thing
        a retry would be retrying. Do not scatter retries into the verbs above. Note that a retry
        arriving here after KAN-551 would be retrying **writes** as well as reads, and `POST
        /notes` is not idempotent: that is a constraint on the fallback, recorded where it would be
        written rather than discovered by a duplicated note.

        ``body`` is serialized as JSON when given and omitted entirely when ``None`` — httpx sends
        no entity body for ``json=None``, which is what keeps a `GET` a `GET`. It is never logged
        and never put in an exception message; the same rule as the bearer, for the weaker but real
        reason that a note body is the user's prose.
        """
        try:
            response = self._client.request(
                method,
                self._base_url + path,
                headers={"Authorization": f"Bearer {self._token}"},
                json=body,
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
