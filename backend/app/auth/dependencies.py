"""FastAPI wiring, and nothing else.

Everything with a decision in it lives one module down: ``kaya_principal.py`` for identity,
``authorization.py`` for what a caller may do to a note. What is left here is ``get_principal``, the
dependency every ``/api/v1`` route resolves its caller through.

**Identity has no process-wide singletons (KAN-1740).** ADR 0002's resolver needed a cache, an
upstream client and single-flight because a cold lookup cost a network round trip to pandan.
``kaya_principal.py``'s lookup is a local, indexed database read, so ``get_principal`` reads the
request's cookie and bearer directly and asks the session it already holds. Team lookups, the last
thing here that did need them, were removed by ADR 0017: workspace membership is a local table too.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.errors import error_body
from app.auth.kaya_principal import resolve_principal
from app.auth.principal import Principal
from app.config import get_settings
from app.db import get_session
from app.identity.backend import COOKIE_NAME


def reset_auth() -> None:
    """Kept for the fixtures that call it. There is no cached state left to drop (ADR 0017)."""


SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

bearer_scheme = HTTPBearer(
    scheme_name="kaya PAT",
    description="A personal access token minted by kaya itself (ADR 0012, `kaya_pat_…`).",
    # auto_error=False so a missing header reaches `get_principal` and comes back in the documented
    # error shape rather than in Starlette's bare `{"detail": ...}`.
    #
    # This is the only place in kaya where anything about the `Authorization` header is parsed, it
    # is Starlette doing the parsing, and what it parses is the HTTP *scheme* — the literal
    # `Bearer ` in front. Nothing here, or downstream of here, looks at the credential itself
    # beyond hashing it whole (`app/auth/kaya_principal.py`).
    auto_error=False,
)


def get_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: Annotated[Session, Depends(get_session)],
) -> Principal:
    """The dependency every ``/api/v1`` route depends on.

    Cookie session first, then a ``kaya_pat_…`` bearer, matching pandan's own precedence
    (`app/auth/kaya_principal.py`'s module docstring). ``401 authentication_required`` when neither
    was even supplied; ``401 invalid_token`` when one was supplied and didn't resolve — the same two
    codes ADR 0002's resolver used, preserved on purpose so nothing downstream (kaya-client's exit
    codes, `test_error_extras_stay_addressable.py`) has to learn a new one for the same shape of
    refusal.
    """
    bearer = credentials.credentials if credentials is not None else None
    cookie_token = request.cookies.get(COOKIE_NAME)

    if bearer is None and cookie_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_body("authentication_required", "a bearer token is required"),
            headers={"WWW-Authenticate": "Bearer"},
        )

    principal = resolve_principal(
        session,
        cookie_token=cookie_token,
        bearer=bearer,
        secret=get_settings().kaya_auth_secret,
    )
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_body("invalid_token", "kaya did not accept this credential"),
            headers={"WWW-Authenticate": "Bearer"},
        )
    # KAN-1887 / KAY-141: the one place a token's scope is enforced. Every route that resolves its
    # caller here is covered, and `tests/unit/test_token_scope_decision.py` fails the build for a
    # mutating route that does not. A `DELETE` is the one verb `write-no-delete` loses; the hosted
    # `/mcp` tools call this REST API with the caller's bearer, so they inherit both refusals.
    if principal.scope == "read" and request.method not in SAFE_METHODS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error_body(
                "insufficient_scope",
                "this token has read scope and cannot change anything; use a write-scope token",
            ),
        )
    if principal.scope == "write-no-delete" and request.method == "DELETE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error_body(
                "insufficient_scope",
                "this token has the write-no-delete preset and cannot delete anything; "
                "use a write-scope token",
            ),
        )
    return principal
