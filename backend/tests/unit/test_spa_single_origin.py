"""One origin, two halves, and the fallback that must not eat the API (KAN-538).

This file exists because of a failure mode that no other test in the repository can see. Every
existing API test stands the app up **without** a build directory, so no fallback is installed and
the whole suite stays green against a fallback that swallows ``/api`` whole. The card's own words:
``/api/v1/notes/NOTE-9999`` would answer `200` with ``index.html`` instead of the `404` KAN-536
spent a card making byte-identical across both spellings of a ref.

So the technique here is a **differential** one. Two apps are built from the same routers — one
with the SPA mounted, one without — and the reserved paths are required to produce byte-identical
answers from both. That assertion cannot be satisfied by a fallback that answers a reserved path,
whatever shape the mistake takes: a `200` of HTML is not the `404` of JSON the bare app produced,
and neither is a differently-worded `404`.

No infrastructure, per SLICES §V1's fast layer: the session is a stand-in that finds no note (so
every lookup is a genuine `404` produced by ``authorize_note``), and the principal is Alice.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fakes import ALICE
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import install_error_handlers
from app.api import router as api_router
from app.auth import get_principal
from app.config import get_settings
from app.db import get_session
from app.main import health
from app.spa import RESERVED_PREFIXES, is_reserved, mount_spa, spa_asset

INDEX_HTML = "<!doctype html><html><body><div id=\"app\"></div></body></html>"
BUNDLE_JS = "console.log('kaya')\n"

# Paths the server owns. Each one is answered by the API app today, and each is a way the fallback
# could go wrong: a route that matched and refused (`NOTE-9999`), a namespace with no route behind
# it (`/api/v1/nonesuch`), a route on a sibling namespace (`/health`), and the two doc surfaces.
RESERVED_PATHS = [
    "/api/v1/notes/NOTE-9999",
    "/api/v1/notes/9999",
    "/api/v1/nonesuch",
    "/api/v1",
    "/health",
    "/openapi.json",
    "/docs",
]


class _FindsNothing:
    """A session whose every lookup misses, which is all a `404` needs.

    ``resolve_note`` calls ``session.scalars(statement).one_or_none()`` and hands the result
    straight to ``authorize_note``. Returning ``None`` is therefore the whole of "no such note",
    with no Postgres and no model instances involved.
    """

    def scalars(self, statement: Any) -> "_FindsNothing":
        return self

    def one_or_none(self) -> None:
        return None


def _api_app() -> FastAPI:
    """``app.main``'s composition, with the two edges of the app faked.

    The real handlers, the real router and ``app.main``'s own ``health`` function — not a stand-in
    for any of them, so the differential below compares kaya's actual answers rather than a
    simplified model of them. What is faked is only what would need infrastructure: who is calling,
    and what the database holds.
    """
    app = FastAPI(docs_url="/docs", openapi_url="/openapi.json")
    install_error_handlers(app)
    app.include_router(api_router)
    app.add_api_route("/health", health, methods=["GET"])
    app.dependency_overrides[get_principal] = lambda: ALICE
    app.dependency_overrides[get_session] = lambda: _FindsNothing()
    return app


def served_paths(router: Any) -> list[str]:
    """Every path the app can answer, including the ones behind an included router.

    FastAPI 0.141 puts a single opaque ``_IncludedRouter`` into ``app.routes`` rather than
    splicing the included routes in, so a flat read of ``app.routes`` sees ``/health`` and misses
    the whole of ``/api/v1``. It would have reported "all routes covered" while covering nothing —
    the failure mode this guard exists to prevent, in the guard itself.
    """
    paths: list[str] = []
    for route in getattr(router, "routes", []):
        nested = getattr(route, "original_router", None)
        if nested is not None:
            paths.extend(served_paths(nested))
        path = getattr(route, "path", None)
        if path is not None and getattr(route, "name", None) != "spa":
            paths.append(path)
    return paths


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    """A build directory shaped the way ``vite build`` shapes one."""
    build = tmp_path / "dist"
    (build / "assets").mkdir(parents=True)
    (build / "index.html").write_text(INDEX_HTML)
    (build / "assets" / "index-abc123.js").write_text(BUNDLE_JS)
    (build / "favicon.ico").write_bytes(b"\x00\x00\x01\x00")
    # A file the SPA must never be able to reach out of the build and read.
    (tmp_path / "secrets.txt").write_text("not servable")
    return build


@pytest.fixture
def served(dist: Path) -> Iterator[TestClient]:
    """The app as the container image runs it: API, then SPA."""
    app = _api_app()
    assert mount_spa(app, dist) is True
    with TestClient(app) as client:
        yield client


@pytest.fixture
def bare() -> Iterator[TestClient]:
    """The same app without a build — what every other test in the suite sees."""
    with TestClient(_api_app()) as client:
        yield client


# --- the guard: the fallback cannot answer for the server -----------------------------------------


@pytest.mark.parametrize("path", RESERVED_PATHS)
def test_a_reserved_path_answers_identically_with_and_without_the_spa(
    served: TestClient, bare: TestClient, path: str
) -> None:
    """The whole card, as one assertion repeated over the paths that matter.

    Mounting a SPA is not allowed to change a single byte of what the API says. Compare the status,
    the content type and the body — status alone would pass against a `404` page of HTML, and body
    alone would pass against a `200`.
    """
    with_spa = served.get(path)
    without_spa = bare.get(path)

    assert with_spa.status_code == without_spa.status_code, path
    assert with_spa.headers["content-type"] == without_spa.headers["content-type"], path
    assert with_spa.content == without_spa.content, path


def test_a_missing_note_is_a_json_404_not_the_index_page(served: TestClient) -> None:
    """The card's named failure, spelled out rather than left to the differential above.

    If this returns `200` and HTML, the fallback is mounted wrong and KAN-536's contract is gone.
    """
    response = served.get("/api/v1/notes/NOTE-9999")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "note_not_found"


def test_both_spellings_of_a_missing_ref_stay_byte_identical(served: TestClient) -> None:
    """ADR 0008 §identity, re-asserted downstream of the SPA.

    A fallback that intercepts only *unrouted* paths leaves this passing; one that intercepts `404`
    responses breaks it into two identical HTML pages, which would still be "identical" to a test
    that compared the two spellings to each other and nothing else. Hence the status assertion.
    """
    prefixed = served.get("/api/v1/notes/NOTE-9999")
    bare_id = served.get("/api/v1/notes/9999")

    assert prefixed.status_code == 404
    assert prefixed.content == bare_id.content


def test_health_stays_reachable_behind_the_spa(served: TestClient) -> None:
    """The liveness probe in ``deploy/k8s/`` hits this path on a pod that *does* serve the SPA."""
    response = served.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_every_route_the_app_registers_falls_under_a_reserved_prefix() -> None:
    """The forward guard: a new server route cannot be added without deciding about the SPA.

    Reads the real ``app.main`` app, not a fixture. Add ``/metrics`` tomorrow and this fails,
    which is the moment to decide whether ``/metrics/typo`` is a JSON `404` or a client-side
    route — rather than discovering months later that it became the latter.
    """
    from app.main import app as real_app

    paths = served_paths(real_app)
    assert "/api/v1/notes/{ref}" in paths, "the walker stopped seeing the API; fix it before this"

    unreserved = sorted({path for path in paths if not is_reserved(path)})

    assert unreserved == [], (
        f"{unreserved} are served by kaya but not covered by {RESERVED_PREFIXES}; "
        "the SPA fallback would answer for anything unmatched inside them"
    )


# --- the SPA half, which must still actually work -------------------------------------------------


def test_the_root_serves_the_built_index(served: TestClient) -> None:
    response = served.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.text == INDEX_HTML


def test_an_unknown_path_is_a_client_side_route(served: TestClient) -> None:
    """History fallback. A pasted deep link must load the app, not a `404`."""
    response = served.get("/notes/NOTE-12")

    assert response.status_code == 200
    assert response.text == INDEX_HTML


def test_a_path_that_merely_starts_like_a_reserved_one_is_the_spas(served: TestClient) -> None:
    """``/apiary`` is a fine note path. ``startswith('/api')`` would steal it."""
    assert served.get("/apiary/notes").text == INDEX_HTML


def test_a_hashed_bundle_is_served_as_itself_and_cached_forever(served: TestClient) -> None:
    response = served.get("/assets/index-abc123.js")

    assert response.status_code == 200
    assert response.text == BUNDLE_JS
    assert "immutable" in response.headers["cache-control"]


def test_a_bundle_answers_head_as_well_as_get(served: TestClient) -> None:
    """A file server that 405s on HEAD breaks `curl -I` and any proxy that revalidates with one.

    FastAPI's ``@app.get`` does not add HEAD the way Starlette's plain ``Route`` does, so this is
    the assertion that keeps ``mount_spa`` from being simplified back into a decorator.
    """
    response = served.head("/assets/index-abc123.js")

    assert response.status_code == 200
    assert "immutable" in response.headers["cache-control"]


def test_the_index_is_revalidated_rather_than_cached(served: TestClient) -> None:
    """It names the hashed bundles. A cached copy outlives the deploy that deleted them."""
    assert served.get("/").headers["cache-control"] == "no-cache"


def test_a_root_level_file_is_served_without_the_immutable_header(served: TestClient) -> None:
    """``favicon.ico`` carries no content hash, so it is not safe to freeze for a year."""
    response = served.get("/favicon.ico")

    assert response.status_code == 200
    assert "immutable" not in response.headers.get("cache-control", "")


# --- containment and absence ----------------------------------------------------------------------


@pytest.mark.parametrize("escape", ["../secrets.txt", "assets/../../secrets.txt", "/etc/passwd"])
def test_the_fallback_cannot_read_outside_the_build(dist: Path, escape: str) -> None:
    """Asserted on the function rather than through the client, because the HTTP layer normalises
    some of these away — and the containment must hold for the ones it does not."""
    assert spa_asset(dist, escape) is None


def test_nothing_is_mounted_when_there_is_no_build(tmp_path: Path) -> None:
    """A source checkout, and every other test file in this suite.

    ``mount_spa`` reporting ``False`` is what keeps this card from changing the app that ``pytest
    tests/unit`` has been exercising all along.
    """
    app = _api_app()

    assert mount_spa(app, tmp_path / "never-built") is False
    with TestClient(app) as client:
        assert client.get("/notes/NOTE-12").status_code == 404


def test_a_build_directory_without_an_index_is_not_a_build(tmp_path: Path) -> None:
    """Half a build is not a build. Serving from it would 500 on every deep link."""
    (tmp_path / "assets").mkdir()

    assert mount_spa(_api_app(), tmp_path) is False


def test_an_unconfigured_spa_dist_guesses_at_nothing() -> None:
    """``KAYA_SPA_DIST`` unset means no SPA, and no directory is looked for.

    The alternative — a default location, or a list of candidates — is how an API process ends up
    serving whatever build happened to be lying around, dated by nobody. The container image sets
    the variable; nothing else does.
    """
    assert get_settings().spa_dist is None
    assert mount_spa(_api_app()) is False
