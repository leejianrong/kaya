"""``/api/v1/pandan-link`` — connecting a kaya account to a pandan PAT (ADR 0012's amendment,
KAN-1741).

The board-embed preview (`app/api/embeds.py`) used to forward the caller's own kaya-side bearer
straight to pandan and it happened to work, because before `KAN-1740` the same PAT authenticated
both apps (ADR 0002). It no longer does: the caller's bearer is a `kaya_pat_…` kaya minted itself,
or no bearer at all for a cookie session, and pandan has never seen either. This router is the fix
— an explicit, one-time step where a caller pastes a **pandan** PAT, kaya verifies it actually works
against pandan's own `GET /api/v1/me` (`app/integrations/pandan_link.py`), and, only then, stores it
encrypted (`app/identity/pandan_link.py`) for `board_embed.py` to forward on the caller's behalf
from then on.

Gated on `get_principal`, unlike `app/api/tokens.py`'s cookie-session-only routes. There is no
chicken-and-egg here the way minting kaya's *own* first PAT has (pandan ADR 0014's own reasoning,
mirrored in `tokens.py`'s module docstring): a caller connecting a *pandan* account is already
holding a working kaya credential, cookie or `kaya_pat_…` bearer, by the time they reach this route
at all — `get_principal` is exactly the credential every other authenticated route under
`api_router` already requires, and since `KAN-1740` it costs nothing extra to check (a local,
indexed database lookup, not a call to pandan the way it would have been before that cutover).

Three routes:

- ``GET    /api/v1/pandan-link`` — whether the caller has a linked pandan account.
- ``POST   /api/v1/pandan-link`` — connect (or replace) one. Verifies before storing; `422` if
  pandan rejects the pasted token, `503` if pandan could not be asked at all (Q9's "a wrong guess
  about a credential is worse than an honest 'couldn't check'", the same call ADR 0002 made).
- ``DELETE /api/v1/pandan-link`` — disconnect. Idempotent: deleting a link that does not exist is
  still `200 {"connected": false}`, not a `404` — there is nothing here for a caller to have gotten
  wrong by asking twice.

**Never returns the stored token, or any part of it** — `PandanLinkStatus`'s own docstring is the
whole of what this feature is willing to say about a caller's linked account.
"""

from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import Principal, error_body, get_principal
from app.config import get_settings
from app.db import get_session
from app.identity.pandan_link import PandanLink, decrypt_token, encrypt_token
from app.identity.pandan_link_schemas import PandanLinkConnect, PandanLinkStatus
from app.integrations.dependencies import PandanLinkVerify
from app.integrations.pandan_link import PandanLinkUnreachable

router = APIRouter(prefix="/api/v1", tags=["pandan-link"])

CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
DbSession = Annotated[Session, Depends(get_session)]


def _find_link(db: Session, principal: Principal) -> PandanLink | None:
    return db.scalar(select(PandanLink).where(PandanLink.user_id == principal.id))


def _is_connected(db: Session, principal: Principal) -> bool:
    """A link row existing is not quite enough on its own: `KAYA_AUTH_SECRET` may have rotated
    since it was stored, in which case the stored ciphertext can no longer be read back
    (`decrypt_token`'s own docstring) and the caller must reconnect — indistinguishable, from their
    chair, from never having connected at all, so this reports it the same way rather than a link
    that silently stops working the next time a board embed renders."""
    link = _find_link(db, principal)
    if link is None:
        return False
    return decrypt_token(link.encrypted_token, get_settings().kaya_auth_secret) is not None


@router.get("/pandan-link", response_model=PandanLinkStatus)
def read_pandan_link(db: DbSession, principal: CurrentPrincipal) -> PandanLinkStatus:
    return PandanLinkStatus(connected=_is_connected(db, principal))


@router.post("/pandan-link", response_model=PandanLinkStatus)
def connect_pandan_link(
    payload: PandanLinkConnect,
    db: DbSession,
    principal: CurrentPrincipal,
    verifier: PandanLinkVerify,
) -> PandanLinkStatus:
    try:
        accepted = verifier.verify(payload.token)
    except PandanLinkUnreachable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=error_body(
                "pandan_unavailable",
                "kaya could not reach pandan to verify this token",
            ),
        ) from exc

    if not accepted:
        raise HTTPException(
            # `HTTPStatus.UNPROCESSABLE_ENTITY` rather than `status.HTTP_422_UNPROCESSABLE_ENTITY`,
            # matching `app/api/embeds.py`'s own comment — the latter is a deprecated alias in this
            # Starlette version (`HTTP_422_UNPROCESSABLE_CONTENT` replaced it).
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail=error_body(
                "invalid_pandan_token", "pandan did not accept this token", field="token"
            ),
        )

    encrypted = encrypt_token(payload.token, get_settings().kaya_auth_secret)
    existing = _find_link(db, principal)
    if existing is not None:
        # Replace, not append — one row per account (the table's own unique index would reject a
        # second insert anyway), so reconnecting after a rotation or a mistake is the same call as
        # connecting the first time.
        existing.encrypted_token = encrypted
    else:
        db.add(PandanLink(user_id=principal.id, encrypted_token=encrypted))
    db.commit()

    return PandanLinkStatus(connected=True)


@router.delete("/pandan-link", response_model=PandanLinkStatus)
def disconnect_pandan_link(db: DbSession, principal: CurrentPrincipal) -> PandanLinkStatus:
    link = _find_link(db, principal)
    if link is not None:
        db.delete(link)
        db.commit()
    return PandanLinkStatus(connected=False)
