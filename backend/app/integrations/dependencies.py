"""FastAPI wiring for card/epic resolution and the board-embed integration, and nothing else —
KAN-566, KAN-1049.

The sibling of ``app/auth/dependencies.py``, deliberately the same shape: every decision with an
argument in it lives one module down (``card_resolution.py`` or ``board_embed.py``, whichever a
given block wires), and what is left here is which object gets built where and how long it lives.
That is the part a unit test cannot reach without a framework and does not need to.

Lifetimes for card/epic resolution, and each one is the reason ``app/auth/dependencies.py`` gives
for its twin:

- **The cache is process-wide.** A per-request cache caches nothing, and this one exists to make a
  second render of the same note cost no upstream call at all (spike 0001's own acceptance line).
  Built lazily rather than at import, so a fixture that repoints ``KAYA_PANDAN_URL`` is not racing
  an import that already read it.
- **The upstream is process-wide**, so its ``httpx.Client`` pools connections to pandan and a miss
  pays for a TLS handshake roughly never. Measured on the identity path, where the same choice made
  a warm miss 387 ms rather than a handshake plus a round trip.
- **The resolver is per-request.** It holds no state — every mutable thing it touches is the cache
  or the upstream above — so a fresh one per request costs an object allocation and buys the
  property that its ``clock`` and its budgets are read from settings at the time of the call.

Deliberately **not** here: a ``SingleFlight``. ``card_resolution.py``'s docstring argues that at
length and the argument is unchanged by having a caller — a resolution miss is bounded by this
module's own deadline rather than by a cold identity round trip, so two renders racing for one ref
cost one duplicate request instead of a stalled service.

The board-embed wiring below follows the same upstream/resolver split, minus the cache —
``board_embed.py``'s module docstring explains why that integration deliberately has none.
"""

from collections.abc import Callable
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.auth import Principal, get_principal
from app.config import get_settings
from app.db import get_session
from app.identity.pandan_link import linked_pandan_bearer
from app.integrations.board_embed import BoardEmbedResolver, BoardEmbedUpstream
from app.integrations.board_embed import default_resolver as default_board_embed_resolver
from app.integrations.board_embed import default_upstream as default_board_embed_upstream
from app.integrations.card_resolution import (
    CardEpicCache,
    CardEpicResolver,
    CardEpicUpstream,
    default_cache,
    default_resolver,
    default_upstream,
)
from app.integrations.pandan_link import PandanLinkVerifier
from app.integrations.pandan_link import default_verifier as default_pandan_link_verifier
from app.integrations.storage import ObjectStorage
from app.integrations.storage import default_storage as default_object_storage


@lru_cache(maxsize=1)
def get_card_epic_cache() -> CardEpicCache:
    return default_cache(get_settings())


@lru_cache(maxsize=1)
def get_card_epic_upstream() -> CardEpicUpstream:
    return default_upstream(get_settings())


def get_card_epic_resolver() -> CardEpicResolver:
    return default_resolver(get_card_epic_upstream(), get_card_epic_cache(), get_settings())


def reset_card_resolution() -> None:
    """Drop the cached singletons. The twin of ``app.auth.dependencies.reset_auth``, and needed for
    the same reason: a cache surviving into the next test serves an answer that test never asked
    for, which is the classic way a resolution suite passes alone and fails in a full run."""
    get_card_epic_cache.cache_clear()
    get_card_epic_upstream.cache_clear()


@lru_cache(maxsize=1)
def get_board_embed_upstream() -> BoardEmbedUpstream:
    """Process-wide, for the reason ``get_card_epic_upstream`` gives: an ``httpx.Client`` pools
    connections to pandan, and rebuilding one per request would pay a TLS handshake on every
    render. No cache singleton alongside it — ``board_embed.py``'s module docstring explains why
    this integration deliberately has none."""
    return default_board_embed_upstream(get_settings())


def get_board_embed_resolver() -> BoardEmbedResolver:
    """Per-request, same as ``get_card_epic_resolver``: the resolver holds no state of its own, so
    a fresh one costs an allocation and buys nothing to leak between requests."""
    return default_board_embed_resolver(get_board_embed_upstream())


def reset_board_embed() -> None:
    """Drop the cached upstream singleton. The twin of ``reset_card_resolution``."""
    get_board_embed_upstream.cache_clear()


@lru_cache(maxsize=1)
def get_pandan_link_verifier() -> PandanLinkVerifier:
    """Process-wide, for the reason `get_card_epic_upstream` gives: `PandanHttpVerifier` pools an
    `httpx.Client` to pandan, and rebuilding one per request would pay a TLS handshake on every
    connect-a-pandan-account submission."""
    return default_pandan_link_verifier(get_settings())


def reset_pandan_link() -> None:
    """Drop the cached verifier. The twin of `reset_board_embed`, needed for the identical
    reason."""
    get_pandan_link_verifier.cache_clear()


