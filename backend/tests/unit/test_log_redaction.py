"""**[mutate]** A caller's bearer must never reach a log line. KAN-700.

ADR 0002 buys one property with everything it costs: kaya holds no replayable credential. It
forwards the caller's PAT and keeps only ``sha256(raw)``, so a heap dump, a debugger session or an
errant log line yields nothing an attacker can use. ``TokenRejected``'s docstring says outright
that it "carries no token, not even a fragment: this reaches an exception handler and a log line."

Adding request logging is the most likely way that gets broken, so it arrives with this file.

**Why the assertion is over fragments and not over the token.** ``assert token not in output`` is
the obvious test and it is nearly useless: it passes for a log line carrying the first forty
characters of a forty-three character token, which is not meaningfully less leaked. Anything a
redactor truncated, an f-string cut short, or a formatter elided would sail through it. So
``leaked_fragments`` slides a window across the token and requires that *no* contiguous run of
``FRAGMENT`` characters appears anywhere in the output.
``test_the_fragment_assertion_catches_a_partial_leak`` proves that helper can fail, because an
absence-assertion that cannot fail is the most comfortable kind of bug.

**The token here is a fake with a real shape.** ``pandan_pat_`` plus a 43-character URL-safe tail
is what pandan mints, and the shape matters: a scrubber tested against ``"secret"`` proves nothing
about a scrubber that keys off syntax. It is a constructed string that has never been a
credential, and ``.gitleaks.toml``'s allowlist covers exactly this ``FAKE…`` placeholder form so
the secret gate does not fire on the test that guards against secrets.
"""

import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import install_error_handlers
from app.observability import (
    ACCESS_FIELDS,
    REQUEST_ID_HEADER,
    configure_logging,
    get_logger,
    install_observability,
    scrub,
    scrub_text,
)

TOKEN = "pandan_pat_FAKE0000aaaaBBBBccccDDDDeeeeFFFFgggg111"
"""Shaped like the real thing, and never was one. See the module docstring."""

FRAGMENT = 8
"""The window width. Short enough that a badly truncated token is still caught, long enough that
an eight-character run does not collide with ordinary log text by accident."""


def leaked_fragments(output: str, secret: str = TOKEN) -> list[str]:
    """Every contiguous ``FRAGMENT``-character run of ``secret`` that appears in ``output``.

    The tail is excluded from the window walk deliberately: the prefix ``pandan_pat_`` is public
    knowledge (it is in ``.gitleaks.toml`` and in three ADRs), so a match on it alone would be a
    false positive. Every window that overlaps the random tail is checked.
    """
    windows = {
        secret[i : i + FRAGMENT]
        for i in range(len(secret) - FRAGMENT + 1)
        # Skip windows lying wholly inside the well-known prefix.
        if i + FRAGMENT > len("pandan_pat_")
    }
    return sorted(window for window in windows if window in output)


def build_app() -> FastAPI:
    """The real surface, on a bare app, with one route that leaks on purpose.

    ``/boom`` raises an exception whose *message* contains the bearer — the accident this has to
    survive. Nobody writes that deliberately; somebody writes ``raise ValueError(f"rejected
    {credentials}")`` while debugging and it reaches production.
    """
    app = FastAPI()
    install_observability(app)
    install_error_handlers(app)

    @app.get("/ok")
    def ok() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/boom")
    def boom() -> dict[str, str]:
        raise RuntimeError(f"could not resolve Authorization: Bearer {TOKEN}")

    return app


