"""kaya's own login, exercised against a real Postgres — no GitHub, no network (KAN-1738).

``UserManager.oauth_callback`` is the exact method ``app/identity/router.py``'s GitHub OAuth
router calls once GitHub has answered the callback with a profile. Calling it directly here is the
same seam ADR 0002 argued for at the *pandan* boundary (``FakeUpstream`` in
``test_notes_api.py``), applied at kaya's own new one: what's under test is kaya's side of the
handshake — account creation, account reuse, and session revocation — not GitHub's OAuth dance,
which no unit or integration test in this repo should need a live token to exercise.

``asyncio.run`` per test, not ``pytest-asyncio`` — the async engine (``app/identity/db.py``) is
the only async surface in this codebase, so a whole plugin + marker convention for one test file
would outweigh what it buys. Each test opens and closes its own event loop, which the async engine
tolerates because nothing about it survives across a `run` (`create_async_engine`'s connections are
opened lazily, on the loop that is running when a query actually happens).

**No ``import app.*`` at module top** — see ``tests/integration/__init__``'s package docstring
convention (PR #17's trap: a top-level import binds before the ``database_url`` fixture sets
``DATABASE_URL``).
"""

import asyncio
from pathlib import Path
from typing import Any

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config() -> Any:
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


@pytest.fixture
def migrated(database_url: str) -> None:
    from alembic import command

    command.upgrade(_alembic_config(), "head")


async def _create_via_oauth(email: str, account_id: str) -> Any:
    from fastapi_users.db import SQLAlchemyUserDatabase

    from app.identity.db import get_async_sessionmaker
    from app.identity.manager import UserManager
    from app.identity.models import KayaAccount, KayaOAuthAccount

    async with get_async_sessionmaker()() as session:
        user_db = SQLAlchemyUserDatabase(session, KayaAccount, KayaOAuthAccount)
        manager = UserManager(user_db)
        return await manager.oauth_callback(
            oauth_name="github",
            access_token="gho_fake_access_token",
            account_id=account_id,
            account_email=email,
        )


@pytest.mark.usefixtures("migrated")
def test_first_github_login_creates_an_account_with_one_linked_oauth_row() -> None:
    user = asyncio.run(_create_via_oauth("alice@example.com", account_id="1001"))

    assert user.email == "alice@example.com"
    assert user.is_active is True
    assert len(user.oauth_accounts) == 1
    assert user.oauth_accounts[0].oauth_name == "github"
    assert user.oauth_accounts[0].account_id == "1001"


@pytest.mark.usefixtures("migrated")
def test_a_second_login_from_the_same_github_account_reuses_the_row() -> None:
    """The whole point of resolving by ``(oauth_name, account_id)`` rather than minting fresh: a
    returning user is the *same* ``kaya_account``, not a duplicate with the same email."""
    first = asyncio.run(_create_via_oauth("bob@example.com", account_id="2002"))
    second = asyncio.run(_create_via_oauth("bob@example.com", account_id="2002"))

    assert first.id == second.id
    assert len(second.oauth_accounts) == 1, "a repeat login must not append a second linked row"


@pytest.mark.usefixtures("migrated")
def test_logout_deletes_the_session_row_rather_than_merely_expiring_it() -> None:
    """ADR 0012's whole argument for `DatabaseStrategy` over a self-verifying JWT: logout is a row
    delete, so a stolen cookie stops working the instant it is used, not when a TTL elapses."""

    async def scenario() -> tuple[str | None, str | None]:
        from fastapi_users.authentication.strategy.db import DatabaseStrategy
        from fastapi_users.db import SQLAlchemyUserDatabase
        from fastapi_users_db_sqlalchemy.access_token import SQLAlchemyAccessTokenDatabase

        from app.identity.db import get_async_sessionmaker
        from app.identity.manager import UserManager
        from app.identity.models import KayaAccount, KayaOAuthAccount, KayaSession

        async with get_async_sessionmaker()() as session:
            user_db = SQLAlchemyUserDatabase(session, KayaAccount, KayaOAuthAccount)
            manager = UserManager(user_db)
            user = await manager.oauth_callback(
                oauth_name="github",
                access_token="gho_fake_access_token",
                account_id="3003",
                account_email="carol@example.com",
            )

            access_token_db = SQLAlchemyAccessTokenDatabase(session, KayaSession)
            strategy = DatabaseStrategy(access_token_db)

            token = await strategy.write_token(user)
            before = await strategy.read_token(token, manager)

            await strategy.destroy_token(token, user)
            after = await strategy.read_token(token, manager)

            return (before.email if before is not None else None, after)

    before_email, after = asyncio.run(scenario())

    assert before_email == "carol@example.com"
    assert after is None, "the session must be gone, not merely unreadable-but-present"


@pytest.mark.usefixtures("migrated")
def test_associate_by_email_is_off_so_a_colliding_email_is_refused() -> None:
    """`app/identity/router.py` does not pass `associate_by_email=True` (its default, `False`).
    Two different GitHub accounts sharing an email — a plausible collision once a second OAuth
    provider exists — must not silently merge into one `kaya_account`."""
    from fastapi_users import exceptions

    asyncio.run(_create_via_oauth("dana@example.com", account_id="4004"))

    with pytest.raises(exceptions.UserAlreadyExists):
        asyncio.run(_create_via_oauth("dana@example.com", account_id="4005"))
