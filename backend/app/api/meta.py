"""``GET /api/v1/meta`` — the one thing a visitor with no credential is allowed to ask.

Originally KAN-555's landing state used this to tell a visitor *where to mint a PAT*. ADR 0012's
cutover (KAN-1740) retired that use — kaya mints its own PATs now, from its own ``/tokens`` page,
and ``Landing.svelte`` no longer calls this route at all. What is left is KAN-1157's authenticated
nav link: ``App.svelte`` reads ``pandan_url`` to render a link to the linked pandan board once a
caller is signed in. The route stays unauthenticated regardless (see below), and the value it
carries, ``KAYA_PANDAN_URL``, is still backend configuration a browser cannot read any other way.
The two obvious alternatives were both rejected with reasons worth keeping:

- **Hard-coding pandan's origin in the SPA** duplicates configuration that already has exactly one
  home, and breaks any self-hosted pandan — which this route's design has always supported and ADR
  0012 does not change.
- **A build-time ``VITE_PANDAN_URL``** is the thing ``frontend/src/lib/api.ts`` already refuses in
  prose: "an origin baked in at build time is how a frontend ends up needing a per-environment
  build and a CORS policy to go with it." ADR 0001 promises one artifact; a per-environment bundle
  ends that.

**This route is unauthenticated by necessity, not by oversight.** The entire caller it exists for is
a visitor who has no token yet, so requiring one would make it useless. It is safe to answer
anonymously because the value is not a secret: ``app/config.py``'s own docstring draws exactly this
line — "kaya holds no long-lived credential of its own … ``KAYA_PANDAN_URL`` is configuration" — and
Q9's `503` body already puts the same string in front of an unauthenticated caller.

**It returns one key and must keep returning one key.** The next person here will want to add
something — the version, the log level, a feature flag, the SPA's build sha — and each of those is
one more fact published to the internet by a route with no credential in front of it. A meta
endpoint that accumulates keys is a config dump with a friendly name, and the moment one of those
keys is a secret nobody re-reads this file to notice. ``Meta`` has one field;
``tests/unit/test_meta.py`` asserts the response body has exactly one key, so a second one is a
failing build and therefore a decision rather than a commit. If a new fact genuinely needs a public
home, argue for it in a card and change that test on purpose.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import Settings, get_settings

router = APIRouter(prefix="/api/v1", tags=["meta"])

CurrentSettings = Annotated[Settings, Depends(get_settings)]


class Meta(BaseModel):
    """One key. See this module's docstring before adding a second."""

    pandan_url: str
    """Origin of the linked pandan deployment (team-default access, ADR 0011) — no longer the
    identity provider since ADR 0012's cutover (KAN-1740) retired that role.

    Verbatim from ``KAYA_PANDAN_URL``, not normalised: it is the operator's own string, and the
    authenticated shell (`App.svelte`, KAN-1157) only ever puts it in an ``href``."""


@router.get("/meta", summary="Public configuration a caller needs before pandan is reachable")
def read_meta(settings: CurrentSettings) -> Meta:
    """Where the linked pandan board lives.

    No ``get_principal`` dependency, deliberately (see the module docstring), and no database
    session either — so this route answers with pandan unreachable *and* with Postgres down. That
    also keeps ADR 0003's rule intact by construction: the route that tells you about pandan does
    not talk to pandan. Unauthenticated on purpose still — nothing about ADR 0012's cutover made
    `pandan_url` a secret, and gating it behind `get_principal` would just be one more thing to call
    before this route can answer.
    """
    return Meta(pandan_url=settings.pandan_url)
