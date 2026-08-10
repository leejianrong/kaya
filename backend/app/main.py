"""The ASGI app.

KAN-531 was the skeleton: an app that boots and one health endpoint. KAN-536 mounts ``/api/v1``
(``app/api/``), which is where everything a caller can do now lives. KAN-538 puts the built SPA on
this same origin, so one artifact serves both halves (ADR 0010).

A handful of lines of composition and no behaviour, deliberately — the routers, the error handlers,
the observability layer and the SPA are all installable onto a bare ``FastAPI()``, so a test can
stand up the real surface without the real settings.
"""

from fastapi import FastAPI
from pydantic import BaseModel

from app import __version__
from app.api import install_error_handlers, meta_router
from app.api import router as api_router
from app.observability import install_observability
from app.spa import mount_spa

app = FastAPI(
    title="kaya",
    summary="Markdown notes, API-first and agent-drivable.",
    version=__version__,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

# First, so that anything the rest of this module's import does — and everything uvicorn logs
# while starting up — is already going to one stdout handler in one shape. It also puts the
# request-log middleware *outside* the exception handlers, which is what lets the access line
# record the status a refusal was finally answered with rather than the exception it began as.
# See `app/observability/middleware.py` on the ordering.
install_observability(app)

# Before the router, so a refusal raised while resolving a dependency is shaped too.
install_error_handlers(app)
app.include_router(api_router)

# KAN-555. Separate from `api_router` because it is the one route under `/api/v1` with no credential
# in front of it, and that difference should be visible where the surface is composed rather than
# only inside the module — `app/api/meta.py` has the argument for why it is safe.
app.include_router(meta_router)


class Health(BaseModel):
    status: str
    service: str
    version: str


@app.get("/health", tags=["meta"], summary="Liveness")
def health() -> Health:
    """Liveness only.

    Deliberately touches no database and makes no upstream call. A health check that depends on
    Postgres or on pandan reports *their* availability, and under ADR 0003 nothing in kaya may
    hard-depend on pandan being reachable. Readiness, if it is ever needed, is a separate route.
    """
    return Health(status="ok", service="kaya", version=__version__)


# LAST, and the position is the guarantee rather than a tidiness preference. Starlette matches in
# registration order, so a catch-all installed here sees only paths that `/api/v1`, `/health`,
# `/docs` and `/openapi.json` all declined — and `app.spa` refuses those namespaces a second time,
# for the paths inside them that match no route at all. Installs nothing when there is no build,
# which is every source checkout and every existing test. See `app/spa.py`.
mount_spa(app)
