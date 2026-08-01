"""The ASGI app.

KAN-531 is the skeleton: an app that boots and one health endpoint. ``/api/v1`` arrives with
KAN-535, and serving the built SPA from this same origin arrives with KAN-538.
"""

from fastapi import FastAPI
from pydantic import BaseModel

from app import __version__

app = FastAPI(
    title="kaya",
    summary="Markdown notes, API-first and agent-drivable.",
    version=__version__,
    docs_url="/docs",
    openapi_url="/openapi.json",
)


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
