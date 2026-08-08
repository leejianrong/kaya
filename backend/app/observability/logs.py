"""One JSON line per event, on stdout, through one handler.

dev-playbook §17: "You can't call it shipped if you can't see it running." Kaya had the health
endpoint and nothing else — whatever uvicorn printed by default was the entire story, which under
ADR 0010 means the homelab pod, where nobody is watching a terminal, and where `kubectl logs` is
the only thing there is to read.

**stdout, not a file and not a socket.** The container (`Dockerfile`) and the manifests
(`deploy/k8s/`) both expect the process to write its log to stdout and expect something else to
collect it. A log file inside a pod is a log file nobody reads.

**One format, in development too.** A pretty console renderer for `make dev` and JSON for
production is two code paths, and the one that runs in production is then the one nobody looks at
until it matters. `make dev` gets JSON and `jq`.

**Everything goes through the root logger**, uvicorn's own records included, so a line from httpx
or SQLAlchemy is the same shape as a line from kaya and is scrubbed by the same formatter
(``app.observability.redaction``). That is the point of configuring the root rather than a
``kaya`` logger: a third-party library that logs a request object is exactly the leak this has to
survive, and it will never import anything of ours.
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, TextIO

from app.config import get_settings
from app.observability.redaction import scrub

REQUEST_ID: ContextVar[str | None] = ContextVar("kaya_request_id", default=None)
"""The current request's id, set by ``app.observability.middleware``.

A context variable rather than a parameter, because the point is to correlate log lines written by
code that knows nothing about HTTP — a SQLAlchemy warning, an httpx retry, a traceback from four
frames down. Passing an id to those is not available; reading one here is.
"""

LOGGER_NAME = "kaya"
"""Root of kaya's own logger namespace. Third-party records keep their own names."""

_CORE_FIELDS = ("ts", "level", "logger", "msg", "request_id", "error")
"""Fields the formatter owns. An ``extra=`` key colliding with one of these is dropped, so a
caller cannot overwrite the timestamp or forge a request id by naming a field badly."""

_RECORD_ATTRIBUTES = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {
    "taskName",
    "message",
    "asctime",
}
"""Every attribute the stdlib puts on a ``LogRecord``, computed from a real one rather than typed
out — a hand-written list goes stale the first time CPython adds a field, and the symptom is a
``LogRecord`` internal appearing in the log as though a caller had passed it. ``taskName`` (3.12),
``message`` and ``asctime`` are added because they are set later by the formatting machinery
rather than by the constructor."""

_IGNORED_EXTRAS = frozenset({"color_message"})
"""Third-party ``extra=`` keys that are noise in a JSON line rather than data.

One entry, and it is uvicorn's: every ``uvicorn.error`` record carries a ``color_message`` holding
the same text as ``msg`` with ANSI escape sequences in it, for the colourising handler this app
replaced. Kept out because an escape sequence embedded in a JSON string is unreadable in
`kubectl logs`, meaningless to a collector, and a duplicate of a field already on the line."""


class StdoutHandler(logging.StreamHandler):
    """A stream handler that resolves ``sys.stdout`` **at emit time**, not at construction.

    ``logging.StreamHandler(sys.stdout)`` captures the object once. That is wrong twice over: a
    test using pytest's ``capsys`` replaces ``sys.stdout`` *after* this handler is built and would
    see nothing, so the redaction guard could not observe what it is guarding; and any code that
    reopens stdout at runtime would leave the handler writing to a closed file. Late binding costs
    one attribute lookup per record.
    """

    def __init__(self) -> None:
        # Handler, not StreamHandler: `StreamHandler.__init__` assigns `self.stream`, and `stream`
        # is a read-only property below. There is no setter on purpose — something calling
        # `setStream` wants a different stream than this class is willing to give it, and should
        # fail loudly rather than be silently ignored.
        logging.Handler.__init__(self)

    @property
    def stream(self) -> TextIO:
        return sys.stdout


class JsonFormatter(logging.Formatter):
    """A ``LogRecord`` as one line of JSON, scrubbed.

    The last statement in ``format`` is the security boundary for the whole application: ``scrub``
    sees the complete payload, and nothing reaches stdout that did not go through it. Every reason
    that is the right place for it, rather than the call sites, is in
    ``app.observability.redaction``.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            # `record.created` is a POSIX timestamp; UTC and an explicit `Z`, because a log
            # correlated across a pod and a laptop cannot be in two local times.
            "ts": datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "logger": record.name,
            # `getMessage` applies the `%`-args. Doing it here rather than reading `record.msg`
            # matters: `logger.info("resolved %s", bearer)` puts the credential in `args`, and a
            # formatter that scrubbed `msg` alone would print it from `args` untouched.
            "msg": record.getMessage(),
        }

        request_id = getattr(record, "request_id", None) or REQUEST_ID.get()
        if request_id:
            payload["request_id"] = request_id

        for key, value in vars(record).items():
            if key in _RECORD_ATTRIBUTES or key in _CORE_FIELDS or key in _IGNORED_EXTRAS:
                continue
            payload[key] = value

        if record.exc_info:
            exc_type, exc, _ = record.exc_info
            payload["error"] = {
                "type": exc_type.__name__ if exc_type else "Exception",
                "message": str(exc) if exc else "",
                # The traceback is the error surface. `app/api/errors.py` deliberately declines to
                # *format* a `500` for the caller; that decision is about the response body and is
                # untouched here. This is the operator's copy, and without it an unhandled
                # exception in the pod is a status code with no cause attached.
                "traceback": self.formatException(record.exc_info),
            }

        return json.dumps(
            scrub(payload),
            # Unreachable by construction: `scrub` returns only JSON-native values. It is a
            # refusal rather than `default=str` because the one thing that could get here is an
            # object `scrub` failed to flatten, and printing its `repr()` unexamined is the exact
            # accident this formatter exists to prevent.
            default=lambda _: "[unserializable]",
            separators=(",", ":"),
        )


def configure_logging(level: str | None = None) -> None:
    """Install the one stdout handler on the root logger. Idempotent.

    Idempotent because it is called from ``app.main`` at import and again by any test that wants a
    clean handler — and a `configure` that appends would produce one duplicate log line per call,
    which is how a suite ends up asserting against the *second* copy of a record.
    """
    resolved = (level or get_settings().log_level).upper()

    root = logging.getLogger()
    for existing in [h for h in root.handlers if isinstance(h, StdoutHandler)]:
        root.removeHandler(existing)

    handler = StdoutHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(resolved)

    # uvicorn installs its own handlers on these three and sets `propagate = False`, so without
    # this its records bypass the root handler entirely and arrive as unstructured text next to
    # kaya's JSON. Clearing the handlers and restoring propagation folds them into one stream.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True

    # `uvicorn.access` is the one exception: its INFO line is the same request this app already
    # logs from `app.observability.middleware`, with less in it. Raising its level to WARNING
    # silences the duplicate without silencing the logger — an actual warning from uvicorn's
    # access machinery still arrives, as JSON, through the root handler.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> logging.Logger:
    """A logger under kaya's namespace. ``get_logger("access")`` → ``kaya.access``."""
    return logging.getLogger(LOGGER_NAME if name is None else f"{LOGGER_NAME}.{name}")
