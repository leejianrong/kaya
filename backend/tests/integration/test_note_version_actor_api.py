"""Who cut each ``note_version``, against a real Postgres — KAY-138 (ADR 0015 precondition 1).

Real tokens and a real cookie session drive the real ``get_principal`` (no override), so what is
asserted is what a caller on each channel would leave behind. The hosted ``/mcp`` path is not driven
here: its tools call the REST API with the caller's own bearer over HTTP, which is the token branch
below byte for byte (a PAT is a PAT), and `test_mcp_host_api.py` already covers the transport.

**No ``import app.*`` at module top** (see ``tests/integration/conftest.py``).
"""

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

BACKEND_ROOT = Path(__file__).resolve().parents[2]
NOTES = "/api/v1/notes"
ALICE = uuid.UUID("44444444-4444-4444-8444-444444444444")


def _alembic_config() -> Any:
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


def mint(name: str, scope: str = "write") -> tuple[str, str]:
    from app.config import get_settings
    from app.db import get_sessionmaker
    from app.identity.pat import PersonalAccessToken, generate_token

    raw, prefix, token_hash = generate_token(get_settings().kaya_auth_secret)
    with get_sessionmaker()() as session:
        session.add(
            PersonalAccessToken(
                user_id=ALICE, name=name, token_hash=token_hash, token_prefix=prefix, scope=scope
            )
        )
        session.commit()
    return raw, prefix


@pytest.fixture
def client(database_url: str) -> Iterator[Any]:
    from alembic import command
    from fastapi.testclient import TestClient

    from app.db import get_sessionmaker
    from app.main import app
    from tests.integration.auth_helpers import seed_kaya_account

    command.upgrade(_alembic_config(), "head")

    def empty() -> None:
        with get_sessionmaker()() as session:
            session.execute(
                text("TRUNCATE TABLE note, personal_access_token, kaya_account CASCADE")
            )
            session.commit()

    empty()
    with get_sessionmaker()() as session:
        seed_kaya_account(session, id=ALICE, email="alice@example.com")
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        empty()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def versions(client: Any, ref: str, token: str) -> list[dict[str, Any]]:
    response = client.get(f"{NOTES}/{ref}/versions", headers=bearer(token))
    assert response.status_code == 200, response.text
    return response.json()["versions"]


def test_a_pat_write_records_the_token_and_a_cookie_write_records_a_session(client: Any) -> None:
    from app.db import get_sessionmaker
    from app.identity.backend import COOKIE_NAME
    from app.identity.models import KayaSession

    raw, prefix = mint("ci-bot")
    created = client.post(NOTES, json={"title": "t", "body": "one"}, headers=bearer(raw))
    ref = created.json()["ref"]

    with get_sessionmaker()() as session:
        session.add(KayaSession(token="alices-browser", user_id=ALICE))
        session.commit()
    patched = client.patch(
        f"{NOTES}/{ref}", json={"body": "two"}, cookies={COOKIE_NAME: "alices-browser"}
    )
    assert patched.status_code == 200, patched.text

    newest, oldest = versions(client, ref, raw)
    assert oldest["body"] == "one"
    assert oldest["actor"]["channel"] == "token"
    assert oldest["actor"]["email"] == "alice@example.com"
    assert oldest["actor"]["user_id"] == str(ALICE)
    assert oldest["actor"]["token"]["prefix"] == prefix
    assert oldest["actor"]["token"]["name"] == "ci-bot"
    assert oldest["actor"]["token"]["kind"] is None
    assert newest["body"] == "two"
    assert newest["actor"]["channel"] == "session"
    assert newest["actor"]["token"] is None
    assert newest["actor"]["user_id"] == str(ALICE)
    assert newest["actor"]["is_you"] is True


def test_a_restore_is_attributed_to_whoever_restored(client: Any) -> None:
    first, _ = mint("first")
    second, second_prefix = mint("second")
    ref = client.post(NOTES, json={"title": "t", "body": "v1"}, headers=bearer(first)).json()["ref"]
    client.patch(f"{NOTES}/{ref}", json={"body": "v2"}, headers=bearer(first))
    restored = client.patch(f"{NOTES}/{ref}", json={"body": "v1"}, headers=bearer(second))
    assert restored.status_code == 200

    newest = versions(client, ref, first)[0]
    assert newest["body"] == "v1"
    assert newest["actor"]["token"]["name"] == "second"
    assert newest["actor"]["token"]["prefix"] == second_prefix


def test_a_title_only_edit_cuts_no_version(client: Any) -> None:
    raw, _ = mint("bot")
    ref = client.post(NOTES, json={"title": "t"}, headers=bearer(raw)).json()["ref"]
    client.patch(f"{NOTES}/{ref}", json={"title": "u"}, headers=bearer(raw))
    assert len(versions(client, ref, raw)) == 1


def test_revoking_the_token_keeps_the_record_of_what_it_did(client: Any) -> None:
    from app.db import get_sessionmaker

    raw, prefix = mint("short-lived")
    keeper, _ = mint("keeper")
    ref = client.post(NOTES, json={"title": "t", "body": "x"}, headers=bearer(raw)).json()["ref"]
    with get_sessionmaker()() as session:
        session.execute(text("DELETE FROM personal_access_token WHERE name = 'short-lived'"))
        session.commit()

    (only,) = versions(client, ref, keeper)
    assert only["actor"]["token"]["name"] == "short-lived"
    assert only["actor"]["token"]["prefix"] == prefix


def test_a_version_cut_before_tracking_has_a_null_actor(client: Any) -> None:
    from app.db import get_sessionmaker

    raw, _ = mint("bot")
    ref = client.post(NOTES, json={"title": "t", "body": "x"}, headers=bearer(raw)).json()["ref"]
    with get_sessionmaker()() as session:
        session.execute(
            text(
                "UPDATE note_version SET actor_user_id = NULL, actor_channel = NULL, "
                "actor_token_id = NULL, actor_token_prefix = NULL, actor_token_name = NULL"
            )
        )
        session.commit()
    (only,) = versions(client, ref, raw)
    assert only["actor"] is None
