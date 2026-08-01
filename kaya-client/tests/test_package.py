"""The package is importable and its version is honest.

Thin, because the package is thin — but not a placeholder. The version assertion is the mechanical
half of ADR 0007: a behavioural change bumps the version in the same PR, and a bump that touches
`pyproject.toml` while the installed distribution says something else is the drift that makes a
release's provenance a guess. That failure is silent otherwise, since nothing reads both numbers.
"""

import tomllib
from pathlib import Path

import kaya_client

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def declared_version() -> str:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]


def test_the_package_imports() -> None:
    assert kaya_client.__version__ != "0.0.0", "installed metadata is missing — not a real install"


def test_the_installed_version_matches_pyproject() -> None:
    assert kaya_client.__version__ == declared_version()


def test_the_distribution_is_licensed_apache_2() -> None:
    """Package metadata has to agree with the LICENSE file at the repo root."""
    from importlib.metadata import metadata

    declared = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["license"]
    assert declared == "Apache-2.0"
    assert metadata("kaya-client")["License-Expression"] == "Apache-2.0"
