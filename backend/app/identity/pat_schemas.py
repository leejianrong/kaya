"""What a personal access token looks like on the wire (ADR 0012, KAN-1739).

Separate from `app/identity/schemas.py` (the fastapi-users account contract) on purpose: those
three classes exist because `fastapi-users`' routers require *some* Pydantic model, however thin;
these three exist because `app/api/tokens.py` needs them, the same reason `app/api/schemas.py`
holds every note-shaped model. A PAT is not a `KayaAccount`, and putting both in one file would
blur a distinction this package's own module layout otherwise keeps clean.
"""

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_NAME_LEN = 255
"""Matches `personal_access_token.name`'s `String(255)` column (migration `0008`) — a longer value
is a `422` here, not a psycopg `DataError` two layers down."""


class TokenScope(StrEnum):
    """A PAT's capability (ADR 0012, mirroring pandan ADR 0014's post-KAN-251 shape — kaya starts
    with the split already in place rather than growing into it). `read` = observer (GET only);
    `write` = operator (the owning account's full access, and the default).

    **Unenforced by this card.** The column and this enum exist so `KAN-1740` has something to
    read when it wires a PAT bearer into request authentication; until then, minting a `read`-scope
    token has no effect on what it can do, because nothing checks `scope` yet."""

    read = "read"
    write = "write"


class TokenCreate(BaseModel):
    """`POST /api/v1/tokens`'s body. Only a name, an optional scope (default `write`), and an
    optional expiry — the secret is always server-generated, never client-supplied."""

    name: Annotated[str, Field(min_length=1, max_length=MAX_NAME_LEN)]
    scope: TokenScope = TokenScope.write
    expires_at: datetime | None = None

    @field_validator("name")
    @classmethod
    def name_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name must not be empty")
        return value


class TokenRead(BaseModel):
    """Token metadata — **never** the secret. `token_prefix` (e.g. `kaya_pat_ab12`) is the only
    hint a caller gets once the create response has scrolled past."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    token_prefix: str
    scope: TokenScope
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None


class TokenCreated(TokenRead):
    """The create-only response: metadata **plus** the raw secret, returned exactly once (R7.1 in
    pandan ADR 0014's numbering). The client must copy it now — it is hashed at rest and cannot be
    retrieved again."""

    token: str
