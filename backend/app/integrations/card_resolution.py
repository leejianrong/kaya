"""Card/epic resolution against pandan, with the *caller's own* PAT, cached (KAN-564).

This is the pandan-facing half of wikilink resolution: turning `[[KAN-12]]` / `[[EPIC-3]]` into a
title and (for a card) a column. KAN-563 does the other half — note-to-note resolution by title,
entirely local — in `app/wikilinks.py`, `app/note_links.py` and `app/models/note_link.py`. This
module does not import, and is not imported by, any of those three; the two halves share nothing
but the parser's ref vocabulary (`KAN-`/`EPIC-`, never `PAN-`, per ADR 0003), which this module
re-derives on its own terms via `classify_ref` rather than importing `app.wikilinks`, so KAN-563's
work and this card's are free to land as two independent PRs with no merge collision between them.

## Read this before touching the request-shaping code below: spike 0001 is now partially stale

[Spike 0001](../../../docs/spikes/0001-wikilink-ref-batching.md) settled, on 2026-08-01, that pandan
has no batch card-read endpoint and recommended a bounded page-walk of `GET
/api/v1/cards?limit=200` as the least-bad option, explicitly *not* waiting on [pandan issue
254](https://github.com/leejianrong/pandan/issues/254) (a `?refs=` batch parameter). **Issue 254
has since shipped.** Verified live against `https://simple-kanban-jian.fly.dev/openapi.json` and
the endpoint itself on 2026-08-18, with a real PAT:

    GET /api/v1/cards?refs=KAN-560,KAN-561,EPIC-3,KAN-999999
    -> 200, body = the two resolvable cards (order-preserving, de-duplicated)
    -> header X-Unresolved-Selectors: EPIC-3,KAN-999999
       (EPIC-3 is a real, well-formed ticket that just isn't a card — reported identically to a
       ticket that plain doesn't exist, which is deliberate: distinguishing them would leak
       whether a row exists on a board the caller can't see)
    GET /api/v1/cards?refs=NOSUCHTICKET-99999
    -> 422 {"detail": "refs must be tickets like 'KAN-12', got 'NOSUCHTICKET-99999'"}

and separately, `board_id` omitted still returned a card belonging to board 18 while the PAT's
default configured board is board 5 — confirming resolution is scoped to *every* board the caller
owns, in one request, with no need to know which board a ticket lives on. `GET /api/v1/epics` never
gained a `refs` parameter, but it never needed pagination either (confirmed: no `limit`/`cursor` in
its live OpenAPI schema) — one un-paginated, owner-scoped request returns every epic across every
board the caller can see, in any resolution batch that needs one.

So the mechanism this module implements is **not** the spike's page-walk. It is the shape the
spike's own "what would change the answer" section named as the exit case — "issue 254 ships: swap
the sweep for one call, everything else stands" — except that call turned out to batch by *ticket
ref* rather than by internal id, which the spike had separately proven kaya could never have used
anyway (no route accepts a `card_id: int` that came from a wikilink). Everything the spike actually
argued for is unchanged and still true here: the caller's own PAT (never a kaya-owned credential),
one request in flight at a time, a cache with its own TTL, a bounded number of requests, a total
deadline, and unresolved-rather-than-error as the only outcome a note render ever sees. What
changed is that "bounded" now means chunking a `refs=` parameter past pandan's own
`MAX_CARD_SELECTORS` cap (verified live at 100) rather than paging through the whole board, which
is strictly better on every axis the spike measured: requests now scale with **distinct refs
actually in the note**, not with board size, so a forty-ref note is one request instead of the
spike's three, and a *board* growing past a few thousand cards — the spike's stated
"issue 254 ships" trigger and its own "what would change the answer" row about very large boards —
no longer matters at all. `docs/spikes/0001-…` and `SLICES.md`'s V5 build-plan step 1 (which still
says "V5 does not wait on pandan issue 254" and describes requests scaling "with pages, not refs")
are stale as a result and worth a follow-up docs PR; this module's docstring is the live account.

## The cross-caller leak this module exists to prevent

SLICES.md V5's test plan names it directly: "a note referencing a card the reader cannot see
renders unresolved rather than leaking the title." Pandan's own owner-scoping is what makes an
answer *correct* for a given caller (a ref your PAT can't see resolves as unresolved, never as a
403 — see the `EPIC-3` line above), but a cache keyed on the bare ticket number would silently
discard that scoping one layer up: caller A resolves `KAN-99`, the cache remembers a title, caller
B — who cannot see board … that `KAN-99` lives on — asks for the same ref and gets A's cached
answer instead of pandan's real "no" for B. `CardEpicCache` keys every entry on
`(sha256(bearer), ticket_number)`, never on the bare ref, so A's cache entry is not reachable
through B's bearer at all. `test_a_callers_cache_entry_never_leaks_to_another_caller` proves this
by resolving through A first, confirming the entry is warm, and then resolving the *same ref*
through B and asserting the upstream sees a second call rather than the cache answering for it.

## Why this is not reachable by an unauthenticated caller, and why it still needs a bound

`resolve()` is only ever called with a bearer that has already cleared ADR 0002's principal
resolution on the request it is serving — KAN-566 wired that in, at `GET /api/v1/notes/{ref}/links`,
whose `NoteFromRef` dependency resolves a principal from the same header before the route body runs
— so unlike `PrincipalCache`'s negative half — built specifically to shed load from a stranger
sending garbage `Authorization` headers with no request past that — this cache is not a surface a
caller can reach without a credential that already worked. It still needs `DEFAULT_MAX_ENTRIES`:
the key space here is *per (caller, ticket)* rather than per-caller, so one authenticated caller
referencing many distinct nonexistent refs across many notes over time grows this cache faster than
`PrincipalCache`'s one-entry-per-token ever could. Bounded, with the same evict-expired-then-oldest
policy `PrincipalCache` uses and the same reasoning for it (see `cache.py`).

## What this module deliberately does not do

- **No single-flight coalescing.** `app/auth/single_flight.py` exists because a cold *identity*
  miss can be tens of seconds and forty concurrent requests on one token is kaya's normal opening
  move. A card-resolution miss is bounded at a few seconds by this module's own deadline, and two
  renders racing to resolve the same ref cost one duplicate request, not a stalled service. Adding
  it would be solving a problem this card does not have evidence of.
- **No fan-out, no thread pool, no async client.** ADR 0001 stands; every upstream call here is
  synchronous and made one at a time, exactly as it was in the spike's recommendation.
- **No raising to the caller for a network reason.** `CardEpicUpstream` implementations raise
  `CardEpicUnavailable` — mirroring `app.auth.principal.UpstreamUnavailable` — but `resolve()`
  catches it internally. A timeout, a connection failure, hitting the deadline or hitting the
  request-count cap all collapse into the same outward signal as a ref pandan genuinely does not
  have: an entry mapped to `None` in the returned dict. That is this card's job per its brief —
    "this card's job is to expose that outcome cleanly … not to raise" — and it is what keeps ADR
  0003's line ("nothing in kaya may block on pandan") true one layer past the HTTP boundary:
  `app/api/links.py` calls `resolve()` from inside a note-render path with no `try/except` of its
  own, and that absence is deliberate rather than incidental — a handler there would be a second
  opinion about a decision made here, and the first thing a second opinion does is disagree.
"""

