#!/usr/bin/env python3
"""A stand-in for pandan's `GET /api/v1/me`, for `make test-e2e` (KAN-1070) only.

A real browser needs a real running backend to authenticate against — the in-process
`app.dependency_overrides` trick `backend/tests/integration/test_pandan_down.py`'s `FakeUpstream`
uses does not work here, because the browser talks to a real HTTP server process, not an in-process
`TestClient`. So this is that process: a real server the e2e stack's `app` container points
`KAYA_PANDAN_URL` at, in place of `https://simple-kanban-jian.fly.dev`.

The contract it implements is `backend/app/auth/upstream.py`'s, verified live against real pandan
and quoted verbatim in that module's docstring:

    GET /api/v1/me, Authorization: Bearer <pat>  ->  200 {"id": "<uuid4>", "email": "<str>"}
    no Authorization header                      ->  401 {"detail": "authentication required"}
    garbage bearer                                ->  401 {"detail": "authentication required"}

Deliberately stdlib-only (`http.server`), not FastAPI/uvicorn: this is test-only infrastructure for
the e2e stack, not shipped backend code, and pulling in a second HTTP framework here would blur that
line for no benefit — the whole handler is under sixty lines. `docker-compose.e2e.yml` runs it by
bind-mounting this file into the same digest-pinned `python:3.12-slim` image the real Dockerfile
already uses, so `scripts/check-image-pins.sh` has nothing new to pin.

The token this process accepts is read from `KAYA_E2E_FAKE_PANDAN_TOKEN` — never hard-coded here and
in the Playwright side both, because a default that silently drifts between the two processes is the
exact failure mode a "shared constant" is supposed to prevent. `scripts/test-e2e.sh` sets it once and
exports it to both.
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ME_PATH = "/api/v1/me"
HEALTH_PATH = "/health"

FAKE_PRINCIPAL_ID = "e2e0e2e0-e2e0-4e2e-8e2e-e2e0e2e0e2e0"
FAKE_PRINCIPAL_EMAIL = "e2e@kaya.test"


class Handler(BaseHTTPRequestHandler):
    # Nothing this process logs is a credential — the token is compared, never echoed — but the
    # default access log is still noise nobody watching `docker compose logs` needs.
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib's own name
        pass

    def _write(self, status: int, body: dict[str, object]) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's own naming
        if self.path == HEALTH_PATH:
            self._write(200, {"status": "ok"})
            return

        if self.path != ME_PATH:
            self._write(404, {"detail": "not found"})
            return

        expected = f"Bearer {fake_token()}"
        if self.headers.get("Authorization") != expected:
            # Byte-identical to a garbage bearer and to a missing header, exactly as real pandan's
            # docstring records — see `backend/app/auth/upstream.py`.
            self._write(401, {"detail": "authentication required"})
            return

        self._write(200, {"id": FAKE_PRINCIPAL_ID, "email": FAKE_PRINCIPAL_EMAIL})


def fake_token() -> str:
    token = os.environ.get("KAYA_E2E_FAKE_PANDAN_TOKEN")
    if not token:
        print(
            "fake_pandan: KAYA_E2E_FAKE_PANDAN_TOKEN is not set — refusing to start with no "
            "credential to check against.",
            file=sys.stderr,
        )
        sys.exit(1)
    return token


if __name__ == "__main__":
    fake_token()  # fail fast, before binding a socket, if the token is missing
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"fake_pandan: listening on :{port}", flush=True)
    server.serve_forever()
