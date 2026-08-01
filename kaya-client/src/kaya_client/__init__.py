"""kaya's shared core: the API client and the single payload-shaping seam.

Deliberately empty of logic. KAN-531 is the scaffold; this package earns its contents in V2a:

- ``KayaClient`` over httpx, the only thing that speaks to ``/api/v1``.
- ``render(payload, *, fields, text_limit, fmt)`` — the one seam every projection, truncation,
  aggregate and serialization decision goes through (ADR 0004).

Both adapters call in here. Neither reimplements any of it.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("kaya-client")
except PackageNotFoundError:  # pragma: no cover - source checkout without an install
    __version__ = "0.0.0"

__all__ = ["__version__"]