import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

import httpx

from app.auth.cache import digest
from app.auth.upstream import split_timeout
from app.config import Settings

CARDS_PATH = "/api/v1/cards"
EPICS_PATH = "/api/v1/epics"

DEFAULT_MAX_ENTRIES = 8192
"""Bound on `CardEpicCache`. See the module docstring's "why this still needs a bound" section."""


# --- What gets resolved -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResolvedTicket:
    """A card or epic pandan resolved for the caller — what a wikilink pill needs to render."""

    kind: Literal["card", "epic"]
    id: int
    ticket_number: str
    title: str
    column: str | None
    """Pandan's column name for a card (e.g. ``"in_progress"``); always ``None`` for an epic —
    epics have no column, and inventing one to make the shape uniform would be a fact this module
    does not have."""


def classify_ref(ref: str) -> Literal["card", "epic"] | None:
    """``KAN-`` is a card, ``EPIC-`` is an epic, anything else is not a ref this module resolves.

    Deliberately re-derived rather than imported from `app.wikilinks` (KAN-561's parser already
    enforces this vocabulary on save, and never hands this module a `PAN-` ref in practice) — see
    the module docstring on why the two halves of KAN-566's future caller stay decoupled.
    """
    if ref.startswith("KAN-"):
        return "card"
    if ref.startswith("EPIC-"):
        return "epic"
    return None


# --- The upstream seam ---------------------------------------------------------------------------


class CardEpicUnavailable(Exception):
    """Pandan could not be asked. Mirrors `app.auth.principal.UpstreamUnavailable` on purpose —
    same shape, same reason: a caller distinguishing "asked and got nothing" from "could not ask"
    needs the exception, even though `CardEpicResolver.resolve()` (the only caller in this repo)
    deliberately does not re-raise it. Carries no bearer, not even a fragment."""


