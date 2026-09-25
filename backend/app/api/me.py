"""``GET /api/v1/me`` — the one thing an authenticated caller is allowed to ask about itself
(ADR 0012's amendment, KAN-1743, mirrors pandan's own `GET /api/v1/me`, KAN-530).

Two reasons this exists now, both new since ADR 0012's cutover:

1. **`kaya auth status`** (KAN-1743) needs something to call. Before ADR 0012, kaya had no identity
   of its own to introspect — a caller's credential was pandan's, and asking "who am I" meant
   asking pandan. Kaya now resolves every caller from its own tables (`get_principal`), so it can
   answer the question about itself.
2. **`app/integrations/pandan_link.py`'s `PandanHttpVerifier`** already calls the identical route on
   *pandan* to verify a pasted pandan PAT before storing it — this is kaya's own mirror of that same
   small, useful-standalone endpoint (ADR 0002's own words for why pandan built it in the first
   place: "there is currently no way for a PAT holder to ask who it is").

**Deliberately the minimum: `id` and `email`, nothing else.** There is nothing to authorize against
— a caller either has a working credential or does not — so the only outcomes are `200` and
`get_principal`'s own `401`, never a `403`. Mirrors `app/api/meta.py`'s "one key and must keep
returning one key" discipline for the identical reason: the next person here will want to add a
field, and each one is a fact this route publishes to anyone holding *any* valid credential, not
just the caller it happens to matter to.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import Principal, get_principal

router = APIRouter(prefix="/api/v1", tags=["me"])

CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


class MeRead(BaseModel):
    """`GET /api/v1/me`'s body. Two fields, deliberately — see the module docstring."""

    id: str
    email: str


@router.get("/me", summary="Who this credential authenticates as")
def read_me(principal: CurrentPrincipal) -> MeRead:
    return MeRead(id=str(principal.id), email=principal.email)
