"""What kaya actually sends pandan, against a fake pandan that serves only pandan's *current* paths
(KAN-1804).

Two suspected breakages from the repo audit, reproduced over real HTTP shapes (`httpx.MockTransport`
under the real upstream classes, real Postgres, real `kaya_pat_` tokens through the real
`get_principal`):

1. `[[KAN-n]]` resolution must send the caller's **linked** pandan PAT, never the kaya bearer, and
   must send nothing at all for a caller who never linked an account.
2. Team-default access (ADR 0011) must ask `GET /api/v1/workspaces` (pandan ADR 0023 renamed
   `/teams`; the fake answers 404 to the old path) with the caller's linked pandan PAT, and a
   non-member, an unlinked caller, or an erroring pandan all land on the same refusal, never a 500.

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
BOB_PANDAN_PAT = "bobs-linked-pandan-pat"
WORKSPACE_ID = 501


def _alembic_config() -> Any:
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


class FakePandan:
    """Pandan as it is today: `/api/v1/cards`, `/api/v1/epics`, `/api/v1/workspaces`, and nothing
    else (anything else, `/api/v1/teams` included, is the 404 the real service gives). Answers only
    for `pandan_pat`s it was told about; any other bearer is a 401."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []
        self.cards: dict[str, str] = {}
        self.workspaces: dict[str, list[int]] = {}
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
            if pat not in self.workspaces and pat not in {"alice-linked"}:
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
        if request.url.path == "/api/v1/workspaces":
            if pat not in self.workspaces:
                return httpx.Response(401, json={"detail": "no"})
            rows = [
                {"id": wid, "name": "w", "role": "viewer", "created_at": "x", "updated_at": "x"}
                for wid in self.workspaces[pat]
            ]
            return httpx.Response(200, json=rows)
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

    from app.auth.dependencies import get_team_access_resolver
    from app.auth.single_flight import SingleFlight
    from app.auth.team_cache import TeamMembershipCache
    from app.auth.team_resolver import TeamAccessResolver
    from app.auth.team_upstream import PandanTeamUpstream
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
                    "TRUNCATE TABLE note_link, note, team, personal_access_token, "
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
    team_upstream = PandanTeamUpstream(base, timeout=2.0, client=pandan_client())
    card_cache = CardEpicCache(ttl=300.0)
    team_cache = TeamMembershipCache(positive_ttl=60.0, negative_ttl=10.0)
    team_single_flight = SingleFlight()

    app.dependency_overrides[get_card_epic_resolver] = lambda: CardEpicResolver(
        card_upstream,
        card_cache,
        max_selectors_per_request=50,
        max_upstream_requests=4,
        total_deadline_seconds=5.0,
    )
    app.dependency_overrides[get_team_access_resolver] = lambda: TeamAccessResolver(
        upstream=team_upstream, cache=team_cache, single_flight=team_single_flight
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


# --- 2. team-default access --------------------------------------------------------------------


@pytest.fixture
def alices_team_note(client: Any) -> str:
    from app.db import get_sessionmaker

    with get_sessionmaker()() as session:
        session.execute(text("INSERT INTO team (id) VALUES (:id)"), {"id": WORKSPACE_ID})
        ref = session.execute(
            text(
                "INSERT INTO note (owner_id, title, team_id) "
                "VALUES (:owner, 'alice team note', :team) RETURNING ref"
            ),
            {"owner": ALICE_ID, "team": WORKSPACE_ID},
        ).scalar_one()
        session.commit()
    return ref


def test_a_workspace_member_reads_a_team_shared_note_via_the_workspaces_path(
    client: Any, pandan: FakePandan, alices_team_note: str
) -> None:
    bob = mint(BOB_ID)
    link_pandan(BOB_ID, BOB_PANDAN_PAT)
    pandan.workspaces[BOB_PANDAN_PAT] = [WORKSPACE_ID]

    response = client.get(f"{NOTES}/{alices_team_note}", headers=bearer(bob))

    assert response.status_code == 200, response.text
    assert pandan.paths() == ["/api/v1/workspaces"]
    assert pandan.authorizations() == {f"Bearer {BOB_PANDAN_PAT}"}


def test_a_workspace_member_sees_the_team_note_in_their_list(
    client: Any, pandan: FakePandan, alices_team_note: str
) -> None:
    bob = mint(BOB_ID)
    link_pandan(BOB_ID, BOB_PANDAN_PAT)
    pandan.workspaces[BOB_PANDAN_PAT] = [WORKSPACE_ID]

    response = client.get(NOTES, headers=bearer(bob))

    assert [n["ref"] for n in response.json()["notes"]] == [alices_team_note]
    assert pandan.authorizations() == {f"Bearer {BOB_PANDAN_PAT}"}


def test_a_non_member_is_403_and_the_kaya_bearer_never_reaches_pandan(
    client: Any, pandan: FakePandan, alices_team_note: str
) -> None:
    bob = mint(BOB_ID)
    link_pandan(BOB_ID, BOB_PANDAN_PAT)
    pandan.workspaces[BOB_PANDAN_PAT] = [999]

    response = client.get(f"{NOTES}/{alices_team_note}", headers=bearer(bob))

    assert response.status_code == 403
    assert not any("kaya_pat_" in a for a in pandan.authorizations())


def test_a_caller_with_no_linked_account_is_403_without_calling_pandan(
    client: Any, pandan: FakePandan, alices_team_note: str
) -> None:
    response = client.get(f"{NOTES}/{alices_team_note}", headers=bearer(mint(BOB_ID)))

    assert response.status_code == 403
    assert pandan.requests == []


@pytest.mark.parametrize("failure", ["down", 500, 404, 401])
def test_pandan_failing_to_answer_is_a_403_never_a_500(
    client: Any, pandan: FakePandan, alices_team_note: str, failure: Any
) -> None:
    bob = mint(BOB_ID)
    link_pandan(BOB_ID, BOB_PANDAN_PAT)
    pandan.workspaces[BOB_PANDAN_PAT] = [WORKSPACE_ID]
    if failure == "down":
        pandan.down = True
    else:
        pandan.error_status = failure

    response = client.get(f"{NOTES}/{alices_team_note}", headers=bearer(bob))

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "note_forbidden"


def test_the_owner_never_triggers_a_team_check(
    client: Any, pandan: FakePandan, alices_team_note: str
) -> None:
    alice = mint(ALICE_ID)
    link_pandan(ALICE_ID, "alice-linked")

    response = client.get(f"{NOTES}/{alices_team_note}", headers=bearer(alice))

    assert response.status_code == 200
    assert pandan.requests == []
