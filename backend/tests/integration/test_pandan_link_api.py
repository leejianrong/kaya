"""``/api/v1/pandan-link`` against a real Postgres (ADR 0012's amendment, KAN-1741).

Real encryption (`app/identity/pandan_link.py`), a real `kaya_account` row (the FK), and
`get_principal` faked directly the same way every other integration test in this package does
(`tests/integration/auth_helpers.py`'s own module docstring). `get_pandan_link_verifier` is faked at
its own, unrelated seam — this file's job is the store/read/replace/delete round trip and the two
error shapes (`422` rejected, `503` unreachable), not pandan's real HTTP contract
(`test_pandan_link_verify.py` covers that against `httpx.MockTransport`).

**No ``import app.*`` at module top** — see the package docstring, and pandan's PR #17 trap.
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

PANDAN_LINK = "/api/v1/pandan-link"
A_PANDAN_TOKEN = "pandan_pat_FAKEa-real-looking-secret"


def _alembic_config() -> Any:
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


class FakeVerifier:
    """A `PandanLinkVerifier`, answering a canned decision and recording every token it saw."""

    def __init__(self) -> None:
        self.accepted = True
        self.unreachable = False
        self.calls: list[str] = []

    def verify(self, token: str) -> bool:
        from app.integrations.pandan_link import PandanLinkUnreachable

        self.calls.append(token)
        if self.unreachable:
            raise PandanLinkUnreachable("https://pandan.invalid/api/v1/me is unreachable")
        return self.accepted


@pytest.fixture
def verifier() -> FakeVerifier:
    return FakeVerifier()


@pytest.fixture
def known_principals() -> dict[str, Any]:
    return {}


@pytest.fixture
def client(
    database_url: str, known_principals: dict[str, Any], verifier: FakeVerifier
) -> Iterator[Any]:
    from alembic import command
    from fastapi.testclient import TestClient

    from app.db import get_sessionmaker
    from app.integrations.dependencies import get_pandan_link_verifier
    from app.main import app

    command.upgrade(_alembic_config(), "head")

    def empty() -> None:
        with get_sessionmaker()() as session:
            session.execute(text("TRUNCATE TABLE note, kaya_account CASCADE"))
            session.commit()

    empty()
    with get_sessionmaker()() as session:
        seed_kaya_account(session, id=ALICE_ID, email="alice@example.com")

    override_get_principal(app, known_principals)
    app.dependency_overrides[get_pandan_link_verifier] = lambda: verifier
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        del app.dependency_overrides[get_pandan_link_verifier]
        app.dependency_overrides.clear()
        empty()


@pytest.fixture
def alice(client: Any, known_principals: dict[str, Any]) -> Any:
    """`client: Any` forces `client`'s own truncation to complete first — see
    `test_board_embed_api.py`'s identical fixture for why."""
    from app.auth.principal import Principal

    known_principals[ALICE_TOKEN] = Principal(id=ALICE_ID, email="alice@example.com")
    return ALICE_TOKEN


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def error(response: Any) -> dict[str, Any]:
    return response.json()["error"]


# --- status, unauthenticated and never-connected ------------------------------------------------


def test_status_before_connecting_is_not_connected(client: Any, alice: str) -> None:
    response = client.get(PANDAN_LINK, headers=bearer(alice))

    assert response.status_code == 200
    assert response.json() == {"connected": False}


def test_no_bearer_is_a_401(client: Any) -> None:
    response = client.get(PANDAN_LINK)

    assert response.status_code == 401
    assert error(response)["code"] == "authentication_required"


# --- connecting -----------------------------------------------------------------------------------


def test_connecting_a_good_token_verifies_it_first(
    client: Any, alice: str, verifier: FakeVerifier
) -> None:
    response = client.post(PANDAN_LINK, json={"token": A_PANDAN_TOKEN}, headers=bearer(alice))

    assert response.status_code == 200
    assert response.json() == {"connected": True}
    assert verifier.calls == [A_PANDAN_TOKEN]


def test_a_connected_link_is_reflected_in_status(client: Any, alice: str) -> None:
    client.post(PANDAN_LINK, json={"token": A_PANDAN_TOKEN}, headers=bearer(alice))

    response = client.get(PANDAN_LINK, headers=bearer(alice))

    assert response.json() == {"connected": True}


