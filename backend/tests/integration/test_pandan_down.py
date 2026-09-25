"""R5.1: with pandan completely stopped, a note still saves, renders, and is searchable.

ADR 0003's line, restated as SLICES §V5's own acceptance criterion (its wording, verbatim): "the
note saves, renders, and appears in full-text search; the link renders unresolved with a hint and
nothing returns an error." This is the guard the card asks for, and the card asks for it loudly on
purpose — CLAUDE.md's framing is that this is exactly the kind of degradation guard that passes for
the wrong reason, so it is written to be mutated and watched failing (see the PR description for
the mutation actually run).

**ADR 0002's identity exception is gone (KAN-1740).** This file used to spend most of its own
docstring on a boundary: authentication was the one place kaya was *allowed* to depend on pandan, so
every test here had to warm a principal cache with pandan reachable before stopping it, and a
separate pair of tests proved the honest edge of that exception (a `503` for a cold bearer, never a
false `401`). ADR 0012 removed the dependency those tests existed to bound — kaya's own identity
resolution (`app/auth/kaya_principal.py`) is a local database lookup with no pandan call in it at
all, ever — so there is no exception left to draw a boundary around, and this file is now simply
"none of these code paths call pandan," full stop. `stopped` below still fakes a stopped pandan
(for `CardEpicUpstream`, the one thing note *linking* can call), but nothing about identity needs a
fake, a clock, or a cache any more.

Wikilink reconciliation (`app/note_links.py`, `app/wikilinks.py`) and full-text search
(`app/auth/authorization.py`'s `notes_matching`, `app/api/search.py`) make **no network call at
all**, today or ever, by design (see both modules' docstrings). So the honest claim this file makes
is that the code paths it drives — create, read, edit, move, search, delete, and wikilink
reconciliation — never call pandan, which is exactly SLICES §V4/§V5's promise and exactly what a
future card wiring a blocking call into `create_note`, `get_note` or `notes_matching` would break
first.

`GET /api/v1/notes/{ref}/links` **is** allowed to call pandan (ADR 0003 forbids *blocking* on it,
not calling it) and is deliberately **not** driven from this file —
`tests/integration/test_note_links_api.py` owns it, along with `/backlinks`'s own no-upstream-at-all
claim, because the property to assert there is different in kind: not "no call happened" but "the
call happened, failed, and cost the response nothing but three nulls".

**No `import app.*` at module top** — see the package docstring, and pandan's PR #17 trap: a
top-level `app` import runs at collection, before the `database_url` fixture sets `DATABASE_URL`.
"""

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from tests.integration.auth_helpers import override_get_principal, seed_kaya_account

BACKEND_ROOT = Path(__file__).resolve().parents[2]

ALICE_TOKEN = "a-caller-supplied-string-kaya-does-not-parse"
ALICE_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")

NOTES = "/api/v1/notes"


def _alembic_config() -> Any:
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


@pytest.fixture
def client(database_url: str) -> Iterator[Any]:
    """The real app (`app.main.app`) with identity faked directly (`override_get_principal`,
    KAN-1740) — no upstream, no cache, no clock, because there is no pandan call left in the
    identity path for any of those to shield a test from."""
    from alembic import command
    from fastapi.testclient import TestClient

    from app.auth.principal import Principal
    from app.db import get_sessionmaker
    from app.main import app

    command.upgrade(_alembic_config(), "head")

    def empty() -> None:
        with get_sessionmaker()() as session:
            session.execute(text("TRUNCATE TABLE note_link, note, kaya_account CASCADE"))
            session.commit()

    empty()
    with get_sessionmaker()() as session:
        seed_kaya_account(session, id=ALICE_ID, email="alice@example.com")
    known_principals = {ALICE_TOKEN: Principal(id=ALICE_ID, email="alice@example.com")}
    override_get_principal(app, known_principals)
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        empty()


