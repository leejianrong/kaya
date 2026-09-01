"""The only thing in the suite that speaks to ``/api/v1``.

Two read methods in V2a — ``list_notes`` and ``get_note`` — matching SLICES §V2a's deliberately
minimal verb set, because the slice is about the layer and not the breadth. **KAN-551 adds the four
writes**, one per route in `backend/app/api/notes.py`, and there are four rather than five because
``move_note`` is not a route: ADR 0008 makes moving a note a `PATCH` to one column, so it delegates
to ``update_note`` and issues a byte-identical request. **KAN-566 adds two more reads**, ``links``
and ``backlinks``, one per route in `backend/app/api/links.py` — and the pair is worth reading
together, because they are the clearest illustration in this file of what attaching schema knowledge
at the call actually buys. ``links`` returns a collection of a **new** noun with its own envelope,
its own columns and an empty prose allow-list; ``backlinks`` returns a collection of *notes*,
because the API answers it with the very same ``NoteList`` a plain list does, so it is
``list_notes`` at a different URL and inherits every shaping decision that one already made.

**Every method returns a ``Payload``, never a response body.** That is ADR 0004 applied at its
sharpest point. Pandan's client returns a raw dict, its CLI shapes that dict, and its MCP adapter —
calling the same client — inherited none of the shaping and pays 11.4× per task for it. A ``dict``
crossing this boundary is an invitation for the next adapter to format it locally, and the
invitation is always accepted. So the schema knowledge that shaping needs (which fields are prose,
which make the default row, what the envelope is called) is attached *here*, where the call was
made, and travels with the data.

**R12 (KAN-1060..1063) adds ``export_note``/``export_all``/``import_note``/``import_dir``**, the
export/import round trip `docs/roadmap/BREADBOARD.md` shapes. No new route: export reads through
``get_note``/``list_notes`` and import writes through ``create_note``, so every one of them is this
file's existing seven methods plus file I/O and `frontmatter`'s parse/compose pair. See
``_import_document`` for R12's one real finding — a caller-supplied ref has nowhere on the wire to
go, which the fit-check's "no new route" leaves unresolved rather than this card working around it.

### The transport seam

``client`` is injectable, the same shape as ``PandanIdentityUpstream`` in
`backend/app/auth/upstream.py`, and it carries the same asymmetry warning for the same reason.
Tests drive it with an ``httpx.MockTransport``: no network, no live backend, no PAT anywhere near
this repository.

It is also the named place retry-with-backoff would land if KAN-666's measurement asks for it — see
``_request``. Nothing retries today, and nothing should start to without that measurement, because
a retry over a 21.8 s cold introspection makes an outage take a multiple of the timeout to report.
"""

from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from kaya_client.errors import ApiError, TransportError, UsageError
from kaya_client.frontmatter import PATH_KEY, REF_KEY, TITLE_KEY, compose_document, parse_document
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

QUERY_PARAM = "q"
"""``GET /api/v1/notes``'s search parameter (KAN-558, KAN-559). Named once so `list_notes` and its
tests spell it the same way the API's own query parameter does."""

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

RECENT_NOTES = 5
"""How many notes a bare `kaya` shows (KAN-549). See ``recent_notes`` for why there is a number here
at all; this is the argument for *five*.

It is an orientation, not a listing, and it is read in two places with opposite constraints. On a
terminal the whole invocation has to be one screen: three banner lines, a blank, the rows, a blank,
the footer, a blank and two ``help:`` lines is 13 lines at five rows, which fits the 24-line default
with the command that produced it still visible. For an agent it is the *first* call of a session,
and the one most likely to be made speculatively, so it is the read whose cost matters most —
measured at **174** `human` tokens, against 893 for the same invocation unsliced
(`scripts/measure_toon_delta.py`, 40 notes, ``o200k_base``).

Five rather than ten because the marginal row answers a question the caller has not asked yet: "what
was I doing?" is answered by the top of the list, and "what have I got?" is `note list`, which the
banner names. Ten is measured at 284 — **+63%** for five rows nobody asked for, on the cheapest and
most frequent read in the tool, to defer that command by one turn."""

