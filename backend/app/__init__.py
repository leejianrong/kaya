"""kaya notes backend."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("kaya-backend")
except PackageNotFoundError:  # pragma: no cover - source checkout without an install
    __version__ = "0.0.0"

__all__ = ["__version__"]
