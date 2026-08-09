"""kaya's shared core: the API client and the single payload-shaping seam.

Two things live here, and the second is the reason the first must not return a ``dict``:

- ``KayaClient`` over httpx, the only thing in the suite that speaks to ``/api/v1``. Its methods
  return a ``Payload`` — the complete API response plus the schema facts shaping needs.
- ``render(payload, *, fields, text_limit, fmt)`` — the one seam every projection, truncation,
  aggregate and serialization decision goes through (ADR 0004). Both adapters call it. Neither
  reimplements any of it, and a projection or truncation rule appearing in `kaya-cli/` or `mcp/` is
  a bug rather than a local optimisation.

A third, smaller thing sits alongside them for the same reason: ``version_line()`` in `provenance`,
which turns the build stamp into ADR 0007's two ``--version`` forms. It is here rather than in
`kaya-cli` because the sha is a fact about the repository both adapters are built from, and because
V6's MCP server reports its own provenance by calling it. It deliberately does *not* go through
``render``, whose signature ADR 0005 freezes until V2b — see `provenance`'s module docstring.

``render`` is four composable steps in ADR 0004's fixed order, one module each, so the "god
function" risk that ADR flags against itself has somewhere to be tested apart:

    projection → truncation → aggregate attachment → serialization
    projection.py  truncation.py  aggregates.py       serialization.py

Two format vocabularies, because two audiences: ``Format`` is what a person may type after
``--format`` — ``human``, ``json`` and, since KAN-541, ``toon`` — and is therefore a published
contract; ``AdapterFormat`` (``data``) is what an in-tree adapter asks for in code. ``CLI_FORMATS``
is the first as a tuple, ready for argparse's ``choices``. The ``toon`` encoder is in `toon`,
stdlib-only and **encode-only**: the round-trip contract is proven by a decoder that lives in
``tests/``, because nothing in the product reads TOON back.

``config`` resolves PLAN §Config's ``KAYA_API_URL``, ``KAYA_TOKEN`` and — since KAN-547 —
``KAYA_MAX_TEXT_CHARS`` from the environment, and hands back a ``KayaClient``, so both adapters
agree about which deployment they are talking to and how much prose a read returns. Its file tiers
and the ``config`` verbs are KAN-551's.

**Failures render through the same layer** (KAN-542). ``render_error(failure, fmt=…)`` produces ADR
0005 §contract 3's ``error<TAB>code<TAB>message<TAB>arg`` row or the ``{"error": {…}}`` object, with
``code``/``message``/``arg`` always present; ``error_payload`` builds that object for a caller that
wants the dict rather than a rendering. What the client deliberately does *not* own is the stream or
the exit number — ADR 0005's exit table is `kaya-cli`'s, because an MCP tool has neither. Every
exception class here carries a ``code``, so a raise site names a meaning and the CLI's table is a
lookup rather than a judgement.

**V2a (KAN-540) implemented the ``fmt`` dimension only; KAN-546 added ``fields`` and KAN-547
``text_limit``.** Projection selects a subset of the record's own keys — vocabulary from
``Payload.field_names()``, an unknown name refused by name, ``fields`` on a single entity a
``UsageError`` — and it does the same thing in every format, because the CLI's ``--fields`` and
MCP's ``fields`` are one parameter through one seam. Truncation cuts the fields named by
``Payload.prose_fields`` and appends a hint carrying the **true** total in-band, so the total
survives into ``json``, ``toon`` and ``data``; ``0`` disables it and is what ``--full`` resolves to.
ADR 0005 puts the signature before the behaviour on purpose — **``render``'s signature did not move
for either card and must not move for what follows**; if a later card needs it to change, that is
the signal the sequencing broke, not a reason to push through. ``render``'s module docstring argues
requirement by requirement why.

Still to come: aggregates (KAN-548), content-first and ``help[]``, the write verbs, search and links
(KAN-558/559, KAN-566).
"""

from importlib.metadata import PackageNotFoundError, version

from kaya_client.aggregates import attach_summary
from kaya_client.client import KayaClient
from kaya_client.config import (
    API_URL_ENV,
    MAX_TEXT_CHARS_ENV,
    TOKEN_ENV,
    api_url,
    max_text_chars,
    open_client,
)
from kaya_client.errors import (
    ARG_KEY,
    CODE_KEY,
    CONTRACT_KEYS,
    MESSAGE_KEY,
    ApiError,
    KayaError,
    MissingCredential,
    TransportError,
    UnknownFormat,
    UsageError,
    error_payload,
)
from kaya_client.payloads import Kind, Payload, Shaped
from kaya_client.projection import project
from kaya_client.provenance import SOURCE_CHECKOUT, build_sha, version_line
from kaya_client.render import render, render_error
from kaya_client.serialization import (
    CLI_FORMATS,
    ERROR_MARKER,
    ROW_SEPARATOR,
    AdapterFormat,
    Format,
    serialize,
    serialize_error,
)
from kaya_client.truncation import DEFAULT_TEXT_LIMIT, hint, truncate

try:
    __version__ = version("kaya-client")
except PackageNotFoundError:  # pragma: no cover - source checkout without an install
    __version__ = "0.0.0"

__all__ = [
    "API_URL_ENV",
    "ARG_KEY",
    "CLI_FORMATS",
    "CODE_KEY",
    "CONTRACT_KEYS",
    "DEFAULT_TEXT_LIMIT",
    "ERROR_MARKER",
    "MAX_TEXT_CHARS_ENV",
    "MESSAGE_KEY",
    "ROW_SEPARATOR",
    "SOURCE_CHECKOUT",
    "TOKEN_ENV",
    "AdapterFormat",
    "ApiError",
    "Format",
    "KayaClient",
    "KayaError",
    "Kind",
    "MissingCredential",
    "Payload",
    "Shaped",
    "TransportError",
    "UnknownFormat",
    "UsageError",
    "__version__",
    "api_url",
    "attach_summary",
    "build_sha",
    "error_payload",
    "hint",
    "max_text_chars",
    "open_client",
    "project",
    "render",
    "render_error",
    "serialize",
    "serialize_error",
    "truncate",
    "version_line",
]
