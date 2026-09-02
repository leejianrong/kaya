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
from starlette.middleware.gzip import GZipMiddleware

from app import __version__
from app.api import (
    attachments_router,
    embeds_router,
    graph_router,
    install_error_handlers,
    links_router,
    meta_router,
    note_claim_router,
)
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

# KAN-963. Every bundle figure this project has ever quoted (ADR 0001 §2's obligation, and every
# table in frontend/README.md) is a `gzip -9` figure — the honest number *a compressing edge would
# deliver*. Per ADR 0010's amendment, `make up` is the only origin that exists, and it had no
# compressing edge in front of it: `mount_spa`'s `FileResponse`s went out raw, so a real request
# against the one real deployment shape paid roughly 3x every quoted table. Middleware, not an edge,
# because there is no edge (ADR 0010, KAN-722) and this is one line closing a real gap rather than
# infrastructure built for a deploy shape that does not exist.
#
# Registered before `install_observability`, and that ordering has **no observable effect** on the
# access log — checked rather than assumed, after an earlier draft of this comment claimed
# otherwise and was wrong on two counts. First, `app/observability/middleware.py`'s `ACCESS_FIELDS`
# is `("method", "path", "status", "duration_ms", "client")`: there is no byte-count field for a
# compression order to make honest or dishonest. Second, `Starlette.add_middleware` inserts at index
# 0 of `user_middleware`, so the middleware added *last* ends up outermost — meaning
# `install_observability`'s `RequestLogMiddleware`, added after this line, actually wraps this one,
# not the other way round. That still changes nothing that matters: verified with a throwaway ASGI
# trace (both directions), `duration_ms` includes this middleware's work either way, and an
# exception raised while sending a response is caught by `RequestLogMiddleware`'s `try`/`except` and
# still produces an access line either way. Both are consequences of ASGI middleware being nested,
# synchronous coroutine calls rather than concurrent tasks — a `send()` callback invoked deep in the
# chain unwinds back through every enclosing frame regardless of which middleware nominally wraps
# which, so there is no ordering here to get right. It sits before `install_observability` simply
# because the SPA/response-shaping concerns this file composes are grouped together, ahead of where
# observability is installed — a readability choice, not a behavioural one.
#
# Starlette's `GZipMiddleware` explicitly does not touch an `http.response.pathsend` message (see
# its source: "Don't apply GZip to pathsend responses"), which is how a server offering that ASGI
# extension could silently exempt every `FileResponse` — every static asset `app/spa.py` serves —
# from this middleware while every JSON response still compressed. Checked rather than assumed:
# uvicorn 0.52 (this project's ASGI server) implements no such extension, so it never appears in
# `scope["extensions"]` and `FileResponse` always falls through to plain chunked
# `http.response.body` messages, which this middleware compresses like anything else — confirmed by
# re-measuring against a real built SPA (see the PR). Re-check this comment if the ASGI server ever
# changes.
#
# `minimum_size` is Starlette's own default (500 bytes) — small enough that a real note body clears
# it and a JSON `{"status":"ok"}` from `/health` does not, so the liveness probe pays no gzip
# overhead for a saving that could never be positive on its own.
app.add_middleware(GZipMiddleware)

# So that anything the rest of this module's import does — and everything uvicorn logs
# while starting up — is already going to one stdout handler in one shape. It also puts the
# request-log middleware *outside* the exception handlers, which is what lets the access line
# record the status a refusal was finally answered with rather than the exception it began as.
# See `app/observability/middleware.py` on the ordering.
install_observability(app)

# Before the router, so a refusal raised while resolving a dependency is shaped too.
install_error_handlers(app)
app.include_router(api_router)

# KAN-566's `/notes/{ref}/links` and `/notes/{ref}/backlinks`. A second router under the same
# `/api/v1` prefix rather than two more routes on `api_router`, for the reason `app/api/links.py`
# argues: they are the only routes that reach an upstream as well as the database. Registration
# order is immaterial between the two — `/notes/{ref}` cannot match `/notes/NOTE-3/links`, because a
# path parameter never spans a `/` — so this is composition, not precedence.
app.include_router(links_router)

# KAN-1049's `/embeds/board`. A third router under `/api/v1` for the reason `app/api/embeds.py`
# argues: it is authenticated but, unlike every route on `api_router` and unlike `links_router`,
# it holds no database session at all.
app.include_router(embeds_router)

# KAN-1050's `/graph`. A fourth router under `/api/v1` for the reason `app/api/graph.py` argues: it
# answers a different question (a graph, not a note), so it reads as itself in its own module.
# Registration order is immaterial for the same reason as above — `/graph` matches nothing else
# under `/notes`.
app.include_router(graph_router)

# R14's `/notes/{ref}/attachments` (KAN-1067/1068). A fifth router under `/api/v1` for the same
# reason `links_router` is its own: `/notes/{ref}` cannot match `/notes/NOTE-3/attachments`, so
# registration order is immaterial, and this reads as itself in its own module.
app.include_router(attachments_router)

# R12/KAN-1061's `PUT /notes/{ref}`. A sixth router under `/api/v1` for the reason
# `app/api/note_claim.py` argues: it is the one route allowed to hand a caller-chosen ref to a new
# note, which `NoteCreate` (the schema every other creation path shares) is deliberately built to
# refuse, so it earns its own module rather than a conditional inside `notes.py`. Registration
# order is immaterial against `api_router`'s own `GET`/`PATCH`/`DELETE /notes/{ref}`: they share a
# path but not a method, and Starlette dispatches on both.
app.include_router(note_claim_router)

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