NOTE_COLUMNS = ("ref", "title", "path", "created_at", "updated_at", "body")
"""A single note shows everything, ``body`` last — it is what the reader opened the note for.
``id`` is omitted: ADR 0008 says a note's identity is its ``ref``, and printing a second identifier
next to it invites a caller to store the wrong one."""

DELETED_KEY = "deleted"
NOTE_DELETED_COLUMNS = ("ref", DELETED_KEY)
"""What a `204` renders as. See ``delete_note`` for why it is a record rather than nothing."""

LINKS_SEGMENT = "/links"
BACKLINKS_SEGMENT = "/backlinks"
"""KAN-566's two sub-resources of a note, appended to ``_note_path``'s single encoded segment.

Written as suffixes rather than as two more path templates so that every ref-taking method still
goes through ``_note_path`` — the reason that helper exists is that a ref interpolated raw reaches a
*different endpoint* than the caller named, and a second URL builder here would be the first place
to forget it."""

LINK_NOUN = "link"
LINK_ENVELOPE = "links"
"""The API's own key for `/links` (``{"links": [...]}``), the same PLAN §Implementation decisions
shape ``notes`` has. ``noun`` and ``envelope_key`` together are what `aggregates.summary_line`
renders as ``1 link`` / ``3 links``, so neither needs any English written here."""

LINK_PROSE_FIELDS: frozenset[str] = frozenset()
"""**Empty, and argued rather than defaulted.** ADR 0005 makes truncation an allow-list of prose
fields and never a length heuristic, so the question is which of a link record's five fields is
unbounded ``TEXT``. None of them are. ``target_kind`` is ``String(16)`` and ``target_ref`` is
``String(255)`` in migration ``0003``; ``title`` and ``column`` are a pandan card's own bounded
columns, or a note's ``String(255)`` title. Cutting a title is what KAN-547 already refuses to do to
``note.title`` for exactly this reason — the schema bounds it, so a cut would only ever mangle a
value a `422` already caps.

It has a second, mechanical effect worth knowing about: `kaya_cli.__main__` skips resolving
``KAYA_MAX_TEXT_CHARS`` entirely for a payload with no prose fields, so a broken value in the config
file cannot lock a caller out of `kaya links`. That is inherited, not arranged — see the comment on
``text_limit`` there."""

LINK_COLUMNS = ("target_kind", "target_ref", "resolved_ref", "title", "column")
"""The default human row for `/links`: every key the payload has, in the API's own order.

The one payload in this package whose default row is **not** narrower than the record, and the
reason is that ADR 0005 §contract 2's argument for a narrow row does not apply. A note's row is
narrow because a note carries its whole ``body`` and showing it in a table would be unreadable; a
link record has five short fields and no prose at all, so a narrower row would hide the two things
a reader opened `kaya links` to see (did it resolve, and to what). ``--fields`` still narrows it,
uniformly, for every format."""

TITLE_FIELD = "title"
BODY_FIELD = "body"
PATH_FIELD = "path"
PRECONDITION_FIELD = "if_updated_at"
"""``NoteUpdate``'s field names, spelled once. These are wire keys — `backend/app/api/schemas.py`
fixes them and ``extra="forbid"`` makes a typo a `422` rather than a silently ignored write — so
they are named here rather than written inline at three call sites."""

CONTENT_FIELDS = (TITLE_FIELD, BODY_FIELD, PATH_FIELD)
"""The three columns a `PATCH` may write, in the order a refusal lists them."""

EXPORT_NOUN = "export"
EXPORT_ENVELOPE = "exports"
"""R12's third noun, alongside ``note`` and ``link``. `note export` is a new **entity** kind for the
same reason `links` argues a link is not a note: what an export answers — which file did this write,
and where — is not a note's own shape, so widening ``NOTE_COLUMNS`` to fit it would put a column on
`note get` that only `note export` ever fills."""

