"""``GET /api/v1/embeds/board`` against a real Postgres — KAN-1049, amended by ADR 0012's KAN-1741.

**Moved here from the fast, no-infrastructure layer.** Before `KAN-1741`, this route depended on no
database at all — it forwarded the caller's own bearer straight to pandan and skipped
`get_principal` entirely (`app/api/embeds.py`'s old module docstring argued this at length). That
stopped being true the day the caller's own bearer stopped being a pandan credential: this route now
resolves the caller's kaya identity and looks up their linked pandan PAT
(`app/identity/pandan_link.py`) with a real, indexed `SELECT`, so it needs the same real-Postgres
fixture every other authenticated route's integration test does.

`get_board_embed_resolver` is still overridden with an in-memory fake — this file's job is proving
the identity-to-linked-token wiring (`app/api/embeds.py`'s `linked_pandan_bearer`) and the
`not_connected` plumbing, not re-proving `BoardEmbedResolver`'s own call shape
(`test_board_embed.py` already does that against a fake upstream) or pandan's real HTTP contract
(`test_board_embed_upstream.py`).

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

BOARD_EMBED = "/api/v1/embeds/board"

# Never a real pandan credential — this suite fakes `get_board_embed_resolver` itself, so nothing
# downstream of `app/api/embeds.py`'s own decrypt ever tries to use this value as a bearer against a
# real pandan. It only has to round-trip through `encrypt_token`/`decrypt_token` unchanged.
ALICES_PANDAN_PAT = "pandan_pat_FAKEalices-real-linked-token"


def _alembic_config() -> Any:
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


class FakeBoardEmbedResolver:
    """A `BoardEmbedResolver`, answering a canned result and recording every call it saw —
    including the `bearer` argument, which is this file's whole point: proving it is the *decrypted
    linked pandan token*, never the caller's own kaya-side credential."""

    def __init__(self) -> None:
        from app.integrations.board_embed import BoardEmbedResult

        self.result = BoardEmbedResult(unavailable=False, cards=())
        self.calls: list[tuple[str | None, int, int | None, str | None]] = []

    def resolve(
        self,
        bearer: str | None,
        board_id: int,
        *,
        view_id: int | None = None,
        column: str | None = None,
    ) -> Any:
        self.calls.append((bearer, board_id, view_id, column))
        return self.result


@pytest.fixture
def resolver() -> FakeBoardEmbedResolver:
    return FakeBoardEmbedResolver()


@pytest.fixture
def known_principals() -> dict[str, Any]:
    return {}


@pytest.fixture
def client(
    database_url: str, known_principals: dict[str, Any], resolver: FakeBoardEmbedResolver
) -> Iterator[Any]:
    """The real app: identity faked directly (`override_get_principal`, KAN-1740's own seam) over a
    real `kaya_account` row (required — `app/api/embeds.py`'s `linked_pandan_bearer` does a real
    `SELECT ... WHERE pandan_link.user_id = :id`), and `get_board_embed_resolver` faked at its own,
    unrelated seam so no real pandan is ever called."""
    from alembic import command
    from fastapi.testclient import TestClient

    from app.db import get_sessionmaker
    from app.integrations.dependencies import get_board_embed_resolver
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
    app.dependency_overrides[get_board_embed_resolver] = lambda: resolver
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        del app.dependency_overrides[get_board_embed_resolver]
        app.dependency_overrides.clear()
        empty()


@pytest.fixture
def alice(client: Any, known_principals: dict[str, Any]) -> Any:
    """`client: Any` as an otherwise-unused parameter forces `client`'s own truncation to complete
    before this fixture runs — the same ordering guard `test_notes_api.py`'s own `alice`/`bob`
    fixtures use, and for the identical pytest-fixture-resolution-order reason."""
    from app.auth.principal import Principal

    known_principals[ALICE_TOKEN] = Principal(id=ALICE_ID, email="alice@example.com")
    return ALICE_TOKEN


