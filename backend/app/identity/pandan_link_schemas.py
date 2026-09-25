"""What a linked pandan account looks like on the wire (ADR 0012's amendment, KAN-1741).

Two classes, mirroring `pat_schemas.py`'s own reasoning for being a file separate from
`app/api/schemas.py`: `app/api/pandan_link.py` needs them and nothing else does.

**`PandanLinkStatus` is the only shape this feature ever returns after a link exists.** Never the
stored token, never its prefix, never even whether it was ever *tested* successfully more than
once — a caller either has a link or does not, the same over-disclosure posture `TokenRead` already
takes for kaya's own PATs (`app/identity/pat_schemas.py`), just with nothing at all left to show
once the boolean is `true`."""

from pydantic import BaseModel, Field


class PandanLinkStatus(BaseModel):
    """`GET`/`POST`/`DELETE /api/v1/pandan-link` all answer this shape. `connected` is the entire
    fact this feature is willing to state about a caller's linked pandan account."""

    connected: bool


class PandanLinkConnect(BaseModel):
    """`POST /api/v1/pandan-link`'s body: the raw pandan PAT to link, verified against pandan's own
    `GET /api/v1/me` before it is ever stored (`app/integrations/pandan_link.py`)."""

    token: str = Field(min_length=1)