EXPORT_COLUMNS = ("ref", "title", "path", "file")
"""The whole of what an export reports: which note, and which file it landed in. No prose fields —
the body went into the file, not onto the screen, which is the point of the verb."""

IMPORTED_FROM_REF_KEY = "imported_from_ref"
ORIGINAL_REF_STATUS_KEY = "original_ref_status"
"""Two informational keys `import_note`/`import_dir` add to the created note's own record — see
``_import_document``'s docstring for what they mean, and, more importantly, for what they do
**not**: the backend has no way to honour a caller-supplied ref (`app/models/note.py`'s
``NOTE_REF_SERVER_DEFAULT`` allocates one from a sequence inside the INSERT, and ``NoteCreate``
forbids sending one at all), so these two keys report what the source file *asked for* and whether
it *could* have been reused — never that it *was*. They are extra keys on an ordinary ``note``
entity, not a new noun, because the record this returns is a real note in every other respect and
`note get <ref>` on it behaves identically."""

REF_STATUS_FREE = "free"
REF_STATUS_TAKEN = "taken"


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

    def list_notes(self, q: str | None = None) -> Payload:
        """Every note the caller owns, newest first — or, with ``q``, the ones that match it.

        ``GET /api/v1/notes`` orders by ``updated_at DESC, id DESC`` with no ``q``, and by
        ``ts_rank DESC, id DESC`` with one (`app/auth/authorization.py`::``notes_matching``,
        KAN-558). Both orders are the API's; re-sorting client-side would be a second opinion about
        ordering that only one of the two adapters could stay consistent with.

        **``q`` is forwarded verbatim, the same opaque-string treatment ``if_updated_at`` gets.**
        ``None`` means "no search" and adds no query parameter at all — the exact request
        `list_notes()` always made, so an absent `--q` changes nothing about a plain `note list`.
        A non-``None`` value is sent as ``?q=`` even when it is empty or all whitespace: this client
        does not strip it, guess at it, or refuse it client-side, because `app/api/search.py` is the
        one place that decision is made and it is a `400 empty_search_query` there — the same
        argument ADR 0008 makes about a ref, applied to a search term. `ApiError` carries that
        refusal to the caller unchanged, and it inherits exit `2` from `EXIT_FOR_STATUS` with
        nothing here or in `kaya-cli` keyed on the code string.

        The response is the same ``NoteList`` shape either way — no ``rank`` key, nothing to
        distinguish a search from a list except the notes it returned — so this method needs no
        second envelope and no second set of columns.
        """
        path = NOTES_PATH if q is None else f"{NOTES_PATH}?{urlencode({QUERY_PARAM: q})}"
        body = self._request("GET", path)
        return Payload.collection(
            noun=NOTE_NOUN,
            envelope_key=NOTE_ENVELOPE,
            records=body.get(NOTE_ENVELOPE, []),
            columns=NOTE_LIST_COLUMNS,
            prose_fields=NOTE_PROSE_FIELDS,
        )

    def recent_notes(self, limit: int = RECENT_NOTES) -> Payload:
        """The caller's most recently updated notes, at most ``limit`` of them — bare `kaya`.

        A **named method rather than a ``limit`` parameter on ``list_notes``**, because the two are
        different questions. `note list` answers "what have I got?" and its answer has to be
        complete; a bare invocation answers "what was I doing?" and five rows are the answer. Making
        it a parameter would mean every caller of ``list_notes`` deciding a number, and the obvious
        default for that number is "all", which is the wall SLICES §V2b's "recent" exists to avoid.

        **Honest about what it costs: this fetches everything and keeps the first few.** There is no
        ``?limit=`` on `GET /api/v1/notes` and no cursor — paging is deferred (SLICES), and no card
        has asked for one — so the saving is entirely in what is *rendered*, which is the expensive
        end for the consumer this layer exists for but not for the database. When paging lands, this
        method is the one call site that has to change and the CLI does not, which is the other
        reason it is a method here rather than a slice in an adapter.

        The order is the API's — ``updated_at DESC, id DESC`` — so "recent" is the server's opinion
        and not a second sort. ``limit`` is a parameter with a default rather than a constant read
        inside, so a test can drive the boundary without monkeypatching a module attribute.
        """
        return self.list_notes().limited_to(limit)

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

    def links(self, ref: str) -> Payload:
        """``GET /api/v1/notes/{ref}/links`` — the wikilinks in this note's body, resolved.

        A **collection of links**, not of notes: the records are edges, one per distinct ``[[...]]``
        the body contains, each carrying what it points at (``resolved_ref``, ``title``, ``column``)
        or three ``null``s when nothing could resolve it. Q26 makes the unresolved case a rendering
        rather than an error, so there is no failure here for a caller to branch on — an outage and
        a ticket that does not exist arrive identically, which is ADR 0003's degrade-to-unresolved
        posture reaching the output layer intact.

        **The order is the API's** (``target_kind``, then ``target_ref``) and this method does not
        re-sort. The backend's own docstring explains why it cannot be insertion order — the
        reconciler builds its inserts from a ``set``, and Python randomises string hashing per
        process — so a client-side sort would be a second opinion about a decision made where the
        rows are, and only one of the two adapters could stay consistent with it.

        **No hints are registered for this payload, deliberately** (`hints.py` predicted exactly
        this, by name). A links row's ``resolved_ref`` is a ``NOTE-n`` only for the NOTE-kind rows,
        so ``note get <ref>`` would be advice that applies to some rows and not others, and
        ``backlinks <ref>`` restates the sibling of the command the caller just typed. An unknown
        ``(kind, noun)`` emits nothing, which is the behaviour that keeps a new envelope silent
        instead of wrong.
        """
        body = self._request("GET", f"{self._note_path(ref)}{LINKS_SEGMENT}")
        return Payload.collection(
            noun=LINK_NOUN,
            envelope_key=LINK_ENVELOPE,
            records=body.get(LINK_ENVELOPE, []),
            columns=LINK_COLUMNS,
            prose_fields=LINK_PROSE_FIELDS,
        )

    def backlinks(self, ref: str) -> Payload:
        """``GET /api/v1/notes/{ref}/backlinks`` — the notes whose body links to this one.

        **A collection of *notes*, with the note noun, the note columns and the note prose fields**,
        because that is what the API returns: `/backlinks` answers with the very same ``NoteList`` a
        plain `note list` does. So this method is `list_notes` at a different URL, and that identity
        is the point rather than a coincidence — ``--fields ref,title``, ``--full``, the ``{"count":
        n}`` aggregate and the two ``help:`` templates all arrive with nothing added anywhere, and
        V6's MCP server gets them for free (ADR 0004).

        The alternative — a link-shaped record naming which edge pointed here — would have cost a
        second noun, a second column set and a second hint row to publish a fact the caller can
        already read off the notes. Nothing has asked for it; SLICES §V5's own wording is "lists
        every note linking to it", and KAN-568's panel lists notes.

        **This read never touches pandan**, and that is the card's headline sentence rather than an
        implementation note: "which notes mention this one" is a join over two of kaya's own tables,
        so it is answerable with pandan stopped and a cold cache. Nothing in this method could
        change that — it makes one request to kaya — which is exactly why the guarantee is asserted
        in `backend/tests/integration/test_note_links_api.py` against the route, where an upstream
        call could actually be added.

        The order is the API's ``updated_at DESC, id DESC``, the same one `list_notes` documents.
        """
        body = self._request("GET", f"{self._note_path(ref)}{BACKLINKS_SEGMENT}")
        return Payload.collection(
            noun=NOTE_NOUN,
            envelope_key=NOTE_ENVELOPE,
            records=body.get(NOTE_ENVELOPE, []),
            columns=NOTE_LIST_COLUMNS,
            prose_fields=NOTE_PROSE_FIELDS,
        )

    # --------------------------------------------------------- export / import (R12)

    def export_note(self, ref: str, destination: str | Path | None = None) -> Payload:
        """Write one note to a file: YAML-ish front matter, then the body verbatim.

        ``GET /api/v1/notes/{ref}`` through the ordinary `get_note` path — no new route, per R12's
        fit-check, and the same ref-resolution guarantee every other verb gets (ADR 0008). What
        `frontmatter.compose_document` does with the response is this card's whole addition.

        ``destination`` defaults to ``<ref>.md`` in the current directory, using the **canonical**
        ref the API returned rather than whatever spelling ``ref`` was typed as (``12`` exports to
        ``NOTE-12.md``, not ``12.md``) — the closest a filename can get to the round-trip guarantee
        ADR 0008 makes about the ref itself.
        """
        note = dict(self.get_note(ref).record)
        target = Path(destination) if destination is not None else Path(f"{note['ref']}.md")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(compose_document(note), encoding="utf-8")
        return Payload.entity(
            noun=EXPORT_NOUN,
            envelope_key=EXPORT_ENVELOPE,
            record={
                "ref": note["ref"],
                "title": note["title"],
                "path": note["path"],
                "file": str(target),
            },
            columns=EXPORT_COLUMNS,
        )

    def export_all(self, directory: str | Path) -> Payload:
        """Every note the caller owns, one file per note at its ``path`` — an Obsidian-vault-
        compatible directory (BREADBOARD.md's R12 corpus export).

        ``list_notes()`` rather than a loop of ``get_note`` calls: the list route already returns
        the complete record, ``body`` included (`NoteList`'s own ``NoteRead`` items, not a
        summary), so there is no second request per note to make. The order it writes in is
        whatever `list_notes` returned — ``updated_at DESC, id DESC`` — which is irrelevant to a
        directory of files and not re-sorted for that reason.

        See `_vault_relative_path` for how a note's mutable, unconstrained ``path`` (ADR 0008: no
        uniqueness, no format) becomes a filesystem path that cannot escape ``directory``.
        """
        root = Path(directory)
        written = []
        for note in self.list_notes().records:
            relative = _vault_relative_path(note)
            target = root.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(compose_document(note), encoding="utf-8")
            written.append(
                {
                    "ref": note["ref"],
                    "title": note["title"],
                    "path": note["path"],
                    "file": str(target),
                }
            )
        return Payload.collection(
            noun=EXPORT_NOUN,
            envelope_key=EXPORT_ENVELOPE,
            records=written,
            columns=EXPORT_COLUMNS,
        )

    def import_note(self, source: str | Path) -> Payload:
        """Create a note from one file — kaya's own export shape, or arbitrary markdown.

        ``POST /api/v1/notes`` through the ordinary `create_note` path (see `_import_document`),
        so KAN-563's wikilink reconciliation runs exactly the way it does for any other create —
        "nothing bespoke", per R12's own wording. **No new route**, and — see `_import_document`'s
        docstring — no route that could accept a caller-chosen ref either way.

        A file that cannot be read or is not UTF-8 is a ``UsageError``, the same refusal
        `kaya_cli.parsing.resolve_body` gives ``--body-file`` for the same two failures, since this
        is the same kind of caller mistake in the same kind of argument.
        """
        path = Path(source)
        text = _read_text(path, arg=str(source))
        return self._import_document(text, fallback_title=path.stem, fallback_path="")

    def import_dir(self, directory: str | Path) -> Payload:
        """Create a note from every ``*.md`` file under ``directory``, recursively.

        **One request per file, in a fixed (sorted) order, and no batching.** A file naming
        ``[[Some Title]]`` before that title's own file has been walked yet gets an unresolved edge
        at its own creation — Q26's honest rendering, per ADR 0003 — and the backend's own
        ``resolve_pending_note_links`` (KAN-563) is what points it at the right note the moment
        that later file *is* created, in the same transaction as the file that finally supplies the
        title. That is already correct for *any* creation order, which is what lets this method be
        a plain loop rather than a two-pass walk that builds a graph first: the order only changes
        which notes look unresolved in between two files landing, never the end state once the
        whole directory has been walked.

        Each note's ``path`` becomes the file's own location relative to ``directory`` — the mirror
        of `export_all`'s ``_vault_relative_path``, so a corpus round-tripped through `export_all`
        and back through this method files every note exactly where it was.
        """
        root = Path(directory)
        if not root.is_dir():
            raise UsageError(f"{directory}: not a directory", arg=str(directory))

        created = []
        candidates = (p for p in root.rglob("*.md") if p.is_file())
        for file in sorted(candidates):
            text = _read_text(file, arg=str(file))
            fallback_path = file.relative_to(root).as_posix()
            payload = self._import_document(
                text, fallback_title=file.stem, fallback_path=fallback_path
            )
            created.append(dict(payload.record))

        return Payload.collection(
            noun=NOTE_NOUN,
            envelope_key=NOTE_ENVELOPE,
            records=created,
            columns=NOTE_LIST_COLUMNS,
            prose_fields=NOTE_PROSE_FIELDS,
        )

    def _import_document(self, text: str, *, fallback_title: str, fallback_path: str) -> Payload:
        """The shared half of `import_note` and `import_dir`: parse, create, annotate.

        **Why the front matter's ``kaya_ref`` never reaches the request this method sends, and why
        that is correct rather than an unfinished half of R12.** ADR 0008 §Decision and
        `app/models/note.py`'s own comment both make this permanent: a ref is "allocated by
        Postgres inside the INSERT" from ``note_ref_seq``, never assigned by application code, and
        ``NoteCreate`` (`app/api/schemas.py`) declares ``extra="forbid"`` with no ``ref`` field at
        all — sending one is a `422` naming the field, not a hint the server ignores. There is
        consequently no request this method, or any future one that stays inside R12's fit-check
        ("no new backend route, no new table"), could make that would hand the new note the old
        ref back. BREADBOARD.md's R12 table says an import "carries [a free ref] forward"; that
        turned out to describe a capability the current schema does not have a door for, which is
        this card's one finding worth flagging rather than quietly working around.

        So every import mints a fresh ref — the one thing `create_note` can do — and what this
        method adds is honest bookkeeping about the ref the file *asked* for:
        ``imported_from_ref`` is that ref (or ``None`` for a file with no ``kaya_ref`` at all, the
        "absent" case BREADBOARD.md does describe correctly), and ``original_ref_status`` is
        whether it was free or already taken *at the moment of this import* — informational only,
        since neither answer changes what happens next. A future card could close this gap for
        real, by giving ``NoteCreate`` an optional ``ref`` the route accepts only when the sequence
        has not passed it — that is a new field on an existing route, not a new one, so it may
        still fit R12's constraint, but it is schema and route work this card's scope excludes.

        Title, in order: the front matter's own ``title``, the body's first line if it is a
        markdown ``# heading``, the file's own name, or ``"Untitled"`` — the last resort a title
        that must be non-empty (`NoteCreate.title`) forces. Path: the front matter's own ``path``
        if the file carries kaya's shape, else ``fallback_path`` (empty for a standalone
        `import_note`, the file's own vault-relative location for `import_dir`). Body: verbatim,
        the same "no link rewriting" R12 headline `frontmatter.compose_document` already argues for
        — the wikilinks a body carries resolve on the server, at creation, the same as any other.
        """
        document = parse_document(text)
        original_ref = document.get(REF_KEY)
        title = (
            document.get(TITLE_KEY)
            or _title_from_body(document.body)
            or fallback_title
            or "Untitled"
        )
        path = document.get(PATH_KEY) or fallback_path

        status = self._ref_status(original_ref) if original_ref else None
        created = self.create_note(title, body=document.body, path=path or None)

        record = dict(created.record)
        record[IMPORTED_FROM_REF_KEY] = original_ref
        record[ORIGINAL_REF_STATUS_KEY] = status
        return Payload.entity(
            noun=NOTE_NOUN,
            envelope_key=NOTE_ENVELOPE,
            record=record,
            columns=NOTE_COLUMNS,
            prose_fields=NOTE_PROSE_FIELDS,
        )

    def _ref_status(self, ref: str) -> str | None:
        """Whether ``ref`` currently names a note — ``"free"``, ``"taken"``, or ``None`` when this
        client cannot tell (a malformed ref, or the request itself failing).

        A plain `get_note`, and the same unscoped-fetch distinction `authorize_note` exists to make
        is what this reads: a `404` means nobody holds it (``free``); a `403` means somebody else
        does (``taken``, without this caller ever learning whose); a `200` means the caller's own
        note does (``taken``). Anything else — a `400` for a ref this module cannot even parse, a
        `TransportError` — degrades to ``None`` rather than raising, because this check is a
        courtesy note on an import that is going to mint a fresh ref regardless (see
        `_import_document`); a transient failure here must never be the reason a whole import
        fails.
        """
        try:
            self.get_note(ref)
        except ApiError as exc:
            if exc.status == 404:
                return REF_STATUS_FREE
            if exc.status == 403:
                return REF_STATUS_TAKEN
            return None
        except TransportError:
            return None
        return REF_STATUS_TAKEN

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


