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

from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.auth import Principal, get_principal
from app.auth.dependencies import bearer_scheme
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


def caller_bearer(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> str | None:
    """The caller's own bearer, verbatim, for forwarding to pandan — `app/api/refs.py`'s
    team-default access check (ADR 0011, R16.3) is the only remaining reason to forward it: pandan
    still has no concept of a kaya-minted `kaya_pat_…`, so `TeamAccessResolver.member_of` only ever
    gets an answer for a caller whose kaya-side bearer *is itself* still a valid pandan credential —
    unaffected callers on kaya's now-standalone identity (ADR 0012) simply see no team memberships,
    the same soft-fail ADR 0011 already accepts for pandan being unreachable outright.

    **Card/epic wikilink resolution used to be a second consumer of this and no longer is.**
    `app/integrations/card_resolution.py` forwarded this same caller bearer to pandan until it hit
    the identical, KAN-1740-shaped defect `app/api/embeds.py`'s board-embed preview had already been
    fixed for (KAN-1741): a `kaya_pat_…` reaches pandan as a credential it has never seen. Wikilink
    resolution now uses `card_resolution_bearer`, below — the caller's *linked* pandan PAT, not this
    one — for exactly that reason.

    **It reuses ``app.auth.dependencies.bearer_scheme`` rather than reading the header itself**, so
    the claim in that module's comment — "this is the only place in kaya where anything about the
    ``Authorization`` header is parsed, and it is Starlette doing the parsing" — stays true with a
    second consumer. What is parsed there is the HTTP *scheme*, the literal ``Bearer `` in front;
    nothing here or downstream looks at the credential itself (ADR 0002: kaya has no token format).

    ``str | None``, and ``None`` is a **degradation rather than a refusal**. Every route that asks
    for this also depends on ``get_principal``, which already answers `401` for a request with no
    usable header, so in practice a route body never sees ``None``; raising a second `401` here
    would be a second copy of an error shape ``principal_from_bearer`` already owns, for a case that
    cannot arrive. If one ever did — a route wired to this and not to a principal — the ADR
    0003-shaped answer is a soft-fail: no team ids resolved, nothing else affected.

    The value is returned and never stored, logged or put in an exception (Q41/Q42).
    """
    return credentials.credentials if credentials is not None else None


def card_resolution_bearer(
    principal: Annotated[Principal, Depends(get_principal)],
    db: Annotated[Session, Depends(get_session)],
) -> str | None:
    """The caller's own **linked** pandan PAT, decrypted, or ``None`` if they have never connected
    one — what `app/integrations/card_resolution.py`'s `CardEpicResolver` forwards to pandan to
    resolve `KAN-`/`EPIC-` wikilinks (`app/api/links.py`).

    **Replaces forwarding `caller_bearer` here, which is what this route used to depend on and was
    a bug after ADR 0012's cutover (KAN-1740).** Before that cutover the caller's own kaya-side
    bearer *was* a pandan credential (ADR 0002: one PAT authenticated both apps), so forwarding it
    verbatim was correct. `KAN-1740` ended that — a `kaya_pat_…` (or no bearer at all, from a cookie
    session) reaches pandan as a credential it has never seen, indistinguishable from an outage by
    `CardEpicResolver`'s existing degrade-to-unresolved path. `app/api/embeds.py`'s board-embed
    preview hit the identical defect first and was fixed the same way in `KAN-1741`
    (`app/identity/pandan_link.py`'s `linked_pandan_bearer`, reused here rather than
    reimplemented) — this dependency is that fix applied to wikilink resolution.

    ``None`` is a degradation, not a refusal, for the same reason `caller_bearer` gives: a route
    depending on this also depends on `get_principal`, which already answers `401` before the route
    body runs, so in practice this only returns `None` for a caller who has simply never linked a
    pandan account — and `CardEpicResolver.resolve` (via `app/api/links.py`) already treats a `None`
    bearer as "resolve nothing, render unresolved" (ADR 0003), never a `401` of its own.
    """
    return linked_pandan_bearer(db, principal.id)


CallerBearer = Annotated[str | None, Depends(caller_bearer)]
CardResolutionBearer = Annotated[str | None, Depends(card_resolution_bearer)]
CardResolver = Annotated[CardEpicResolver, Depends(get_card_epic_resolver)]
BoardResolver = Annotated[BoardEmbedResolver, Depends(get_board_embed_resolver)]
PandanLinkVerify = Annotated[PandanLinkVerifier, Depends(get_pandan_link_verifier)]
ObjectStorageDep = Annotated[ObjectStorage, Depends(get_object_storage)]