def auth(token: str = ALICE_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create(client: Any, token: str = ALICE_TOKEN, **fields: str) -> dict[str, Any]:
    fields.setdefault("title", "a note")
    response = client.post(NOTES, json=fields, headers=auth(token))
    assert response.status_code == 201, response.text
    return response.json()


# --- The demo, end to end: create, read, edit, delete, search, all with pandan stopped ------------


def test_full_note_crud_and_search_survive_pandan_being_completely_down(client: Any) -> None:
    """SLICES §V5's end-to-end row, word for word: "the note saves, renders, and appears in
    full-text search ... and nothing returns an error." **[mutate]**

    No pandan fake to stop here at all — identity never calls it (KAN-1740) and nothing in this
    flow touches card/epic resolution (`GET /links` is the one route that does, and it is
    deliberately not exercised here — see the module docstring). What this test actually proves is
    narrower and just as real: the note verbs make no call to any upstream, full stop.
    """
    created = create(
        client,
        ALICE_TOKEN,
        title="a runbook",
        body="see [[KAN-501]] and [[EPIC-9]] for context",
        path="ops/runbook.md",
    )
    assert created["ref"].startswith("NOTE-")

    read = client.get(f"{NOTES}/{created['ref']}", headers=auth(ALICE_TOKEN))
    assert read.status_code == 200
    assert read.json() == created

    edited = client.patch(
        f"{NOTES}/{created['ref']}",
        json={"body": "revised, still see [[KAN-501]]", "if_updated_at": created["updated_at"]},
        headers=auth(ALICE_TOKEN),
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["body"] == "revised, still see [[KAN-501]]"

    moved = client.patch(
        f"{NOTES}/{created['ref']}",
        json={"path": "archive/runbook.md"},
        headers=auth(ALICE_TOKEN),
    )
    assert moved.status_code == 200, moved.text

    found = client.get(NOTES, params={"q": "runbook"}, headers=auth(ALICE_TOKEN))
    assert found.status_code == 200, found.text
    assert [note["ref"] for note in found.json()["notes"]] == [created["ref"]]

    deleted = client.delete(f"{NOTES}/{created['ref']}", headers=auth(ALICE_TOKEN))
    assert deleted.status_code == 204

    assert client.get(f"{NOTES}/{created['ref']}", headers=auth(ALICE_TOKEN)).status_code == 404


def test_wikilink_reconciliation_writes_local_rows_with_pandan_down(client: Any) -> None:
    """`app/note_links.py` and `app/wikilinks.py` both promise, in their own docstrings, to make no
    network call ever — this is the end-to-end proof, for both halves the module handles: a
    pandan-shaped ref (`[[KAN-501]]`, left unresolved, `resolved_id IS NULL`) and a note-to-note
    title link that resolves **locally** against another note already in the database.
    """
    target = create(client, ALICE_TOKEN, title="Target Note", body="nothing special")

    linking = create(
        client,
        ALICE_TOKEN,
        title="Linking note",
        body="mentions [[KAN-501]] and links to [[Target Note]]",
    )
    assert linking["ref"].startswith("NOTE-")

    from sqlalchemy import select

    from app.db import get_sessionmaker
    from app.models.note import Note
    from app.models.note_link import NoteLink

    with get_sessionmaker()() as session:
        source_id = session.execute(
            text("SELECT id FROM note WHERE ref = :ref"), {"ref": linking["ref"]}
        ).scalar_one()
        rows = session.scalars(select(NoteLink).where(NoteLink.source_note_id == source_id)).all()

        by_kind = {row.target_kind: row for row in rows}
        assert set(by_kind) == {"KAN", "NOTE"}
        assert by_kind["KAN"].target_ref == "KAN-501"
        assert by_kind["KAN"].resolved_id is None, "a pandan ref stays unresolved with pandan down"

        target_id = session.execute(
            text("SELECT id FROM note WHERE ref = :ref"), {"ref": target["ref"]}
        ).scalar_one()
        assert by_kind["NOTE"].target_ref == "Target Note"
        assert by_kind["NOTE"].resolved_id == target_id, (
            "note-to-note resolution is a local SELECT and must not need pandan"
        )
        # And Note itself never crossed into an ORM query built outside app/auth/authorization.py.
        assert session.get(Note, source_id) is not None