def test_the_stored_token_round_trips_through_the_real_encryption(
    client: Any, alice: str
) -> None:
    """Not just "a row exists" — the exact secret pasted survives encryption at rest, which is the
    property `app/api/embeds.py`'s `linked_pandan_bearer` depends on being true for a real board
    embed render to ever forward the right credential."""
    from app.config import get_settings
    from app.db import get_sessionmaker
    from app.identity.pandan_link import PandanLink, decrypt_token

    client.post(PANDAN_LINK, json={"token": A_PANDAN_TOKEN}, headers=bearer(alice))

    with get_sessionmaker()() as session:
        link = session.query(PandanLink).filter_by(user_id=ALICE_ID).one()
        assert decrypt_token(link.encrypted_token, get_settings().kaya_auth_secret) == (
            A_PANDAN_TOKEN
        )


def test_a_token_pandan_rejects_is_a_422_and_is_never_stored(
    client: Any, alice: str, verifier: FakeVerifier
) -> None:
    verifier.accepted = False

    response = client.post(PANDAN_LINK, json={"token": "a-bad-token"}, headers=bearer(alice))

    assert response.status_code == 422
    assert error(response)["code"] == "invalid_pandan_token"
    assert client.get(PANDAN_LINK, headers=bearer(alice)).json() == {"connected": False}


def test_pandan_being_unreachable_is_a_503_not_a_422(
    client: Any, alice: str, verifier: FakeVerifier
) -> None:
    """Q9's rule, mirrored here: a wrong guess about a credential (rejecting a token kaya never
    actually got to check) is worse than an honest "couldn't check"."""
    verifier.unreachable = True

    response = client.post(PANDAN_LINK, json={"token": A_PANDAN_TOKEN}, headers=bearer(alice))

    assert response.status_code == 503
    assert error(response)["code"] == "pandan_unavailable"


def test_reconnecting_replaces_the_stored_token_not_a_second_row(
    client: Any, alice: str
) -> None:
    from app.db import get_sessionmaker
    from app.identity.pandan_link import PandanLink

    client.post(PANDAN_LINK, json={"token": A_PANDAN_TOKEN}, headers=bearer(alice))
    client.post(PANDAN_LINK, json={"token": "pandan_pat_FAKEa-second-token"}, headers=bearer(alice))

    with get_sessionmaker()() as session:
        rows = session.query(PandanLink).filter_by(user_id=ALICE_ID).all()
        assert len(rows) == 1


def test_an_empty_token_is_a_422(client: Any, alice: str) -> None:
    response = client.post(PANDAN_LINK, json={"token": ""}, headers=bearer(alice))

    assert response.status_code == 422


# --- disconnecting ----------------------------------------------------------------------------


def test_disconnecting_a_connected_link(client: Any, alice: str) -> None:
    client.post(PANDAN_LINK, json={"token": A_PANDAN_TOKEN}, headers=bearer(alice))

    response = client.delete(PANDAN_LINK, headers=bearer(alice))

    assert response.status_code == 200
    assert response.json() == {"connected": False}
    assert client.get(PANDAN_LINK, headers=bearer(alice)).json() == {"connected": False}


def test_disconnecting_when_never_connected_is_not_a_404(client: Any, alice: str) -> None:
    """Idempotent — there is nothing here for a caller to have gotten wrong by asking twice, the
    same posture `app/api/pandan_link.py`'s module docstring states explicitly."""
    response = client.delete(PANDAN_LINK, headers=bearer(alice))

    assert response.status_code == 200
    assert response.json() == {"connected": False}


# --- one caller's link is never another's --------------------------------------------------------


def test_bobs_status_is_unaffected_by_alices_connection(
    client: Any, alice: str, known_principals: dict[str, Any]
) -> None:
    from app.auth.principal import Principal
    from app.db import get_sessionmaker

    bob_id = uuid.UUID("22222222-2222-4222-8222-222222222222")
    with get_sessionmaker()() as session:
        seed_kaya_account(session, id=bob_id, email="bob@example.com")
    bob_token = "bobs-own-kaya-side-bearer"
    known_principals[bob_token] = Principal(id=bob_id, email="bob@example.com")

    client.post(PANDAN_LINK, json={"token": A_PANDAN_TOKEN}, headers=bearer(alice))

    response = client.get(PANDAN_LINK, headers=bearer(bob_token))

    assert response.json() == {"connected": False}


def test_documented_in_the_openapi_schema(client: Any) -> None:
    schema = client.get("/openapi.json").json()

    assert PANDAN_LINK in schema["paths"]
