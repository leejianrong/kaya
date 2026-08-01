"""The Alembic autogenerate trap, guarded statically.

`alembic/env.py` must import the models package, or `--autogenerate` diffs the live database
against empty metadata and writes a migration that drops every table. It is the second of the two
inherited traps in CLAUDE.md, and it is silent: the migration file looks plausible, and you find
out when you run it.

This is a source-level check rather than a behavioural one on purpose — `env.py` is a script that
runs migrations as a side effect of import, so the cheap way to hold it to its contract is to read
it. The behavioural half (upgrade against a real database) is in `tests/integration`.
"""

import ast
from pathlib import Path

ENV_PY = Path(__file__).resolve().parents[2] / "alembic" / "env.py"


def test_env_py_imports_the_models_package() -> None:
    tree = ast.parse(ENV_PY.read_text(encoding="utf-8"))

    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    assert "app.models" in imported, (
        "alembic/env.py must import app.models, or autogenerate will emit a migration that drops "
        "your tables (CLAUDE.md §Two inherited traps)"
    )


def test_target_metadata_comes_from_base() -> None:
    source = ENV_PY.read_text(encoding="utf-8")

    assert "target_metadata = Base.metadata" in source
    assert "target_metadata = None" not in source, "the alembic init default was left in place"


def test_the_url_is_not_pinned_in_alembic_ini() -> None:
    """A URL in the ini would let migrations run against a different database than the app, and
    would put a credential in a tracked file."""
    ini = (ENV_PY.parents[1] / "alembic.ini").read_text(encoding="utf-8")

    live = [line for line in ini.splitlines() if line.strip().startswith("sqlalchemy.url")]
    assert live == [], f"alembic.ini pins a database URL: {live}"
    assert "get_settings().database_url" in ENV_PY.read_text(encoding="utf-8")
