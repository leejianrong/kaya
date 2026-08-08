"""The ASGI app.

KAN-531 was the skeleton: an app that boots and one health endpoint. KAN-536 mounts ``/api/v1``
(``app/api/``), which is where everything a caller can do now lives. Serving the built SPA from this
same origin arrives with KAN-538.

Two lines of composition and no behaviour, deliberately — the router and the error handlers are both
importable and both installable onto a bare ``FastAPI()``, so a test can stand up the real surface
without the real settings.
"""

from fastapi import FastAPI
from pydantic import BaseModel

from app import __version__
from app.api import install_error_handlers
from app.api import router as api_router

app = FastAPI(
    title="kaya",
    summary="Markdown notes, API-first and agent-drivable.",
    version=__version__,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

# Before the router, so a refusal raised while resolving a dependency is shaped too.
install_error_handlers(app)
app.include_router(api_router)


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