@dataclass(frozen=True, slots=True)
class CardBatch:
    """One parsed `GET /api/v1/cards?refs=...` response."""

    cards: tuple[ResolvedTicket, ...]
    unresolved_refs: tuple[str, ...]
    """Refs from the request pandan could not resolve for this caller, read verbatim out of the
    `X-Unresolved-Selectors` response header (comma-separated, order preserved). Absent header
    means nothing missed — an empty tuple either way, so a caller never has to special-case it."""


class CardEpicUpstream(Protocol):
    """The two calls this card needs, behind a seam fakeable at the HTTP boundary — ADR 0002's
    reason for `IdentityUpstream` applies unchanged: pandan is a runtime dependency this suite
    does not want a network for, and `httpx.MockTransport` lets a test assert against the real
    request `PandanCardEpicUpstream` would put on the wire."""

    def fetch_cards(self, bearer: str, refs: Sequence[str]) -> CardBatch:
        """One request. ``refs`` must already be at or under pandan's combined-selector cap —
        chunking a longer list is `CardEpicResolver`'s job, not this seam's."""
        ...

    def fetch_epics(self, bearer: str) -> Sequence[ResolvedTicket]:
        """One request: every epic the caller can see, on every board they own. Pandan's `/epics`
        route takes no `refs` filter and no pagination — confirmed live, see the module
        docstring — so there is nothing here for a caller to chunk or page through."""
        ...


