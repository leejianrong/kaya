"""Workspace access over real HTTP, real Postgres, real `kaya_pat_` bearers (ADR 0017, KAY-174).

Three accounts and one workspace: **alice** is its `owner`, **bob** an `editor`, **carol** a
`viewer`, and **dave** is in no workspace. Every route that takes a note is exercised at the level
it demands, and the container rules (links, folders, the list) are checked from both sides.

Workspaces and memberships are seeded straight into the database: the routes that manage them are
KAY-175's. What is under test here is only what a *note* does with one.

**No `import app.*` at module top** (see `tests/integration/conftest.py`).
"""

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

BACKEND_ROOT = Path(__file__).resolve().parents[2]

NOTES = "/api/v1/notes"
ALICE = uuid.UUID("a1111111-1111-4111-8111-111111111111")
BOB = uuid.UUID("b2222222-2222-4222-8222-222222222222")
CAROL = uuid.UUID("c3333333-3333-4333-8333-333333333333")
DAVE = uuid.UUID("d4444444-4444-4444-8444-444444444444")
PLATFORM = 501
DESIGN = 502


def _alembic_config() -> Any:
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


def _mint(account_id: uuid.UUID, scope: str = "write") -> str:
    from app.config import get_settings
    from app.db import get_sessionmaker
    from app.identity.pat import PersonalAccessToken, generate_token

    raw, prefix, token_hash = generate_token(get_settings().kaya_auth_secret)
    with get_sessionmaker()() as session:
        session.add(
            PersonalAccessToken(
                user_id=account_id,
                name="t",
                token_hash=token_hash,
                token_prefix=prefix,
                scope=scope,
            )
        )
        session.commit()
    return raw


@pytest.fixture
def world(database_url: str) -> Iterator[dict[str, Any]]:
    from alembic import command
    from fastapi.testclient import TestClient

    from app.db import get_sessionmaker
    from app.main import app
    from tests.integration.auth_helpers import seed_kaya_account

    command.upgrade(_alembic_config(), "head")

    def empty() -> None:
        with get_sessionmaker()() as session:
            session.execute(
                text(
                    "TRUNCATE TABLE note_link, note, workspace, personal_access_token, "
                    "kaya_account CASCADE"
                )
            )
            session.commit()

    empty()
    with get_sessionmaker()() as session:
        for account, name in ((ALICE, "alice"), (BOB, "bob"), (CAROL, "carol"), (DAVE, "dave")):
            seed_kaya_account(session, id=account, email=f"{name}@example.com")
        for workspace in (PLATFORM, DESIGN):
            session.execute(
                text("INSERT INTO workspace (id, name) VALUES (:i, 'w')"), {"i": workspace}
            )
        for account, role in ((ALICE, "owner"), (BOB, "editor"), (CAROL, "viewer")):
            session.execute(
                text(
                    "INSERT INTO workspace_member (workspace_id, user_id, role) "
                    "VALUES (:w, :u, :r)"
                ),
                {"w": PLATFORM, "u": account, "r": role},
            )
        session.commit()

    people = (("alice", ALICE), ("bob", BOB), ("carol", CAROL), ("dave", DAVE))
    tokens = {name: _mint(account) for name, account in people}
    with TestClient(app) as client:
        yield {"client": client, "tokens": tokens}
    empty()