def captured_lines(capsys: pytest.CaptureFixture[str]) -> list[dict]:
    """The JSON log lines written to stdout so far, parsed.

    Every line must parse. A handler that occasionally writes something that is not JSON is a
    handler whose output nothing downstream can filter, and it would also mean the scrubber never
    saw that line.
    """
    raw = capsys.readouterr().out
    lines = [line for line in raw.splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def access_lines(lines: list[dict]) -> list[dict]:
    """Only kaya's own access lines.

    Everything on the root logger comes out of this handler, third-party records included — which
    is the design (``app/observability/logs.py``) and is visible right here: ``TestClient`` drives
    the app through httpx, so httpx's own ``INFO`` line lands in the same stream. Useful in
    production, where the only outbound call kaya makes is pandan's ``GET /api/v1/me`` and that
    line is what distinguishes a cold upstream from a real outage. Noise in a test that is
    asserting about the access line specifically.
    """
    return [line for line in lines if line["logger"] == "kaya.access"]


# --------------------------------------------------------------------- the guard itself


def test_a_request_log_line_never_carries_the_bearer(capsys: pytest.CaptureFixture[str]) -> None:
    """The whole point, end to end: a real request with a real-shaped credential on it."""
    configure_logging("INFO")
    client = TestClient(build_app())

    response = client.get("/ok", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200

    output = capsys.readouterr().out
    assert output.strip(), "nothing was logged at all — the guard would pass vacuously"
    assert leaked_fragments(output) == [], (
        "ADR 0002: a caller's bearer reached stdout. Kaya forwards the token and stores only "
        f"sha256(raw) precisely so a log line cannot yield a live credential. Leaked: "
        f"{leaked_fragments(output)}"
    )


def test_an_unhandled_exception_carrying_the_bearer_is_scrubbed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The traceback is the other half of the surface, and it prints the exception's message.

    ``/boom`` puts the token in that message. Both the ``error.message`` field and the rendered
    traceback go through the same scrubber, so neither leaks — and the line still has to be
    *useful*, which is why the type and the request id are asserted too.
    """
    configure_logging("INFO")
    client = TestClient(build_app(), raise_server_exceptions=False)

    response = client.get("/boom", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 500

    raw = capsys.readouterr().out
    assert leaked_fragments(raw) == [], f"the traceback leaked the bearer: {leaked_fragments(raw)}"

    errors = [json.loads(line) for line in raw.splitlines() if '"error"' in line]
    assert errors, "an unhandled exception produced no log line with an error object on it"
    assert errors[0]["error"]["type"] == "RuntimeError"
    assert "Traceback" in errors[0]["error"]["traceback"]
    assert errors[0]["request_id"], "an error with no request id cannot be correlated"


def test_the_formatter_scrubs_a_header_mapping_someone_logged(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The defence-in-depth case: a call site that logs headers wholesale.

    The middleware never does this — ``ACCESS_FIELDS`` has no header in it — but ``app/auth/``,
    httpx or a future route might, and the redaction rule is at serialization so that it does not
    matter which.
    """
    configure_logging("INFO")

    get_logger("test").info(
        "calling upstream",
        extra={"headers": {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}},
    )

    raw = capsys.readouterr().out
    assert leaked_fragments(raw) == []
    line = json.loads(raw)
    assert line["headers"]["Authorization"] == "[redacted]"
    # Redaction is surgical: the harmless header beside it is untouched, so the log stays useful.
    assert line["headers"]["Accept"] == "application/json"


def test_the_formatter_scrubs_a_bearer_passed_as_a_percent_arg(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``logger.info("resolved %s", bearer)`` — the credential is in ``record.args``, not ``msg``.

    A formatter that scrubbed ``record.msg`` would print ``resolved %s`` clean and interpolate the
    token afterwards. ``JsonFormatter`` calls ``getMessage()`` first for exactly this reason.
    """
    configure_logging("INFO")

    get_logger("test").warning("resolved bearer %s", TOKEN)

    raw = capsys.readouterr().out
    assert leaked_fragments(raw) == []
    assert "[redacted]" in json.loads(raw)["msg"]


def test_the_formatter_scrubs_a_repr_that_hides_headers_inside_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An object logged whole, with its headers inside its ``repr``. httpx and Starlette do this."""
    configure_logging("INFO")

    class Chatty:
        def __repr__(self) -> str:
            return f"<Request headers=Headers({{'authorization': 'Bearer {TOKEN}'}})>"

    get_logger("test").info("sending", extra={"request": Chatty()})

    raw = capsys.readouterr().out
    assert leaked_fragments(raw) == []
    assert "[redacted]" in json.loads(raw)["request"]


def test_the_fragment_assertion_catches_a_partial_leak() -> None:
    """Prove the helper can fail, on every partial shape, before trusting it above.

    An emptiness assertion passes for two reasons and only one of them is good. This is the other
    one, checked directly: a prefix, a suffix, a middle slice and a single window all register.
    """
    assert leaked_fragments(f"msg={TOKEN}") != []
    assert leaked_fragments(f"msg={TOKEN[:24]}") != [], "a truncated prefix went unnoticed"
    assert leaked_fragments(f"msg={TOKEN[-20:]}") != [], "a bare suffix went unnoticed"
    assert leaked_fragments(f"a{TOKEN[15:31]}b") != [], "a middle fragment went unnoticed"
    assert leaked_fragments(TOKEN[20 : 20 + FRAGMENT]) != [], "one exact window went unnoticed"

    # And it stays quiet on the things a clean log line legitimately contains: the public prefix,
    # the redaction marker, and a sha256 digest of the token (which is what the cache stores).
    assert leaked_fragments("token pandan_pat_[redacted] rejected") == []
    assert leaked_fragments("GET /api/v1/notes 200") == []


# --------------------------------------------------------------- the structural half


def test_the_access_line_carries_only_the_allowlisted_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``ACCESS_FIELDS`` is the contract, and no header or query string is in it.

    The scrubber is a backstop that recognises credential-shaped text; this is the guarantee that
    keeps it idle. If a future change adds a field, this fails and the field has to be argued for
    — including whether it can carry something a caller supplied.
    """
    configure_logging("INFO")
    client = TestClient(build_app())

    client.get("/ok?token=should-not-be-logged", headers={"Authorization": f"Bearer {TOKEN}"})

    line = access_lines(captured_lines(capsys))[-1]
    payload_only = set(line) - {"ts", "level", "logger", "msg", "request_id"}

    assert payload_only == set(ACCESS_FIELDS)
    assert "should-not-be-logged" not in json.dumps(line), (
        "the query string reached the log. Kaya takes its credential in a header, but a query "
        "string is where one arrives by accident — see app/observability/middleware.py."
    )


def test_the_access_line_says_what_happened(capsys: pytest.CaptureFixture[str]) -> None:
    """The other failure mode: perfectly redacted output that tells an operator nothing."""
    configure_logging("INFO")
    client = TestClient(build_app())

    client.get("/ok")

    line = access_lines(captured_lines(capsys))[-1]
    assert line["method"] == "GET"
    assert line["path"] == "/ok"
    assert line["status"] == 200
    assert isinstance(line["duration_ms"], float)
    assert line["level"] == "info"
    assert line["ts"].endswith("Z")


def test_scrub_leaves_non_credentials_alone() -> None:
    """Over-redaction is a real cost: a log that redacts everything is a log with nothing in it."""
    payload = {"path": "/api/v1/notes/NOTE-12", "status": 200, "duration_ms": 1.25, "ok": True}
    assert scrub(payload) == payload

    assert scrub_text("resolved NOTE-12 for user 41ad") == "resolved NOTE-12 for user 41ad"


def test_scrub_flattens_anything_json_cannot_encode() -> None:
    """``json.dumps``' ``default=`` must be unreachable, so ``scrub`` owns every leaf.

    If a foreign object reached ``json.dumps``, the natural fix is ``default=str`` — which prints a
    ``repr`` the scrubber never saw. The formatter can refuse instead only because of this.
    """
    encoded = json.dumps(scrub({"blob": b"bytes", "set": {1}, "deep": {"a": {"b": {"c": 1}}}}))
    assert "bytes" in encoded
    assert json.loads(encoded)["set"] == [1]


def test_scrub_does_not_walk_forever() -> None:
    """A self-referential structure truncates instead of hanging the request that logged it."""
    loop: dict[str, object] = {}
    loop["self"] = loop

    assert "[truncated]" in json.dumps(scrub(loop))


# --------------------------------------------------------------------- request ids


def test_the_request_id_is_echoed_and_shared_by_every_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """One id on the response header and on the log line, so a report can be traced to a line."""
    configure_logging("INFO")
    client = TestClient(build_app())

    response = client.get("/ok")

    logged = access_lines(captured_lines(capsys))[-1]

    assert response.headers[REQUEST_ID_HEADER] == logged["request_id"]


def test_an_inbound_request_id_is_honoured_and_a_silly_one_is_not(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Correlation across a proxy is the point. Accepting arbitrary bytes into a log line is not."""
    configure_logging("INFO")
    client = TestClient(build_app())

    client.get("/ok", headers={REQUEST_ID_HEADER: "trace-abc.123"})
    assert access_lines(captured_lines(capsys))[-1]["request_id"] == "trace-abc.123"

    client.get("/ok", headers={REQUEST_ID_HEADER: "x" * 400})
    replaced = access_lines(captured_lines(capsys))[-1]["request_id"]
    assert replaced != "x" * 400
    assert len(replaced) == 32


# --------------------------------------------------------------------- what must not regress


def test_health_is_logged_at_debug_so_probes_do_not_drown_the_log(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The kubelet hits `/health` forever. It stays visible at DEBUG and silent at INFO.

    `/health` itself is unchanged: it still touches neither Postgres nor pandan — see
    ``tests/unit/test_health.py``, which asserts that against a database that cannot exist.
    """
    from app.main import app as real_app

    configure_logging("INFO")
    client = TestClient(real_app)

    assert client.get("/health").status_code == 200
    assert access_lines(captured_lines(capsys)) == [], "the liveness probe was logged at INFO"

    configure_logging("DEBUG")
    assert client.get("/health").status_code == 200
    lines = access_lines(captured_lines(capsys))
    assert [line["path"] for line in lines] == ["/health"]

    configure_logging("INFO")


def test_configure_logging_is_idempotent(capsys: pytest.CaptureFixture[str]) -> None:
    """Called from ``app.main`` at import and again by every test above.

    A ``configure`` that appended handlers would double each line, and the tests would keep
    passing because they read the last one.
    """
    configure_logging("INFO")
    configure_logging("INFO")
    configure_logging("INFO")

    get_logger("test").info("once")

    assert len(captured_lines(capsys)) == 1


def test_uvicorns_access_logger_does_not_duplicate_the_line() -> None:
    """Two loggers describing the same request in two shapes is the state this replaced."""
    configure_logging("INFO")

    access = logging.getLogger("uvicorn.access")
    assert access.handlers == []
    assert access.propagate is True
    assert not access.isEnabledFor(logging.INFO)
    # Still a logger, not a hole: something genuinely wrong still arrives, as JSON.
    assert access.isEnabledFor(logging.WARNING)


def test_the_fast_path_cannot_skip_anything_the_patterns_match() -> None:
    """``TRIGGERS`` is an optimisation over the scrubber, and a wrong one would disable it silently.

    ``scrub_text`` returns early when a string contains none of ``TRIGGERS``. If that set ever
    misses a shape one of the three patterns *would* have matched, the scrubber stops scrubbing
    while continuing to look installed — the worst failure available to this module. So the early
    return is checked against the patterns run unconditionally, over a corpus that includes every
    sensitive header name, the bearer scheme and all three PAT prefixes.
    """
    from app.observability import redaction

    corpus = [
        f"Bearer {TOKEN}",
        f"bearer {TOKEN}",
        f"BEARER {TOKEN}",
        TOKEN,
        TOKEN.replace("pandan_pat_", "kanban_pat_"),
        TOKEN.replace("pandan_pat_", "kaya_pat_"),
        "GET /api/v1/notes 200",
        "note NOTE-12 updated",
        "",
    ]
    corpus += [f"{header}: {TOKEN}" for header in redaction.SENSITIVE_HEADERS]
    corpus += [f"{header.title()}={TOKEN}" for header in redaction.SENSITIVE_HEADERS]
    corpus += [
        f"Headers({{'{header}': 'Bearer {TOKEN}'}})"
        for header in redaction.SENSITIVE_HEADERS
    ]

    def unconditional(value: str) -> str:
        """``scrub_text`` with the early return removed — the slow path, in full."""
        value = redaction._HEADER_ASSIGNMENT.sub(lambda m: m.group(1) + redaction.REDACTED, value)
        value = redaction._BEARER_SCHEME.sub("Bearer " + redaction.REDACTED, value)
        return redaction._SUITE_PAT.sub(redaction.REDACTED, value)

    for item in corpus:
        assert scrub_text(item) == unconditional(item), f"the fast path skipped: {item!r}"

    # And every header name is reachable through a trigger by construction, not by luck.
    for header in redaction.SENSITIVE_HEADERS:
        assert any(trigger in header for trigger in redaction.TRIGGERS)


def test_uvicorns_ansi_duplicate_of_the_message_is_dropped(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Every ``uvicorn.error`` record carries the same text twice, once with escape codes in it.

    Observed against a real ``uvicorn app.main:app`` rather than inferred: the startup lines
    arrived as ``{"msg": "Started server process [410978]", "color_message": "Started server
    process [\\u001b[36m%d\\u001b[0m]"}``. An ANSI escape inside a JSON string helps nobody.
    """
    configure_logging("INFO")

    ansi = chr(27)
    logging.getLogger("uvicorn.error").warning(
        "Started server process [%d]",
        410978,
        extra={"color_message": f"Started server process [{ansi}[36m%d{ansi}[0m]"},
    )

    line = captured_lines(capsys)[-1]
    assert line["msg"] == "Started server process [410978]"
    assert "color_message" not in line
    assert ansi not in json.dumps(line)