@lru_cache(maxsize=1)
def get_object_storage() -> ObjectStorage:
    """Process-wide, for the reason `get_card_epic_upstream` gives: the real implementation's
    `boto3` client pools connections, and building one per request would pay a handshake on every
    upload or fetch. Built lazily, not at import — a fixture that repoints `KAYA_R2_*` must not
    race an import that already read the old values.

    Raises if R2 is not configured (`storage.py`'s `default_storage`) — the attachment routes are
    the only callers, so that surfaces as a `500` on the first attachment request in an environment
    with no bucket, rather than at process boot where every other route would go down with it."""
    return default_object_storage(get_settings())


def reset_object_storage() -> None:
    """Drop the cached singleton. The twin of `reset_card_resolution`, needed for the identical
    reason: a fixture repointing `KAYA_R2_*` must not have the previous test's client survive it."""
    get_object_storage.cache_clear()


def card_resolution_bearer(
    principal: Annotated[Principal, Depends(get_principal)],
    db: Annotated[Session, Depends(get_session)],
) -> str | None:
    """The caller's own **linked** pandan PAT, decrypted, or ``None`` if they have never connected
    one — what `app/integrations/card_resolution.py`'s `CardEpicResolver` forwards to pandan to
    resolve `KAN-`/`EPIC-` wikilinks (`app/api/links.py`).

    **Replaces forwarding the caller's own kaya bearer, which this route used to do and which was a
    bug after ADR 0012's cutover (KAN-1740).** Before that cutover the caller's own kaya-side
    bearer *was* a pandan credential (ADR 0002: one PAT authenticated both apps), so forwarding it
    verbatim was correct. `KAN-1740` ended that — a `kaya_pat_…` (or no bearer at all, from a cookie
    session) reaches pandan as a credential it has never seen, indistinguishable from an outage by
    `CardEpicResolver`'s existing degrade-to-unresolved path. `app/api/embeds.py`'s board-embed
    preview hit the identical defect first and was fixed the same way in `KAN-1741`
    (`app/identity/pandan_link.py`'s `linked_pandan_bearer`, reused here rather than
    reimplemented) — this dependency is that fix applied to wikilink resolution.

    ``None`` is a degradation, not a refusal, as in `pandan_bearer` below: a route
    depending on this also depends on `get_principal`, which already answers `401` before the route
    body runs, so in practice this only returns `None` for a caller who has simply never linked a
    pandan account — and `CardEpicResolver.resolve` (via `app/api/links.py`) already treats a `None`
    bearer as "resolve nothing, render unresolved" (ADR 0003), never a `401` of its own.
    """
    return linked_pandan_bearer(db, principal.id)


PandanBearerLookup = Callable[[], str | None]
"""Call it to get the caller's linked pandan PAT (or ``None``). A lookup, not a value, so a route
that only sometimes needs pandan pays for the database query only then."""


def pandan_bearer(
    principal: Annotated[Principal, Depends(get_principal)],
    db: Annotated[Session, Depends(get_session)],
) -> PandanBearerLookup:
    """A lookup for the caller's linked pandan PAT, for **team-default access** (ADR 0011,
    `app/api/refs.py` and `app/api/notes.py`). Calling it returns the PAT, or ``None`` if they never
    linked one.

    This used to forward the caller's own kaya bearer, which pandan has not recognised since ADR
    0012 (a `kaya_pat_…` is not a pandan credential), so every non-owner of a team-shared note got
    the soft-fail "no memberships" answer whatever pandan held (KAN-1804). The linked PAT is the one
    credential pandan can resolve to the same person, exactly as for wikilink resolution and the
    board embed. ``None`` degrades to "no team memberships known" (ADR 0003, ADR 0011 Fork 3), never
    a refusal, so an unlinked caller keeps every note they own.

    **Lazy, and it releases the connection when called.** The owner path of `resolve_note` never
    needs this, so it must not cost a query. When it is called the caller goes on to ask pandan over
    the network, and a sync handler must not hold a Postgres connection across that
    (`app/api/links.py`'s `_release_the_connection`), so the lookup commits. ``expire_on_commit=
    False`` (`app/db.py`) keeps the session's objects usable afterwards.
    """

    def lookup() -> str | None:
        found = linked_pandan_bearer(db, principal.id)
        db.commit()
        return found

    return lookup


PandanBearer = Annotated[PandanBearerLookup, Depends(pandan_bearer)]
CardResolutionBearer = Annotated[str | None, Depends(card_resolution_bearer)]
CardResolver = Annotated[CardEpicResolver, Depends(get_card_epic_resolver)]
BoardResolver = Annotated[BoardEmbedResolver, Depends(get_board_embed_resolver)]
PandanLinkVerify = Annotated[PandanLinkVerifier, Depends(get_pandan_link_verifier)]
ObjectStorageDep = Annotated[ObjectStorage, Depends(get_object_storage)]