class PandanCardEpicUpstream:
    """``CardEpicUpstream`` over real HTTP. The bearer is forwarded byte for byte, exactly like
    `PandanIdentityUpstream` — this module has no more business parsing it than that one does."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: httpx.Timeout | float,
        client: httpx.Client | None = None,
    ) -> None:
        self._cards_url = base_url.rstrip("/") + CARDS_PATH
        self._epics_url = base_url.rstrip("/") + EPICS_PATH
        # `timeout` configures the client this builds; a `client` passed in (tests only) carries
        # its own — see `PandanIdentityUpstream`'s constructor comment, the asymmetry is the same.
        self._client = client if client is not None else httpx.Client(timeout=timeout)
        # No explicit `Accept-Encoding` header: httpx's `Client` already sends
        # ``gzip, deflate`` by default (verified: `httpx.Client().headers["accept-encoding"]`), so
        # spike 0001's "requesting gzip" is free rather than a header this module has to add.

    def fetch_cards(self, bearer: str, refs: Sequence[str]) -> CardBatch:
        try:
            response = self._client.get(
                self._cards_url,
                params={"refs": ",".join(refs)},
                headers={"Authorization": f"Bearer {bearer}"},
            )
        except httpx.HTTPError as exc:
            raise CardEpicUnavailable(f"{self._cards_url} is unreachable") from exc

        if response.status_code != 200:
            # Includes a 422: pandan's own selector-format or selector-cap refusal. The resolver
            # chunks under the cap and only ever sends well-formed `KAN-n` refs, so this should not
            # happen in practice — but if pandan's cap ever drops, or ships a spelling rule this
            # module doesn't know about, degrading to "unavailable" (and therefore to unresolved,
            # never cached negative) is the ADR 0003-safe answer, not raising into a note render.
            raise CardEpicUnavailable(f"{self._cards_url} answered {response.status_code}")

        try:
            payload = response.json()
            cards = tuple(
                ResolvedTicket(
                    kind="card",
                    id=int(item["id"]),
                    ticket_number=str(item["ticket_number"]),
                    title=str(item["title"]),
                    column=str(item["column"]),
                )
                for item in payload
            )
        except (ValueError, TypeError, KeyError, httpx.HTTPError) as exc:
            raise CardEpicUnavailable(
                f"{self._cards_url} returned a body kaya could not read"
            ) from exc

        raw_header = response.headers.get("X-Unresolved-Selectors", "")
        unresolved = tuple(ref for ref in raw_header.split(",") if ref)
        return CardBatch(cards=cards, unresolved_refs=unresolved)

    def fetch_epics(self, bearer: str) -> Sequence[ResolvedTicket]:
        try:
            response = self._client.get(
                self._epics_url,
                headers={"Authorization": f"Bearer {bearer}"},
            )
        except httpx.HTTPError as exc:
            raise CardEpicUnavailable(f"{self._epics_url} is unreachable") from exc

        if response.status_code != 200:
            raise CardEpicUnavailable(f"{self._epics_url} answered {response.status_code}")

        try:
            payload = response.json()
            return tuple(
                ResolvedTicket(
                    kind="epic",
                    id=int(item["id"]),
                    ticket_number=str(item["ticket_number"]),
                    title=str(item["name"]),
                    column=None,
                )
                for item in payload
            )
        except (ValueError, TypeError, KeyError, httpx.HTTPError) as exc:
            raise CardEpicUnavailable(
                f"{self._epics_url} returned a body kaya could not read"
            ) from exc


# --- The cache: scoped per caller, and that scoping is the whole point --------------------------


@dataclass(frozen=True, slots=True)
class _Entry:
    ticket: ResolvedTicket | None
    """``None`` is a confirmed absence: pandan was asked, with this caller's bearer, and this ref
    was not among the results. Never written for an outage — see `CardEpicResolver.resolve`."""

    expires_at: float


class CardEpicCache:
    """TTL cache of resolved tickets, keyed on ``(sha256(bearer), ticket_number)``. Thread-safe,
    with the same reasoning and the same two rules as `app.auth.cache.PrincipalCache` — nothing
    injected (the clock) runs while `_lock` is held, and `_evict` runs with the lock already held
    and never takes it — because the failure mode `PrincipalCache`'s docstring records (a `del` on
    a key another thread already evicted, raising `KeyError` from inside a sync FastAPI dependency
    that Starlette runs in its threadpool) applies here identically: this cache is read and written
    from the same kind of concurrent, sync request handling.

    **The key is composite on purpose.** A bare ``ticket_number`` key would let one caller's
    resolution answer a second caller's lookup of the same ref, which is exactly the over-disclosure
    SLICES.md V5 calls out by name (see the module docstring). Pandan already scopes an *answer* to
    the caller that asked; a bare-ticket cache key would discard that scoping one layer up, for
    every caller after the first one to resolve any given ref.

    A separate class rather than a second `PrincipalCache` with a different TTL, because the key
    shape differs (composite, not a bare digest) and because ADR 0003 / spike 0001 / SLICES.md V5
    all call for "a TTL separate from the auth cache" as two knobs, not one object with a second
    dial bolted on.
    """

    def __init__(
        self,
        *,
        ttl: float,
        clock: Callable[[], float] = time.monotonic,
        max_entries: int = DEFAULT_MAX_ENTRIES,
    ) -> None:
        self._ttl = ttl
        self._clock = clock
        self._max_entries = max_entries
        self._entries: dict[tuple[str, str], _Entry] = {}
        self._lock = threading.Lock()

    def lookup(self, bearer: str, ticket_number: str) -> tuple[bool, ResolvedTicket | None]:
        """``(hit, ticket)`` — the same three-outcomes-in-two-values shape as `PrincipalCache`,
        and for the same reason: ``(True, None)`` is a cached confirmed-absence, ``(False, None)``
        is a miss that must still ask pandan. Collapsing them would turn every confirmed-absence
        hit into a fresh upstream call, silently undoing the point of caching a "no"."""
        key = (digest(bearer), ticket_number)
        now = self._clock()  # read before the lock, same rule as PrincipalCache
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return (False, None)
            if now >= entry.expires_at:
                del self._entries[key]
                return (False, None)
            return (True, entry.ticket)

    def remember(self, bearer: str, ticket_number: str, ticket: ResolvedTicket | None) -> None:
        key = (digest(bearer), ticket_number)
        now = self._clock()
        with self._lock:
            self._entries.pop(key, None)  # re-insert, so dict order stays recency order
            self._entries[key] = _Entry(ticket=ticket, expires_at=now + self._ttl)
            self._evict(now)

    def _evict(self, now: float) -> None:
        """The caller holds `_lock`. Evict-expired-then-oldest, identical to `PrincipalCache`."""
        if len(self._entries) <= self._max_entries:
            return
        for key in [k for k, entry in self._entries.items() if now >= entry.expires_at]:
            del self._entries[key]
        while len(self._entries) > self._max_entries:
            del self._entries[next(iter(self._entries))]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        """Live *and* expired entries — storage size, not logical size, same as `PrincipalCache`."""
        with self._lock:
            return len(self._entries)


# --- The resolver ---------------------------------------------------------------------------------


class CardEpicResolver:
    """Resolves `KAN-n` / `EPIC-n` refs against pandan, with the caller's own bearer, cached.

    See the module docstring for the mechanism (chunked `refs=` for cards, one unpaginated call
    for epics), the bound (`max_upstream_requests`, `total_deadline_seconds`), and why `resolve()`
    never raises for a network reason.
    """

    def __init__(
        self,
        upstream: CardEpicUpstream,
        cache: CardEpicCache,
        *,
        max_selectors_per_request: int,
        max_upstream_requests: int,
        total_deadline_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._upstream = upstream
        self._cache = cache
        self._max_selectors = max_selectors_per_request
        self._max_requests = max_upstream_requests
        self._deadline_seconds = total_deadline_seconds
        self._clock = clock

    def resolve(self, bearer: str, refs: Sequence[str]) -> dict[str, ResolvedTicket | None]:
        """Every distinct ref in ``refs`` maps to a ``ResolvedTicket`` or ``None`` (unresolved).

        Duplicates collapse to one lookup; the returned dict has exactly one entry per *distinct*
        ref, in first-seen order. Never raises: a timeout, a connection failure, hitting the total
        deadline or hitting the request-count cap all leave whatever is still outstanding mapped to
        `None`, indistinguishable from the outward signal a ref pandan genuinely doesn't have
        (ADR 0003 — see the module docstring's "what this module deliberately does not do").
        """
        result: dict[str, ResolvedTicket | None] = {}
        card_misses: list[str] = []
        epic_misses: list[str] = []

        for ref in dict.fromkeys(refs):  # de-dup, order-preserving — a ref is a string
            hit, cached = self._cache.lookup(bearer, ref)
            if hit:
                result[ref] = cached
                continue
            kind = classify_ref(ref)
            if kind == "card":
                card_misses.append(ref)
            elif kind == "epic":
                epic_misses.append(ref)
            else:
                # Not a ref this module understands. Never asked upstream, never cached — there is
                # nothing pandan-shaped to remember, and the classification is cheap to redo.
                result[ref] = None

        deadline_at = self._clock() + self._deadline_seconds
        requests_made = 0

        def has_budget() -> bool:
            return requests_made < self._max_requests and self._clock() < deadline_at

        # Cards: chunked to pandan's own selector cap, one request in flight at a time.
        outage = False
        for start in range(0, len(card_misses), self._max_selectors):
            chunk = card_misses[start : start + self._max_selectors]
            if outage or not has_budget():
                break
            try:
                batch = self._upstream.fetch_cards(bearer, chunk)
            except CardEpicUnavailable:
                # Stop asking for the rest of this batch too — a pandan that just failed once is
                # not a good bet for the next chunk, and every ref below stays unresolved,
                # uncached (an outage is not evidence a ref doesn't exist).
                outage = True
                break
            requests_made += 1
            unresolved = set(batch.unresolved_refs)
            for card in batch.cards:
                result[card.ticket_number] = card
                self._cache.remember(bearer, card.ticket_number, card)
            for ref in chunk:
                if ref in unresolved or ref not in result:
                    result[ref] = None
                    self._cache.remember(bearer, ref, None)

        # Epics: one call, unpaginated by pandan's own design, covers every epic miss at once.
        if epic_misses and not outage and has_budget():
            try:
                epics = self._upstream.fetch_epics(bearer)
            except CardEpicUnavailable:
                epics = None
            else:
                requests_made += 1
            if epics is not None:
                by_ref = {epic.ticket_number: epic for epic in epics}
                for epic in epics:  # cache every epic returned, not only the referenced ones
                    self._cache.remember(bearer, epic.ticket_number, epic)
                for ref in epic_misses:
                    found = by_ref.get(ref)
                    result[ref] = found
                    self._cache.remember(bearer, ref, found)

        # Anything still missing — deadline hit, request-count cap hit, or an outage broke the
        # loop early — renders unresolved. Not cached: see the two comments above.
        for ref in card_misses + epic_misses:
            result.setdefault(ref, None)

        return result


# --- Wiring helpers (`app/integrations/dependencies.py` owns the Depends() lifecycle) ------------


def default_upstream(settings: Settings) -> CardEpicUpstream:
    return PandanCardEpicUpstream(
        settings.pandan_url,
        timeout=split_timeout(
            connect=settings.card_resolution_connect_timeout_seconds,
            read=settings.card_resolution_read_timeout_seconds,
        ),
    )


def default_cache(settings: Settings) -> CardEpicCache:
    return CardEpicCache(ttl=settings.card_resolution_cache_ttl_seconds)


def default_resolver(
    upstream: CardEpicUpstream,
    cache: CardEpicCache,
    settings: Settings,
) -> CardEpicResolver:
    return CardEpicResolver(
        upstream,
        cache,
        max_selectors_per_request=settings.card_resolution_max_selectors_per_request,
        max_upstream_requests=settings.card_resolution_max_upstream_requests,
        total_deadline_seconds=settings.card_resolution_total_deadline_seconds,
    )
