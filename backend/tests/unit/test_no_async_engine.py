"""ADR 0001's foreclosure, made mechanical — now scoped by ADR 0012's amendment.

Kaya's *board and note* surface is 100% synchronous: one engine, one pool. The failure mode this
guards against is not malice, it is autocomplete — `AsyncSession` and `create_async_engine` are
what a code model suggests the moment it sees SQLAlchemy and FastAPI in the same file. Async
creeping into `app/api/`, `app/models/`, or `app/auth/` means either a route started depending on
kaya's own login machinery where it shouldn't yet, or something needs re-examining, and either way
it should cost a conversation rather than slip in.

**`app/identity/` is the one deliberate exception (ADR 0012, KAN-1738).** `fastapi-users`' user
store is async-only, so kaya's own authorization server carries a second, quarantined async engine
there — see `app/identity/db.py`'s module docstring. Everything else in `app/` stays on the guard
below, unconditionally; a new file under `app/identity/` does not widen the exemption to anywhere
else, and a forbidden name reappearing outside that one package still fails here.

The scan is over the AST rather than the raw text, so the prose explaining the ban doesn't trip
the ban.
"""

import ast
from pathlib import Path

from app.config import DEFAULT_DATABASE_URL

APP_ROOT = Path(__file__).resolve().parents[2] / "app"
EXEMPT_DIR = APP_ROOT / "identity"

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


def test_no_async_database_machinery_outside_identity() -> None:
    modules = sorted(
        p for p in APP_ROOT.rglob("*.py") if EXEMPT_DIR not in p.parents and p.parent != EXEMPT_DIR
    )
    assert len(modules) >= 4, "the glob found almost nothing — the guard would pass vacuously"

    offenders: list[str] = []
    for path in modules:
        offenders += offending_names(path.read_text(encoding="utf-8"), filename=path.name)

    assert offenders == [], (
        "ADR 0001 forecloses an async engine outside app/identity/ (ADR 0012's one exception) "
        "and pins psycopg v3; found: " + ", ".join(offenders)
    )


def test_identity_package_is_the_only_exemption() -> None:
    """The exemption is one directory, not "anywhere the scanner happened not to look."

    Every module actually under ``app/identity/`` is excluded above; this pins that the exclusion
    predicate matches that directory and nothing wider, so a future refactor that broadens the glob
    (e.g. matching any path *containing* "identity") gets caught here instead of silently exempting
    something like a hypothetical ``app/identity_check.py``.
    """
    sibling = APP_ROOT / "identity_check.py"
    assert EXEMPT_DIR not in sibling.parents and sibling.parent != EXEMPT_DIR


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
