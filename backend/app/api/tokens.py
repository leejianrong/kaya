"""``/api/v1/tokens`` — kaya's own PATs (ADR 0012, KAN-1739, mirrors pandan ADR 0014).

Three routes, every one gated on kaya's **cookie-session** identity (`app/identity/current_user.py`)
and nothing else — never a `kaya_pat_` bearer. That is the chicken-and-egg pandan ADR 0014 avoids
the same way: a token cannot mint or revoke itself, so minting the *first* one requires a real,
logged-in-via-GitHub human. This mirrors "the SERVICE bypass is not a user and gets `403`" from
pandan's own decision — kaya has no SERVICE bypass, but the shape of the rule (token management is
inherently per-account) is the same:

- ``GET    /api/v1/tokens``      — list the caller's tokens (metadata only, never the secret)
- ``POST   /api/v1/tokens``      — create a token; the response includes the secret **once**
- ``DELETE /api/v1/tokens/{id}`` — revoke (hard-delete) one of the caller's own tokens

**This router does not authenticate anything with the tokens it manages.** Wiring a `kaya_pat_`
bearer into request authentication for `/api/v1/notes` and friends is `KAN-1740`'s job, not this
one's — see `app/identity/pat.py`'s module docstring.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.identity.current_user import get_current_active_user
from app.identity.models import KayaAccount
from app.identity.pat import PersonalAccessToken, generate_token
from app.identity.pat_schemas import TokenCreate, TokenCreated, TokenRead

router = APIRouter(prefix="/api/v1", tags=["tokens"])

CurrentUser = Annotated[KayaAccount, Depends(get_current_active_user)]
DbSession = Annotated[Session, Depends(get_session)]


@router.get("/tokens", response_model=list[TokenRead])
def list_tokens(db: DbSession, user: CurrentUser) -> list[PersonalAccessToken]:
    return list(
        db.scalars(
            select(PersonalAccessToken)
            .where(PersonalAccessToken.user_id == user.id)
            .order_by(PersonalAccessToken.id)
        ).all()
    )


@router.post("/tokens", response_model=TokenCreated, status_code=status.HTTP_201_CREATED)
def create_token(payload: TokenCreate, db: DbSession, user: CurrentUser) -> TokenCreated:
    raw, prefix, token_hash = generate_token(get_settings().kaya_auth_secret)
    pat = PersonalAccessToken(
        user_id=user.id,
        name=payload.name,
        token_hash=token_hash,
        token_prefix=prefix,
        scope=payload.scope.value,
        expires_at=payload.expires_at,
    )
    db.add(pat)
    db.commit()
    db.refresh(pat)
    # The only time the raw secret is ever returned (R7.1, pandan ADR 0014's numbering).
    return TokenCreated(
        id=pat.id,
        name=pat.name,
        token_prefix=pat.token_prefix,
        scope=pat.scope,  # type: ignore[arg-type]
        created_at=pat.created_at,
        last_used_at=pat.last_used_at,
        expires_at=pat.expires_at,
        token=raw,
    )


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_token(token_id: int, db: DbSession, user: CurrentUser) -> Response:
    pat = db.get(PersonalAccessToken, token_id)
    # 404, not 403, for someone else's token — deliberately the *opposite* choice from a note's
    # owner-mismatch case (`docs/QUESTIONS.md` Q40, a `403`, on purpose, because a note ref already
    # leaks a rough count via one global sequence). A token id has no such excuse to leak: it names
    # a live credential's metadata, and mirrors pandan ADR 0014's own "don't reveal it exists" call.
    if pat is None or pat.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="token not found")
    db.delete(pat)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
