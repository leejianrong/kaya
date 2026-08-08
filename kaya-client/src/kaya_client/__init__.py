"""kaya's shared core: the API client and the single payload-shaping seam.

Two things live here, and the second is the reason the first must not return a ``dict``:

- ``KayaClient`` over httpx, the only thing in the suite that speaks to ``/api/v1``. Its methods
  return a ``Payload`` — the complete API response plus the schema facts shaping needs.
- ``render(payload, *, fields, text_limit, fmt)`` — the one seam every projection, truncation,
  aggregate and serialization decision goes through (ADR 0004). Both adapters call it. Neither
  reimplements any of it, and a projection or truncation rule appearing in `kaya-cli/` or `mcp/` is
  a bug rather than a local optimisation.

``render`` is four composable steps in ADR 0004's fixed order, one module each, so the "god
function" risk that ADR flags against itself has somewhere to be tested apart:

    projection → truncation → aggregate attachment → serialization
    projection.py  truncation.py  aggregates.py       serialization.py

**V2a (KAN-540) implements the ``fmt`` dimension only.** ``fields`` and ``text_limit`` are in the
signature, are validated for shape, and pass through untouched; `tests/test_passthrough_is_a_no_op`
pins that, so V2b filling them in is a visible diff. ADR 0005 puts the signature before the
behaviour on purpose — if a later card needs this signature to change, that is the signal the
sequencing broke, not a reason to push through. ``render``'s module docstring argues requirement by
requirement why V2b lands on it unmoved.

Still to come: ``toon`` and the ``--format`` flag (KAN-541), the shaping behaviour (V2b), the write
verbs (V2b), search and links (KAN-558/559, KAN-566).
"""

from importlib.metadata import PackageNotFoundError, version

from kaya_client.aggregates import attach_summary
from kaya_client.client import KayaClient
from kaya_client.errors import ApiError, KayaError, TransportError, UnknownFormat
from kaya_client.payloads import Kind, Payload, Shaped
from kaya_client.projection import project
from kaya_client.render import render
from kaya_client.serialization import Format, serialize
from kaya_client.truncation import DEFAULT_TEXT_LIMIT, truncate

try:
    __version__ = version("kaya-client")
except PackageNotFoundError:  # pragma: no cover - source checkout without an install
    __version__ = "0.0.0"

__all__ = [
    "DEFAULT_TEXT_LIMIT",
    "ApiError",
    "Format",
    "KayaClient",
    "KayaError",
    "Kind",
    "Payload",
    "Shaped",
    "TransportError",
    "UnknownFormat",
    "__version__",
    "attach_summary",
    "project",
    "render",
    "serialize",
    "truncate",
]
