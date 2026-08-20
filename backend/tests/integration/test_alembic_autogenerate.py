"""`alembic revision --autogenerate` writes a lint-clean revision, through the real command.

KAN-692. The fast half of this guard is `tests/unit/test_alembic_post_write_hooks.py`, which runs
the hook `alembic.ini` declares over a rendered fixture. This is the half that runs no fixture at
all: a real Postgres, `upgrade head`, a real `DROP TABLE`, and the real `alembic revision
--autogenerate`, so the text under test is whatever alembic's renderer decides to emit today rather
than a copy of what it emitted when the card was written. The renderer is the thing that changes
out from under us; a fixture cannot notice that and this can.

**The positive control is the point.** Each run generates the revision twice from the same database
state: once with `[post_write_hooks]` stripped off the `Config`, once with it. The first must fail
E501 — otherwise "clean with the hook" is a green test about nothing, which is exactly the trap the
`search_vector` column sets elsewhere in this suite (autogenerate does not diff a generated
column's expression, so a drop-and-regenerate can quietly produce `pass`). Asserting the *before*
is what rules that out here.

**Why `note_link` is the table that gets dropped.** It has to be a table whose rendering actually
overruns — measured: `created_at` at 105 characters, the FK constraint at 128, the unique
constraint at 112 — and whose overruns are all inside argument lists, which is what a formatter can
reflow. Dropping `note` as well adds a ninth finding that no formatter can repair, because it is
one 224-character line whose excess is a single string literal (`sa.Computed(...)` over the
`search_vector` expression). That boundary is real and is pinned in the unit test, against a
verbatim fixture rather than against the live expression — which would make this test's verdict a
function of how long somebody's SQL happens to be.

**Nothing here touches the shared database.** `tests/integration` runs one session against one
container, and this test drops a table on purpose; dropping `note_link` out from under
`test_note_link_reconcile.py` would surface as a bug in the reconciler. So it migrates its own
database inside the same container and drops it afterwards.

Per this package's placement rule, every `import app.*` and every `import alembic.*` is inside a
test or fixture body: a module-level app import runs at collection, before the fixture has set
`DATABASE_URL`.
"""

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REAL_VERSIONS = BACKEND_ROOT / "alembic" / "versions"

# Its own database, so the shared one keeps its tables. Named for the card, so a leaked one on a
# hard-killed run is traceable rather than mysterious.
PROBE_DATABASE = "kaya_kan692_autogenerate"


@pytest.fixture
def probe_database(database_url: str) -> Iterator[str]:
    """An empty database in the session's container, migrated by the test and dropped after."""
    from sqlalchemy import create_engine, make_url, text

    from app.db import reset_engine

    # CREATE DATABASE cannot run inside a transaction block.
    admin = create_engine(database_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{PROBE_DATABASE}" WITH (FORCE)'))
        connection.execute(text(f'CREATE DATABASE "{PROBE_DATABASE}"'))

    probe_url = make_url(database_url).set(database=PROBE_DATABASE)
    previous = os.environ["DATABASE_URL"]
    os.environ["DATABASE_URL"] = probe_url.render_as_string(hide_password=False)
    reset_engine()
    try:
        yield os.environ["DATABASE_URL"]
    finally:
        os.environ["DATABASE_URL"] = previous
        reset_engine()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{PROBE_DATABASE}" WITH (FORCE)'))
        admin.dispose()


def _config(version_path: Path, *, with_hooks: bool):
    """The real `alembic.ini`, with the generated file diverted out of the repository.

    `version_locations` keeps the real `versions/` directory so `head` resolves to the real head,
    and adds `version_path`, which is where `command.revision(version_path=...)` writes. Nothing
    lands in `alembic/versions/`; a stray revision file there would break `upgrade head` for
    everyone, and the test asserts it stayed empty.
    """
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option(
        "version_locations", os.pathsep.join([str(REAL_VERSIONS), str(version_path)])
    )
    if not with_hooks:
        # The negative arm of the positive control. Removing the section is the same mutation as
        # deleting it from `alembic.ini`, which is what this guard has to notice.
        config.file_config.remove_section("post_write_hooks")
    return config


def _generate(version_path: Path, *, with_hooks: bool) -> Path:
    """One `alembic revision --autogenerate`, returning the file it wrote."""
    from alembic import command

    command.revision(
        _config(version_path, with_hooks=with_hooks),
        message="kan692 probe",
        autogenerate=True,
        version_path=str(version_path),
    )
    written = sorted(version_path.glob("*.py"))
    assert len(written) == 1, f"expected one generated revision, got {written}"
    return written[0]


def _ruff_check(path: Path) -> subprocess.CompletedProcess[str]:
    """The repo's own ruff config over a file that lives outside the repo.

    A twin of `tests/unit/alembic_render.py`'s helper rather than an import of it: the two test
    packages do not share a namespace, and copying nine lines is cheaper than making them.
    """
    return subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--no-cache", "--output-format", "concise",
         "--config", str(BACKEND_ROOT / "pyproject.toml"), str(path)],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.usefixtures("probe_database")
def test_an_autogenerated_revision_is_lint_clean_as_written(tmp_path: Path) -> None:
    from alembic import command
    from sqlalchemy import text

    from app.db import get_engine

    real_versions_before = sorted(p.name for p in REAL_VERSIONS.glob("*.py"))

    command.upgrade(_config(tmp_path, with_hooks=False), "head")

    # The models still declare `note_link`, so autogenerate's next diff is a create_table for it —
    # and `alembic/versions/0003` shows what that renders as before anybody reflows it by hand.
    with get_engine().begin() as connection:
        connection.execute(text("DROP TABLE note_link"))

    unformatted = _generate(tmp_path, with_hooks=False)
    unformatted_source = unformatted.read_text(encoding="utf-8")
    control = _ruff_check(unformatted)
    assert "E501" in control.stdout, (
        "POSITIVE CONTROL FAILED. With the hook stripped off, the revision alembic just generated "
        "is already within 100 columns — so the assertion below would pass whether or not the hook "
        "does anything, and this test proves nothing. Either the renderer changed or the dropped "
        f"table stopped being wide.\n{control.stdout}{control.stderr}\n\n{unformatted_source}"
    )
    assert any(
        len(line) > 100 and "sa.Column(" in line for line in unformatted_source.splitlines()
    ), f"the overrun is no longer on a rendered column:\n{unformatted_source}"
    unformatted.unlink()

    formatted = _generate(tmp_path, with_hooks=True)
    formatted_source = formatted.read_text(encoding="utf-8")
    result = _ruff_check(formatted)

    assert result.returncode == 0, (
        "`alembic revision --autogenerate` wrote a revision that fails lint. The formatter in "
        "alembic.ini's [post_write_hooks] is what is supposed to prevent that; note that alembic "
        "runs the hook with `subprocess.run` and no `check=`, so a hook that exits non-zero is "
        f"swallowed and looks exactly like no hook at all.\n{result.stdout}{result.stderr}\n\n"
        f"{formatted_source}"
    )
    assert formatted_source != unformatted_source, (
        "the hook left the file byte-identical, which is what a swallowed hook failure looks like"
    )
    # The hook reflowed the migration rather than emptying it.
    assert 'op.create_table(\n        "note_link"' in formatted_source
    assert "op.drop_table" in formatted_source

    assert sorted(p.name for p in REAL_VERSIONS.glob("*.py")) == real_versions_before, (
        "a probe revision escaped into alembic/versions/"
    )