def _vault_relative_path(note: dict[str, Any]) -> PurePosixPath:
    """Where `export_all` writes one note, relative to the vault directory.

    ``note["path"]`` is ADR 0008's mutable metadata column: no uniqueness constraint, no format
    enforced by the API (`app/models/note.py`: "the API decides the convention; the column just
    stores what it is told"), so it can be empty, can contain ``..`` if someone typed it by hand
    through `kaya note move`, and carries no guarantee of a ``.md`` suffix. This function is the one
    place that turns it into a filesystem path a whole directory of writes can trust:

    - ``..`` and ``.`` segments, and empty segments from a leading/trailing/doubled ``/``, are
      dropped — the traversal guard. A ``path`` cannot walk `export_all`'s write outside the
      directory the caller named, however it was set.
    - An empty result (an empty ``path``, or one that was *only* traversal segments) falls back to
      ``<ref>.md`` at the vault root — every note has a ref, so this is always available and always
      unique across one export.
    - A last segment with no ``.md``/``.markdown`` suffix gets ``.md`` appended, because a vault
      opened in Obsidian only recognises those two as notes (BREADBOARD.md's R12: "a vault opened in
      Obsidian should just work").
    """
    ref = note["ref"]
    raw = note.get("path") or ""
    segments = [part for part in raw.replace("\\", "/").split("/") if part not in ("", ".", "..")]
    if not segments:
        return PurePosixPath(f"{ref}.md")
    if not segments[-1].lower().endswith((".md", ".markdown")):
        segments[-1] = f"{segments[-1]}.md"
    return PurePosixPath(*segments)


def _read_text(path: Path, *, arg: str) -> str:
    """A file's contents as UTF-8, or the same ``UsageError`` `kaya_cli.parsing.resolve_body` gives
    ``--body-file`` for the same two failures — an unreadable path, or one that is not UTF-8 text.
    """
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise UsageError(f"{arg}: {exc.strerror or 'could not be read'}", arg=arg) from None
    except UnicodeDecodeError:
        raise UsageError(f"{arg}: not valid UTF-8 text", arg=arg) from None


def _title_from_body(body: str) -> str | None:
    """A title from the body's own first line, if — and only if — that line is a markdown
    ``# Heading`` opening the file. Used only when the front matter carried none (an arbitrary
    markdown file with no ``title:`` of its own): the first non-blank line has to be the heading
    for this to apply, so a body that opens with prose and happens to have a heading further down is
    left to the filename fallback instead of guessing which heading the author meant as the title.
    """
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("# "):
            heading = stripped[2:].strip()
            return heading or None
        return None
    return None


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
