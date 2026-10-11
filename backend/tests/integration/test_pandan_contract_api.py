"""What kaya actually sends pandan, against a fake pandan that serves only pandan's *current* paths
(KAN-1804).

A suspected breakage from the repo audit, reproduced over real HTTP shapes (`httpx.MockTransport`
under the real upstream classes, real Postgres, real `kaya_pat_` tokens through the real
`get_principal`): `[[KAN-n]]` resolution must send the caller's **linked** pandan PAT, never the
kaya bearer, and must send nothing at all for a caller who never linked an account.

(A second half used to cover team-default access, which asked pandan for the caller's workspaces.
ADR 0017 moved access to kaya's own tables, so kaya no longer asks pandan anything about access.)

The fake records every request's path and `Authorization` header. A `kaya_pat_` string appearing in
that record is the failure this file exists to catch.

**No `import app.*` at module top** (see `tests/integration/conftest.py`).
"""

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import text

BACKEND_ROOT = Path(__file__).resolve().parents[2]

NOTES = "/api/v1/notes"
ALICE_ID = uuid.UUID("44444444-4444-4444-8444-444444444444")
BOB_ID = uuid.UUID("55555555-5555-4555-8555-555555555555")


def _alembic_config() -> Any:
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


class FakePandan:
    """Pandan as it is today: `/api/v1/cards`, `/api/v1/epics`, and nothing else (anything else is
    the 404 the real service gives). Answers only for `pandan_pat`s it was told about; any other
    bearer is a 401."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []
        self.cards: dict[str, str] = {}
        self.down = False
        self.error_status: int | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("pandan is down", request=request)
        authorization = request.headers.get("authorization", "")
        self.requests.append((request.url.path, authorization))
        if self.error_status is not None:
            return httpx.Response(self.error_status, json={"detail": "boom"})
        pat = authorization.removeprefix("Bearer ")
        if request.url.path == "/api/v1/cards":
            if pat not in {"alice-linked"}:
                return httpx.Response(401, json={"detail": "no"})
            wanted = request.url.params.get("refs", "").split(",")
            found = [
                {"id": 1, "ticket_number": ref, "title": self.cards[ref], "column": "todo"}
                for ref in wanted
                if ref in self.cards
            ]
            missing = ",".join(ref for ref in wanted if ref not in self.cards)
            return httpx.Response(200, json=found, headers={"X-Unresolved-Selectors": missing})
        if request.url.path == "/api/v1/epics":
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={"detail": "Not Found"})

    def paths(self) -> list[str]:
        return [path for path, _ in self.requests]

    def authorizations(self) -> set[str]:
        return {authorization for _, authorization in self.requests}


@pytest.fixture
def pandan() -> FakePandan:
    return FakePandan()


@pytest.fixture
def client(database_url: str, pandan: FakePandan) -> Iterator[Any]:
    from alembic import command
    from fastapi.testclient import TestClient

    from app.db import get_sessionmaker
    from app.integrations.card_resolution import (
        CardEpicCache,
        CardEpicResolver,
        PandanCardEpicUpstream,
    )
    from app.integrations.dependencies import get_card_epic_resolver, reset_card_resolution
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
    reset_card_resolution()
    with get_sessionmaker()() as session:
        seed_kaya_account(session, id=ALICE_ID, email="alice@example.com")
        seed_kaya_account(session, id=BOB_ID, email="bob@example.com")

    def pandan_client() -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(pandan.handler), timeout=2.0)

    base = "http://pandan.invalid"
    card_upstream = PandanCardEpicUpstream(base, timeout=2.0, client=pandan_client())
    card_cache = CardEpicCache(ttl=300.0)

    app.dependency_overrides[get_card_epic_resolver] = lambda: CardEpicResolver(
        card_upstream,
        card_cache,
        max_selectors_per_request=50,
        max_upstream_requests=4,
        total_deadline_seconds=5.0,
    )
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        reset_card_resolution()
        empty()


def mint(account_id: uuid.UUID) -> str:
    from app.config import get_settings
    from app.db import get_sessionmaker
    from app.identity.pat import PersonalAccessToken, generate_token

    raw, prefix, token_hash = generate_token(get_settings().kaya_auth_secret)
    assert raw.startswith("kaya_pat_")
    with get_sessionmaker()() as session:
        session.add(
            PersonalAccessToken(
                user_id=account_id, name="t", token_hash=token_hash, token_prefix=prefix
            )
        )
        session.commit()
    return raw


def link_pandan(account_id: uuid.UUID, raw_pandan_pat: str) -> None:
    from app.config import get_settings
    from app.db import get_sessionmaker
    from app.identity.pandan_link import PandanLink, encrypt_token

    with get_sessionmaker()() as session:
        session.add(
            PandanLink(
                user_id=account_id,
                encrypted_token=encrypt_token(raw_pandan_pat, get_settings().kaya_auth_secret),
            )
        )
        session.commit()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def note_with_card_link(client: Any, token: str) -> str:
    response = client.post(
        NOTES, json={"title": "plan", "body": "see [[KAN-7]]"}, headers=bearer(token)
    )
    assert response.status_code == 201, response.text
    return response.json()["ref"]


# --- 1. [[KAN-n]] resolution -------------------------------------------------------------------


def test_card_resolution_sends_the_linked_pandan_pat_and_never_the_kaya_bearer(
    client: Any, pandan: FakePandan
) -> None:
    kaya_token = mint(ALICE_ID)
    link_pandan(ALICE_ID, "alice-linked")
    pandan.cards["KAN-7"] = "Ship it"
    ref = note_with_card_link(client, kaya_token)

    response = client.get(f"{NOTES}/{ref}/links", headers=bearer(kaya_token))

    assert response.status_code == 200, response.text
    assert response.json()["links"][0]["title"] == "Ship it"
    assert pandan.paths() == ["/api/v1/cards"]
    assert pandan.authorizations() == {"Bearer alice-linked"}
    assert not any("kaya_pat_" in a for a in pandan.authorizations())


def test_card_resolution_for_a_caller_with_no_linked_account_never_calls_pandan(
    client: Any, pandan: FakePandan
) -> None:
    kaya_token = mint(ALICE_ID)
    pandan.cards["KAN-7"] = "Ship it"
    ref = note_with_card_link(client, kaya_token)

    response = client.get(f"{NOTES}/{ref}/links", headers=bearer(kaya_token))

    assert response.status_code == 200, response.text
    assert response.json()["links"][0]["title"] is None
    assert pandan.requests == []


def test_card_resolution_with_pandan_down_is_a_200_with_the_link_unresolved(
    client: Any, pandan: FakePandan
) -> None:
    kaya_token = mint(ALICE_ID)
    link_pandan(ALICE_ID, "alice-linked")
    ref = note_with_card_link(client, kaya_token)
    pandan.down = True

    response = client.get(f"{NOTES}/{ref}/links", headers=bearer(kaya_token))

    assert response.status_code == 200, response.text
    assert response.json()["links"][0]["title"] is None
    assert client.get(f"{NOTES}/{ref}", headers=bearer(kaya_token)).status_code == 200