def auth(world: dict[str, Any], who: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {world['tokens'][who]}"}


def create(world: dict[str, Any], who: str, title: str, **extra: Any) -> Any:
    return world["client"].post(NOTES, json={"title": title, **extra}, headers=auth(world, who))


def shared_note(world: dict[str, Any], title: str = "plan", **extra: Any) -> str:
    """A note alice wrote in the Platform workspace; returns its ref."""
    made = create(world, "alice", title, workspace_id=PLATFORM, **extra)
    assert made.status_code == 201, made.text
    return made.json()["ref"]


# --- creating -----------------------------------------------------------------------------------


def test_an_owner_and_an_editor_can_create_in_the_workspace(world: dict[str, Any]) -> None:
    for who in ("alice", "bob"):
        made = create(world, who, f"{who}'s note", workspace_id=PLATFORM)
        assert made.status_code == 201, made.text
        assert made.json()["workspace_id"] == PLATFORM


@pytest.mark.parametrize("who", ["carol", "dave"])
def test_a_viewer_and_a_stranger_cannot_create_in_the_workspace(
    world: dict[str, Any], who: str
) -> None:
    refused = create(world, who, "nope", workspace_id=PLATFORM)

    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "workspace_forbidden"


def test_a_workspace_that_does_not_exist_is_the_same_403_as_one_you_are_not_in(
    world: dict[str, Any],
) -> None:
    """Not a way to probe which workspace ids exist."""
    missing = create(world, "alice", "x", workspace_id=999_999)
    not_member = create(world, "alice", "x", workspace_id=DESIGN)

    assert missing.status_code == not_member.status_code == 403
    assert missing.json() == not_member.json()


def test_a_note_without_a_workspace_is_personal(world: dict[str, Any]) -> None:
    made = create(world, "alice", "mine")

    assert made.json()["workspace_id"] is None


# --- reading ------------------------------------------------------------------------------------


@pytest.mark.parametrize("who", ["alice", "bob", "carol"])
def test_every_member_reads_a_workspace_note_whoever_wrote_it(
    world: dict[str, Any], who: str
) -> None:
    ref = shared_note(world)

    response = world["client"].get(f"{NOTES}/{ref}", headers=auth(world, who))

    assert response.status_code == 200
    assert response.json()["workspace_id"] == PLATFORM


def test_a_stranger_is_refused_with_a_403_not_a_404(world: dict[str, Any]) -> None:
    ref = shared_note(world)

    response = world["client"].get(f"{NOTES}/{ref}", headers=auth(world, "dave"))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "note_forbidden"


def test_the_list_holds_personal_and_workspace_notes_for_a_member_only(
    world: dict[str, Any],
) -> None:
    shared_note(world, "shared")
    create(world, "bob", "bob personal")
    create(world, "alice", "alice personal")

    def titles(who: str) -> list[str]:
        listed = world["client"].get(NOTES, headers=auth(world, who))
        return sorted(note["title"] for note in listed.json()["notes"])

    assert titles("alice") == ["alice personal", "shared"]
    assert titles("bob") == ["bob personal", "shared"]
    assert titles("carol") == ["shared"]
    assert titles("dave") == []


def test_search_finds_a_workspace_note_for_members_and_not_for_a_stranger(
    world: dict[str, Any],
) -> None:
    shared_note(world, "quarterly roadmap")

    def found(who: str) -> int:
        response = world["client"].get(f"{NOTES}?q=roadmap", headers=auth(world, who))
        return len(response.json()["notes"])

    assert found("carol") == 1
    assert found("dave") == 0


# --- writing ------------------------------------------------------------------------------------


def test_an_editor_can_edit_and_delete_a_note_somebody_else_wrote(world: dict[str, Any]) -> None:
    ref = shared_note(world)

    edited = world["client"].patch(
        f"{NOTES}/{ref}", json={"body": "edited by bob"}, headers=auth(world, "bob")
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["body"] == "edited by bob"

    deleted = world["client"].delete(f"{NOTES}/{ref}", headers=auth(world, "bob"))
    assert deleted.status_code == 204


def test_a_viewer_can_read_but_every_write_is_refused(world: dict[str, Any]) -> None:
    ref = shared_note(world)
    client = world["client"]

    patch = client.patch(f"{NOTES}/{ref}", json={"body": "x"}, headers=auth(world, "carol"))
    delete = client.delete(f"{NOTES}/{ref}", headers=auth(world, "carol"))

    for response in (patch, delete):
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "note_forbidden"
    assert client.get(f"{NOTES}/{ref}", headers=auth(world, "alice")).json()["body"] != "x"


def test_a_viewer_can_still_use_every_read_route(world: dict[str, Any]) -> None:
    ref = shared_note(world)
    client = world["client"]

    for suffix in ("", "/versions", "/links", "/backlinks", "/format-check"):
        response = client.get(f"{NOTES}/{ref}{suffix}", headers=auth(world, "carol"))
        assert response.status_code == 200, f"{suffix}: {response.text}"


def test_a_read_scope_token_still_cannot_write_even_as_a_workspace_owner(
    world: dict[str, Any],
) -> None:
    """The token scope and the workspace role are two independent ceilings; the lower one wins."""
    ref = shared_note(world)
    read_only = _mint(ALICE, scope="read")

    response = world["client"].patch(
        f"{NOTES}/{ref}", json={"body": "x"}, headers={"Authorization": f"Bearer {read_only}"}
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "insufficient_scope"


def test_losing_your_membership_takes_the_notes_you_wrote_with_it(world: dict[str, Any]) -> None:
    from app.db import get_sessionmaker

    ref = shared_note(world, "written by alice")
    with get_sessionmaker()() as session:
        session.execute(text("DELETE FROM workspace_member WHERE user_id = :u"), {"u": ALICE})
        session.commit()

    gone = world["client"].get(f"{NOTES}/{ref}", headers=auth(world, "alice"))

    assert gone.status_code == 403, "authorship grants nothing inside a workspace"
    still_there = world["client"].get(f"{NOTES}/{ref}", headers=auth(world, "bob"))
    assert still_there.status_code == 200


def test_a_workspace_with_notes_cannot_be_deleted(world: dict[str, Any]) -> None:
    from sqlalchemy.exc import IntegrityError

    from app.db import get_sessionmaker

    shared_note(world)
    with get_sessionmaker()() as session, pytest.raises(IntegrityError):
        session.execute(text("DELETE FROM workspace WHERE id = :i"), {"i": PLATFORM})


# --- containers: links, history, folders ---------------------------------------------------------


def test_a_link_resolves_inside_a_workspace_and_never_across_containers(
    world: dict[str, Any],
) -> None:
    client = world["client"]
    create(world, "alice", "Glossary")  # alice's personal note, same title
    target = create(world, "bob", "Glossary", workspace_id=PLATFORM).json()["ref"]
    source = shared_note(world, "uses it", body="see [[Glossary]]")

    links = client.get(f"{NOTES}/{source}/links", headers=auth(world, "carol")).json()["links"]

    assert [link["resolved_ref"] for link in links] == [target], (
        "the link resolves to the workspace's Glossary, not alice's personal one"
    )


def test_a_personal_note_does_not_resolve_a_title_that_only_exists_in_a_workspace(
    world: dict[str, Any],
) -> None:
    client = world["client"]
    create(world, "alice", "Roadmap", workspace_id=PLATFORM)
    source = create(world, "alice", "personal", body="see [[Roadmap]]").json()["ref"]

    links = client.get(f"{NOTES}/{source}/links", headers=auth(world, "alice")).json()["links"]

    assert links[0]["resolved_ref"] is None, "resolving across containers would reveal a title"


def test_the_graph_holds_only_notes_the_caller_can_read(world: dict[str, Any]) -> None:
    shared_note(world, "workspace note")
    create(world, "alice", "alice personal")

    def nodes(who: str) -> list[str]:
        response = world["client"].get("/api/v1/graph", headers=auth(world, who))
        return sorted(node["title"] for node in response.json()["nodes"])

    assert nodes("carol") == ["workspace note"]
    assert nodes("alice") == ["alice personal", "workspace note"]
    assert nodes("dave") == []


def test_move_folder_is_scoped_to_one_container(world: dict[str, Any]) -> None:
    client = world["client"]
    create(world, "alice", "p", path="docs/a.md")
    create(world, "alice", "w", path="docs/b.md", workspace_id=PLATFORM)

    moved = client.post(
        f"{NOTES}/move-folder",
        json={"from": "docs", "to": "guides", "workspace_id": PLATFORM},
        headers=auth(world, "bob"),
    )
    assert moved.json() == {"moved": 1}

    listed = client.get(NOTES, headers=auth(world, "alice")).json()["notes"]
    paths = {n["title"]: n["path"] for n in listed}
    assert paths == {"p": "docs/a.md", "w": "guides/b.md"}, "personal 'docs' is untouched"


def test_move_folder_without_a_workspace_moves_only_personal_notes(world: dict[str, Any]) -> None:
    client = world["client"]
    create(world, "alice", "p", path="docs/a.md")
    create(world, "alice", "w", path="docs/b.md", workspace_id=PLATFORM)

    moved = client.post(
        f"{NOTES}/move-folder", json={"from": "docs", "to": "guides"}, headers=auth(world, "alice")
    )

    assert moved.json() == {"moved": 1}
    listed = client.get(NOTES, headers=auth(world, "alice")).json()["notes"]
    paths = {n["title"]: n["path"] for n in listed}
    assert paths == {"p": "guides/a.md", "w": "docs/b.md"}


@pytest.mark.parametrize("who", ["carol", "dave"])
def test_a_viewer_or_stranger_cannot_move_a_workspace_folder(
    world: dict[str, Any], who: str
) -> None:
    create(world, "alice", "w", path="docs/b.md", workspace_id=PLATFORM)

    refused = world["client"].post(
        f"{NOTES}/move-folder",
        json={"from": "docs", "to": "guides", "workspace_id": PLATFORM},
        headers=auth(world, who),
    )

    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "workspace_forbidden"
    listed = world["client"].get(NOTES, headers=auth(world, "alice")).json()["notes"]
    assert [n["path"] for n in listed] == ["docs/b.md"]
