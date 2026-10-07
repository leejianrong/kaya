"""The API error shape's one builder — split into its own module (KAN-1740).

Before ADR 0012's cutover this lived in ``app/auth/resolver.py``, ADR 0002's introspection module,
purely because that was the first module that needed a `{"error": {...}}` body. It has nothing to
do with identity — every route in ``app/api/`` raises through it — so it gets its own module rather
than following ``resolver.py`` into deletion. ``app/auth/__init__.py`` still re-exports it at
``app.auth.error_body``, so no call site anywhere in ``app/api/`` needed to change.
"""

from typing import Any


def error_body(code: str, message: str, **extra: Any) -> dict[str, dict[str, Any]]:
    """The error shape. One builder, so a status is never paired with a bare prose string.

    ``{"error": {"code", "message", …}}`` reaches the wire exactly as written. KAN-536 settled that
    (``app/api/errors.py``): FastAPI's default handler wraps a raise site's ``detail``, so this
    object used to arrive double-nested under ``detail``, and one handler at the app boundary
    un-nests it. Nothing at a raise site had to change, which is the point of there being one
    builder.

    ``code`` and ``message`` are always strings, and a refusal a human reads is those two alone.
    ``**extra`` is usually a string too — ``field`` on a `422`, ``ref`` on a bad identifier — but it
    is not restricted to one, because some refusals are only actionable with data attached: ADR
    0009's `409` carries two whole notes so the caller can diff them
    (``app/api/concurrency.py``). Anything passed here must be JSON-encodable;
    ``jsonable_encoder`` in the boundary handler does the rest.
    """
    return {"error": {"code": code, "message": message, **extra}}
