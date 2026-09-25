"""``app/auth/kaya_principal.py`` against the **real** app, with ``get_principal`` not overridden
at all (ADR 0012, KAN-1740).

Every other file in this package fakes identity resolution deliberately —
`auth_helpers.py`'s own module docstring explains why: `get_principal`'s replacement is a plain
database lookup with no seam worth faking three layers down for a test that is really about note
*authorization*. This file is the one exception, and it exists precisely to cover the gap that
choice leaves: something has to prove the *real* resolution path — a `kaya_pat_…` bearer, a
`kaya_session` cookie, precedence between the two, expiry, an inactive account — actually works
end to end against `/api/v1/notes`, not just that the test double for it behaves.

A real PAT is minted through the real `POST /api/v1/tokens` (gated on `get_current_active_user`,
KAN-1739's own seam — unrelated to `get_principal` and faked the same way
`test_tokens_api.py` fakes it), then used as a bearer against a route this file does **not**
override identity for.

**No ``import app.*`` at module top** — see `tests/integration/conftest.py`'s package docstring.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]

NOTES = "/api/v1/notes"
TOKENS = "/api/v1/tokens"

ALICE_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")


def _alembic_config() -> Any:
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


@pytest.fixture
def client(database_url: str) -> Iterator[Any]:
    """The real app, with **nothing** overridden for `get_principal` — the one thing every other
    integration test file in this package does override. `get_current_active_user` (KAN-1739's own,
    unrelated seam) is faked only so this fixture can mint a real PAT through the real
    `POST /api/v1/tokens`; nothing about note authorization is faked."""
    from alembic import command
    from fastapi.testclient import TestClient

    from app.db import get_sessionmaker
    from app.identity.current_user import get_current_active_user
    from app.identity.models import KayaAccount
    from app.main import app

    command.upgrade(_alembic_config(), "head")

    def empty() -> None:
        with get_sessionmaker()() as session:
            from sqlalchemy import text

            session.execute(text("TRUNCATE TABLE note, kaya_account CASCADE"))
            session.commit()

    empty()

    with get_sessionmaker()() as session:
        account = KayaAccount(
            id=ALICE_ID,
            email="alice@example.com",
            hashed_password="not-a-real-hash",
            is_active=True,
            is_superuser=False,
            is_verified=False,
        )
        session.add(account)
        session.commit()
        session.refresh(account)

    app.dependency_overrides[get_current_active_user] = lambda: account
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        empty()


def mint_pat(client: Any, *, name: str = "test token", scope: str = "write") -> str:
    """A real `kaya_pat_…` secret, minted through the real `/api/v1/tokens` endpoint."""
    response = client.post(TOKENS, json={"name": name, "scope": scope})
    assert response.status_code == 201, response.text
    return response.json()["token"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- The real resolver, end to end: a minted PAT --------------------------------------------------


def test_a_minted_pat_authenticates_a_real_note_request(client: Any) -> None:
    token = mint_pat(client)

    created = client.post(NOTES, json={"title": "via a real kaya_pat_"}, headers=bearer(token))

    assert created.status_code == 201, created.text
    assert created.json()["ref"].startswith("NOTE-")


def test_an_unknown_pat_is_401_invalid_token(client: Any) -> None:
    response = client.get(NOTES, headers=bearer("kaya_pat_this-was-never-minted-by-anyone"))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_no_credential_at_all_is_401_authentication_required(client: Any) -> None:
    response = client.get(NOTES)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_a_token_belonging_to_a_deactivated_account_is_rejected(client: Any) -> None:
    from sqlalchemy import text

    from app.db import get_sessionmaker

    token = mint_pat(client)

    with get_sessionmaker()() as session:
        session.execute(
            text("UPDATE kaya_account SET is_active = false WHERE id = :id"), {"id": ALICE_ID}
        )
        session.commit()

    response = client.get(NOTES, headers=bearer(token))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


def test_an_expired_pat_is_rejected(client: Any) -> None:
    from sqlalchemy import text

    from app.db import get_sessionmaker

    token = mint_pat(client)

    with get_sessionmaker()() as session:
        # Exactly one row exists at this point in the test (this fixture mints one PAT), so no
        # WHERE clause is needed to target it precisely.
        session.execute(
            text("UPDATE personal_access_token SET expires_at = :expired"),
            {"expired": datetime.now(UTC) - timedelta(days=1)},
        )
        session.commit()

    response = client.get(NOTES, headers=bearer(token))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


def test_last_used_at_is_stamped_on_a_successful_pat_auth(client: Any) -> None:
    from sqlalchemy import select

    from app.db import get_sessionmaker
    from app.identity.pat import PersonalAccessToken

    token = mint_pat(client)

    with get_sessionmaker()() as session:
        before = session.scalars(select(PersonalAccessToken)).one()
        assert before.last_used_at is None

    assert client.get(NOTES, headers=bearer(token)).status_code == 200

    with get_sessionmaker()() as session:
        after = session.scalars(select(PersonalAccessToken)).one()
        assert after.last_used_at is not None


def test_a_read_scope_pat_still_authenticates_writes_today(client: Any) -> None:
    """`scope` is stored (ADR 0012) but unenforced until `KAN-1740`'s own follow-up wires it into
    request authorization — this pins the *current*, honest behaviour rather than a claim about
    enforcement this card does not implement."""
    token = mint_pat(client, scope="read")

    response = client.post(
        NOTES, json={"title": "read-scope token, unenforced"}, headers=bearer(token)
    )

    assert response.status_code == 201, (
        "scope enforcement is not yet wired up -- if this starts failing, either enforcement "
        "landed (update this test to assert a 403) or something else broke write access entirely"
    )


# --- The real resolver, end to end: a cookie session ----------------------------------------------


def test_a_cookie_session_authenticates_a_real_note_request(client: Any) -> None:
    from app.db import get_sessionmaker
    from app.identity.models import KayaSession

    with get_sessionmaker()() as session:
        kaya_session = KayaSession(token="a-real-looking-session-token", user_id=ALICE_ID)
        session.add(kaya_session)
        session.commit()

    from app.identity.backend import COOKIE_NAME

    response = client.get(NOTES, cookies={COOKIE_NAME: "a-real-looking-session-token"})

    assert response.status_code == 200, response.text


def test_an_unknown_cookie_falls_through_to_a_bearer_if_one_is_present(client: Any) -> None:
    from app.identity.backend import COOKIE_NAME

    token = mint_pat(client)

    response = client.get(
        NOTES,
        headers=bearer(token),
        cookies={COOKIE_NAME: "a-cookie-naming-no-live-session"},
    )

    assert response.status_code == 200, (
        "a cookie that resolves to nothing must not shadow a bearer that resolves to someone"
    )


def test_a_live_cookie_takes_precedence_over_a_stale_bearer(client: Any) -> None:
    """`resolve_principal`'s documented precedence: cookie first, matching pandan's own — a browser
    holding both a stale bearer and a fresh session should get the fresh one."""
    from app.db import get_sessionmaker
    from app.identity.backend import COOKIE_NAME
    from app.identity.models import KayaSession

    with get_sessionmaker()() as session:
        kaya_session = KayaSession(token="alices-live-session", user_id=ALICE_ID)
        session.add(kaya_session)
        session.commit()

    response = client.get(
        NOTES,
        headers=bearer("kaya_pat_a-bearer-naming-no-real-token"),
        cookies={COOKIE_NAME: "alices-live-session"},
    )

    assert response.status_code == 200, "the live cookie should have won, not the bad bearer"
