"""``/api/v1/preferences`` — per-account settings (KAN-1815).

- ``GET   /api/v1/preferences`` — every registered preference, defaults applied (an account that
  never wrote one reads ``format_on_save: true``).
- ``PATCH /api/v1/preferences`` — partial write of the fields sent; answers the full state.

Scoped by ``principal.id`` and nothing else: there is no way to name another account's
preferences. Cookie session or ``kaya_pat_…`` bearer, like the rest of ``/api/v1``.

``format_on_save`` governs **browser saves only**. The CLI and MCP never format implicitly; they
send ``format`` on the note ``PATCH`` explicitly or not at all, so this route is read by the SPA
and by nothing server-side.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import Principal, get_principal
from app.db import get_session
from app.identity.preferences import (
    FORMAT_ON_SAVE,
    read_preferences,
    write_preference,
)
from app.identity.preferences_schemas import PreferencesRead, PreferencesUpdate

router = APIRouter(prefix="/api/v1", tags=["preferences"])

CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
DbSession = Annotated[Session, Depends(get_session)]


@router.get("/preferences", response_model=PreferencesRead)
def read_account_preferences(db: DbSession, principal: CurrentPrincipal) -> PreferencesRead:
    return PreferencesRead(**read_preferences(db, principal.id))


@router.patch("/preferences", response_model=PreferencesRead)
def update_account_preferences(
    payload: PreferencesUpdate, db: DbSession, principal: CurrentPrincipal
) -> PreferencesRead:
    if payload.format_on_save is not None:
        write_preference(db, principal.id, FORMAT_ON_SAVE, payload.format_on_save)
        db.commit()
    return PreferencesRead(**read_preferences(db, principal.id))
