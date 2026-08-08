"""Serving the built SPA from the API's own origin (KAN-538, ADR 0010).

One artifact serves both halves, so the SPA fetches ``/api/v1/notes`` with a relative URL in
production exactly as it does through Vite's proxy in development, and CORS never has to exist.

**The whole difficulty of this module is one line of it.** A single-page app needs *history
fallback*: a URL the server has never heard of — ``/notes/NOTE-12``, a link somebody pasted into
chat — must return ``index.html`` so the client-side router can take it from there. Written
carelessly, that fallback answers **every** unmatched path, and the API disappears inside it:

    GET /api/v1/notes/NOTE-9999   →   200 text/html      (a note that does not exist)

instead of KAN-536's `404`. Two shapes of the same mistake produce it, and both look reasonable in
review:

- ``StaticFiles(directory=…, html=True)`` mounted at ``/``, which turns its own misses into
  ``index.html`` and so swallows every ``/api`` path no route claimed;
- an exception handler on `404` that returns ``index.html``, which is worse — it swallows genuine
  refusals raised by routes that matched, so ADR 0008's byte-identical `404` for ``NOTE-9999`` and
  ``9999`` becomes two identical *HTML pages* with a `200` on them.

Neither is caught by the API suite, because that suite stands the app up without a build directory
and therefore without a fallback at all. ``tests/unit/test_spa_single_origin.py`` runs the same
requests against an app *with* the SPA mounted and requires the answers to be byte-identical.

The rule enforced here, in place of both: **a reserved path is never the SPA's**. Anything under
``RESERVED_PREFIXES`` gets the `404` the router would have produced on its own; everything else
gets a real file if one exists and ``index.html`` if not.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from starlette.responses import FileResponse, Response

from app.config import get_settings

INDEX = "index.html"

ASSET_DIR = "assets"
"""Vite's output directory for content-hashed bundles. Everything in it is immutable by
construction: a changed file gets a changed name."""

IMMUTABLE = "public, max-age=31536000, immutable"

RESERVED_PREFIXES: tuple[str, ...] = (
    "/api",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
)
"""Path namespaces the server owns. The SPA is never served for one, matched route or not.

This is a *namespace* list, not a route list, and that is the point — ``/api/v1/notes/NOTE-9999``
matches a route and must 404 from it, while ``/api/v1/nonesuch`` matches nothing and must still
404 as JSON rather than becoming a client-side route. Enumerating routes would only cover the
first case.

``tests/unit/test_spa_single_origin.py`` asserts that *every* route the real app registers falls
under one of these, so adding ``/metrics`` without a decision about ``/metrics/typo`` fails the
build rather than silently making it an SPA deep link.
"""


def is_reserved(path: str) -> bool:
    """Does this path belong to the server rather than to the client-side router?

    Prefix-with-a-boundary, not ``startswith``: ``/apiary`` is a perfectly good note path and must
    not be captured by ``/api``.
    """
    candidate = "/" + path.lstrip("/")
    return any(
        candidate == prefix or candidate.startswith(prefix + "/") for prefix in RESERVED_PREFIXES
    )


def spa_asset(root: Path, path: str) -> Path | None:
    """The real file this path names inside ``root``, or ``None`` if there isn't one.

    ``resolve()`` before the containment check, so ``../../etc/passwd`` and a symlink pointing out
    of the build are both answered with ``None`` — the fallback then serves ``index.html``, which
    is the correct answer for a path that names nothing servable anyway.
    """
    if not path:
        return None

    candidate = (root / path).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        return None
    return candidate


def _index_response(index: Path) -> FileResponse:
    # `no-cache` means "revalidate", not "never store". index.html names the hashed bundles, so a
    # cached copy outlives the deploy that deleted them and the app loads to a blank page with two
    # 404s in the console. The bundles themselves are safe to keep forever, below.
    return FileResponse(index, headers={"Cache-Control": "no-cache"})


def mount_spa(app: FastAPI, dist: Path | None = None) -> bool:
    """Serve the build at ``dist`` from ``app``, and report whether there was one.

    Call this **last**, after every router. Order is load-bearing: Starlette matches routes in
    registration order, so the catch-all registered here can only ever see a path that no real
    route claimed. Registered first, it would shadow the entire API.

    Returns ``False`` and installs nothing when no build is configured or the configured one is
    not there — a source checkout, and every test that has ever imported ``app.main``. That is
    what keeps this card from changing the behaviour of an app nobody asked to serve a SPA.
    """
    configured = dist if dist is not None else get_settings().spa_dist
    if configured is None:
        return False

    root = Path(configured).resolve()
    index = root / INDEX
    if not index.is_file():
        return False

    def serve_spa(spa_path: str) -> Response:
        if is_reserved(spa_path):
            # Bare, on purpose. `HTTPException(404)` carries Starlette's own "Not Found" detail,
            # which `app.api.errors` renders as `{"error": {"code": "not_found", …}}` — the exact
            # body an unmounted app produces for the same path. "Identical" here is asserted
            # against the other app, not eyeballed.
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

        asset = spa_asset(root, spa_path)
        if asset is None or asset == index:
            return _index_response(index)

        if asset.parent == root / ASSET_DIR:
            return FileResponse(asset, headers={"Cache-Control": IMMUTABLE})
        return FileResponse(asset)

    # `add_api_route` rather than `@app.get`, for the sake of one word: HEAD. Starlette's plain
    # `Route` adds HEAD alongside GET; FastAPI's `APIRoute` does not, so a decorated handler answers
    # `405` to `curl -I` and to any proxy or CDN that validates a cached asset with a HEAD. That is
    # tolerable for a JSON API — the rest of kaya's routes are GET-only too — and wrong for the half
    # of this origin that is a file server.
    app.add_api_route(
        "/{spa_path:path}",
        serve_spa,
        methods=["GET", "HEAD"],
        include_in_schema=False,
        name="spa",
    )

    return True
