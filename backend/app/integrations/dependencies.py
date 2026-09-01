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

from app.auth.dependencies import bearer_scheme
from app.config import get_settings
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


def caller_bearer(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> str | None:
    """The caller's own bearer, verbatim, for forwarding to pandan (KAN-564's whole premise).

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
    0003-shaped answer is the one `app/api/links.py` gives it: resolve nothing, render the links
    unresolved, do not fail the read. A note's own edges are local and are never at stake.

    The value is returned and never stored, logged or put in an exception (Q41/Q42). It exists for
    exactly one hop: into ``CardEpicResolver.resolve``, which keys its cache on
    ``sha256(bearer)`` and holds no raw credential either.
    """
    return credentials.credentials if credentials is not None else None


CallerBearer = Annotated[str | None, Depends(caller_bearer)]
CardResolver = Annotated[CardEpicResolver, Depends(get_card_epic_resolver)]
BoardResolver = Annotated[BoardEmbedResolver, Depends(get_board_embed_resolver)]
