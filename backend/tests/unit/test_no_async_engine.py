"""ADR 0001's foreclosure, made mechanical.

Kaya is 100% synchronous: one engine, one pool. The failure mode this guards against is not
malice, it is autocomplete — `AsyncSession` and `create_async_engine` are what a code model
suggests the moment it sees SQLAlchemy and FastAPI in the same file. Reintroducing one means
either kaya took on its own login (contradicting ADR 0002) or something needs re-examining, and
either way it should cost a conversation rather than slip in.

The scan is over the AST rather than the raw text, so the prose explaining the ban doesn't trip
the ban.
"""

import ast
from pathlib import Path

from app.config import DEFAULT_DATABASE_URL

APP_ROOT = Path(__file__).resolve().parents[2] / "app"

FORBIDDEN = frozenset(
    {
        "create_async_engine",
        "async_sessionmaker",
        "AsyncSession",
        "AsyncEngine",
        "asyncpg",
        "psycopg2",  # ADR 0001 pins psycopg v3; v2 is a different driver, not an alias
    }
)


def offending_names(source: str, *, filename: str = "<memory>") -> list[str]:
    """Every reference to a forbidden name, as `filename:lineno: name`."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        names: list[str] = []
        if isinstance(node, ast.Name):
            names = [node.id]
        elif isinstance(node, ast.Attribute):
            names = [node.attr]
        elif isinstance(node, ast.Import):
            names = [part for a in node.names for part in a.name.split(".")]
        elif isinstance(node, ast.ImportFrom):
            names = (node.module or "").split(".") + [a.name for a in node.names]
        found += [
            f"{filename}:{getattr(node, 'lineno', 0)}: {name}"
            for name in names
            if name in FORBIDDEN
        ]
    return sorted(found)


def test_no_async_database_machinery_anywhere_in_app() -> None:
    modules = sorted(APP_ROOT.rglob("*.py"))
    assert len(modules) >= 4, "the glob found almost nothing — the guard would pass vacuously"

    offenders: list[str] = []
    for path in modules:
        offenders += offending_names(path.read_text(encoding="utf-8"), filename=path.name)

    assert offenders == [], (
        "ADR 0001 forecloses an async engine and pins psycopg v3; found: " + ", ".join(offenders)
    )


def test_the_guard_catches_what_it_claims_to() -> None:
    """The guard is an emptiness assertion, which is the shape that passes for the wrong reason.

    Feed the same scanner a module that breaks the rule and confirm it objects, so a refactor that
    quietly neuters the scan fails here instead of going unnoticed for a slice.
    """
    breach = (
        "from sqlalchemy.ext.asyncio import create_async_engine\n"
        "engine = create_async_engine(url)\n"
    )

    assert offending_names(breach) != []
    assert offending_names("from sqlalchemy import create_engine\n") == []


def test_the_default_url_names_psycopg_v3() -> None:
    assert DEFAULT_DATABASE_URL.startswith("postgresql+psycopg://")
    assert "psycopg2" not in DEFAULT_DATABASE_URL
