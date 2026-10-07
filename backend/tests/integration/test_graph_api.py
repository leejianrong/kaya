"""``/api/v1/graph`` end to end: real routes, real Postgres, real HTTP — KAN-1050.

The unit layer (`tests/unit/test_graph_queries.py`) proves what the SQL *says* and what the pure
translation *decides*. This file proves the property that needs rows: two different callers' notes
never mix in one graph, and the wire response is refs, not the internal ids a real database
actually stores.

No pandan fake needed — unlike `test_note_links_api.py`'s sibling, `/graph` never resolves a
`KAN`/`EPIC` reference, so only identity has to be faked.

**No `import app.*` at module top** — see the package docstring, and pandan's PR #17 trap.
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
BOB_TOKEN = "a-different-caller-supplied-string"
ALICE_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
BOB_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")

NOTES = "/api/v1/notes"
GRAPH = "/api/v1/graph"


def _alembic_config() -> Any:
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


@pytest.fixture
def client(database_url: str) -> Iterator[Any]:
    """The real app, with only identity faked (`override_get_principal`, KAN-1740) — since this
    route reaches no upstream of its own."""
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
        seed_kaya_account(session, id=BOB_ID, email="bob@example.com")
    known_principals = {
        ALICE_TOKEN: Principal(id=ALICE_ID, email="alice@example.com"),
        BOB_TOKEN: Principal(id=BOB_ID, email="bob@example.com"),
    }
    override_get_principal(app, known_principals)
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        empty()


def auth(token: str = ALICE_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create(client: Any, token: str, **fields: str) -> dict[str, Any]:
    fields.setdefault("title", "a note")
    response = client.post(NOTES, json=fields, headers=auth(token))
    assert response.status_code == 201, response.text
    return response.json()


def test_a_caller_with_no_notes_gets_an_empty_graph(client: Any) -> None:
    response = client.get(GRAPH, headers=auth(ALICE_TOKEN))

    assert response.status_code == 200
    assert response.json() == {"nodes": [], "edges": []}


def test_no_bearer_at_all_is_a_401(client: Any) -> None:
    response = client.get(GRAPH)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_a_bearer_kaya_does_not_recognise_is_also_a_401(client: Any) -> None:
    response = client.get(GRAPH, headers=auth("a-token-nobody-issued"))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_a_note_with_no_links_is_a_node_with_no_edges(client: Any) -> None:
    solo = create(client, ALICE_TOKEN, title="Solo Note")

    response = client.get(GRAPH, headers=auth(ALICE_TOKEN))

    body = response.json()
    assert body["edges"] == []
    assert [node["ref"] for node in body["nodes"]] == [solo["ref"]]


def test_a_resolved_note_to_note_link_is_an_edge_of_refs_not_ids(client: Any) -> None:
    """The card's headline wire claim: the response names `NOTE-n`, never the integer ids a real
    database is actually holding underneath."""
    target = create(client, ALICE_TOKEN, title="Reading List")
    source = create(client, ALICE_TOKEN, title="Source", body="see [[Reading List]] for more")

    body = client.get(GRAPH, headers=auth(ALICE_TOKEN)).json()

    assert {node["ref"] for node in body["nodes"]} == {source["ref"], target["ref"]}
    assert body["edges"] == [{"source": source["ref"], "target": target["ref"]}]
    # Exactly two keys, both refs — never `note_link.source_note_id`/`resolved_id`'s raw integers.
    [edge] = body["edges"]
    assert set(edge) == {"source", "target"}
    assert all(isinstance(value, str) and value.startswith("NOTE-") for value in edge.values())


def test_an_unresolved_note_title_link_is_no_edge_at_all(client: Any) -> None:
    """CLAUDE.md: an edge with `resolved_id IS NULL` is a link to a title, not yet a note — this
    graph draws no line for one."""
    source = create(client, ALICE_TOKEN, title="Source", body="see [[Nothing Written Yet]]")

    body = client.get(GRAPH, headers=auth(ALICE_TOKEN)).json()

    assert body["edges"] == []
    assert [node["ref"] for node in body["nodes"]] == [source["ref"]]


def test_a_pandan_wikilink_is_not_an_edge_in_this_graph(client: Any) -> None:
    """Out of scope by the card's own framing: this is the note graph, not a pandan-ticket graph."""
    source = create(client, ALICE_TOKEN, title="Source", body="blocked by [[KAN-501]]")

    body = client.get(GRAPH, headers=auth(ALICE_TOKEN)).json()

    assert body["edges"] == []
    assert [node["ref"] for node in body["nodes"]] == [source["ref"]]


def test_two_callers_notes_and_edges_never_mix_in_one_graph(client: Any) -> None:
    """The property the unit layer's statement probe cannot prove on its own: that the clause
    actually keeps rows apart once Postgres has real data from two owners."""
    a_target = create(client, ALICE_TOKEN, title="Alice Target")
    create(client, ALICE_TOKEN, title="Alice Source", body="see [[Alice Target]]")

    b_target = create(client, BOB_TOKEN, title="Bob Target")
    create(client, BOB_TOKEN, title="Bob Source", body="see [[Bob Target]]")

    alice_graph = client.get(GRAPH, headers=auth(ALICE_TOKEN)).json()
    bob_graph = client.get(GRAPH, headers=auth(BOB_TOKEN)).json()

    alice_refs = {node["ref"] for node in alice_graph["nodes"]}
    bob_refs = {node["ref"] for node in bob_graph["nodes"]}

    assert len(alice_refs) == 2
    assert len(bob_refs) == 2
    assert bob_refs.isdisjoint(alice_refs)
    assert len(alice_graph["edges"]) == 1
    assert len(bob_graph["edges"]) == 1
    assert a_target["ref"] not in bob_refs
    assert b_target["ref"] not in alice_refs