def connect_alices_pandan_account(raw_token: str = ALICES_PANDAN_PAT) -> None:
    """Insert a real, encrypted `pandan_link` row for Alice directly — this file is not the one
    proving `POST /api/v1/pandan-link`'s own verify-then-store flow (`test_pandan_link_api.py`
    does), only that `app/api/embeds.py` reads and decrypts whatever is already there."""
    from app.config import get_settings
    from app.db import get_sessionmaker
    from app.identity.pandan_link import PandanLink, encrypt_token

    with get_sessionmaker()() as session:
        session.add(
            PandanLink(
                user_id=ALICE_ID,
                encrypted_token=encrypt_token(raw_token, get_settings().kaya_auth_secret),
            )
        )
        session.commit()


def error(response: Any) -> dict[str, Any]:
    return response.json()["error"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- the happy paths, with a linked pandan account -------------------------------------------


def test_a_column_query_returns_the_resolved_cards(
    client: Any, resolver: FakeBoardEmbedResolver, alice: str
) -> None:
    from app.integrations.board_embed import BoardEmbedCard, BoardEmbedResult

    connect_alices_pandan_account()
    resolver.result = BoardEmbedResult(
        unavailable=False,
        cards=(BoardEmbedCard(ref="KAN-1", title="First", column="todo"),),
    )

    response = client.get(f"{BOARD_EMBED}?board=18&column=todo", headers=bearer(alice))

    assert response.status_code == 200
    assert response.json() == {
        "unavailable": False,
        "not_connected": False,
        "cards": [{"ref": "KAN-1", "title": "First", "column": "todo"}],
    }
    assert resolver.calls == [(ALICES_PANDAN_PAT, 18, None, "todo")]


def test_a_view_query_forwards_the_view_id_not_a_column(
    client: Any, resolver: FakeBoardEmbedResolver, alice: str
) -> None:
    connect_alices_pandan_account()

    response = client.get(f"{BOARD_EMBED}?board=18&view=3", headers=bearer(alice))

    assert response.status_code == 200
    assert resolver.calls == [(ALICES_PANDAN_PAT, 18, 3, None)]


def test_an_unavailable_result_is_still_a_200(
    client: Any, resolver: FakeBoardEmbedResolver, alice: str
) -> None:
    """Q26/ADR 0003's rendering-not-an-error contract, one route over from `/links`: pandan being
    down, or the caller lacking access to this board, is a decoration going missing, not a
    refusal."""
    from app.integrations.board_embed import BoardEmbedResult

    connect_alices_pandan_account()
    resolver.result = BoardEmbedResult(unavailable=True, cards=())

    response = client.get(f"{BOARD_EMBED}?board=18&column=todo", headers=bearer(alice))

    assert response.status_code == 200
    assert response.json() == {"unavailable": True, "not_connected": False, "cards": []}


def test_the_decrypted_linked_pandan_token_is_forwarded_not_the_kaya_bearer(
    client: Any, resolver: FakeBoardEmbedResolver, alice: str
) -> None:
    """KAN-1741's whole point. Before it, this route forwarded the caller's own kaya-side bearer
    verbatim (ADR 0002 — the same PAT authenticated both apps). It must not any more: `alice`'s
    kaya-side credential (`ALICE_TOKEN`) and her linked pandan PAT (`ALICES_PANDAN_PAT`) are
    deliberately different strings, and the resolver must see only the second one."""
    connect_alices_pandan_account()

    client.get(f"{BOARD_EMBED}?board=18&column=todo", headers=bearer(alice))

    assert resolver.calls[0][0] == ALICES_PANDAN_PAT
    assert resolver.calls[0][0] != ALICE_TOKEN


# --- no linked pandan account ------------------------------------------------------------------


def test_no_linked_account_forwards_no_bearer_at_all(
    client: Any, resolver: FakeBoardEmbedResolver, alice: str
) -> None:
    """Alice never connected a pandan account (no `connect_alices_pandan_account()` call here) —
    `app/api/embeds.py` must pass `None`, not an empty string or her kaya-side bearer, so
    `BoardEmbedResolver.resolve` can short-circuit to `not_connected` without ever trying pandan
    (proven separately, against the real resolver, by `test_board_embed.py`)."""
    response = client.get(f"{BOARD_EMBED}?board=18&column=todo", headers=bearer(alice))

    assert response.status_code == 200
    assert resolver.calls == [(None, 18, None, "todo")]


def test_not_connected_propagates_to_the_wire(
    client: Any, resolver: FakeBoardEmbedResolver, alice: str
) -> None:
    from app.integrations.board_embed import BoardEmbedResult

    resolver.result = BoardEmbedResult(unavailable=False, cards=(), not_connected=True)

    response = client.get(f"{BOARD_EMBED}?board=18&column=todo", headers=bearer(alice))

    assert response.status_code == 200
    assert response.json() == {"unavailable": False, "not_connected": True, "cards": []}


# --- validation --------------------------------------------------------------------------------


def test_missing_board_is_a_422(client: Any, alice: str) -> None:
    response = client.get(f"{BOARD_EMBED}?column=todo", headers=bearer(alice))

    assert response.status_code == 422
    assert error(response)["code"] == "invalid_request"


def test_a_non_numeric_board_is_a_422(client: Any, alice: str) -> None:
    response = client.get(f"{BOARD_EMBED}?board=not-a-number&column=todo", headers=bearer(alice))

    assert response.status_code == 422


def test_neither_view_nor_column_is_a_422(client: Any, alice: str) -> None:
    response = client.get(f"{BOARD_EMBED}?board=18", headers=bearer(alice))

    assert response.status_code == 422
    assert error(response)["code"] == "invalid_request"
    assert "view" in error(response)["message"]
    assert "column" in error(response)["message"]


def test_both_view_and_column_is_a_422(client: Any, alice: str) -> None:
    response = client.get(f"{BOARD_EMBED}?board=18&view=3&column=todo", headers=bearer(alice))

    assert response.status_code == 422
    assert error(response)["code"] == "invalid_request"


def test_a_malformed_query_makes_no_upstream_call(
    client: Any, resolver: FakeBoardEmbedResolver, alice: str
) -> None:
    client.get(f"{BOARD_EMBED}?board=18", headers=bearer(alice))

    assert resolver.calls == []


# --- authentication ------------------------------------------------------------------------------


def test_no_bearer_is_a_401(client: Any, resolver: FakeBoardEmbedResolver) -> None:
    response = client.get(f"{BOARD_EMBED}?board=18&column=todo")

    assert response.status_code == 401
    assert error(response)["code"] == "authentication_required"
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert resolver.calls == []


def test_a_bearer_kaya_does_not_recognise_is_a_401_before_reaching_pandan(
    client: Any, resolver: FakeBoardEmbedResolver
) -> None:
    """Inverts this route's pre-`KAN-1740` behaviour, deliberately. Before that cutover, kaya did
    not introspect the bearer itself here — any shape reached pandan, which was the one that would
    say whether it was any good, and a rejection surfaced as `unavailable`, never kaya's own `401`.
    That was correct when the caller's bearer *was* a pandan credential; it no longer is one, and
    kaya's own `get_principal` now genuinely knows every credential it will ever accept (its own
    `kaya_account`/`kaya_session`/`personal_access_token` tables), so an unrecognised bearer is
    kaya's `401` before this route's own database lookup, let alone pandan, is ever reached."""
    response = client.get(
        f"{BOARD_EMBED}?board=18&column=todo",
        headers=bearer("garbage-kaya-has-never-seen"),
    )

    assert response.status_code == 401
    assert error(response)["code"] == "invalid_token"
    assert resolver.calls == []


def test_documented_in_the_openapi_schema(client: Any, alice: str) -> None:
    schema = client.get("/openapi.json").json()

    assert "/api/v1/embeds/board" in schema["paths"]
