"""``get_principal``, overridden directly — the one seam every integration test in this package
needs, since KAN-1740 retired the mockable upstream ADR 0002's ``PrincipalResolver`` was built
around.

Before that cutover, a `client` fixture built a `FakeUpstream` (an ``IdentityUpstream``) and wired
it through a real `PrincipalResolver`/`SqlAlchemyPrincipalMirror`/cache/single-flight stack, because
that whole apparatus was the thing under test *somewhere* in the suite and every other file paid to
fake it. `app/auth/kaya_principal.py`'s replacement is a plain database lookup with no seam worth
faking three layers down — the tests that actually exercise it are `test_kaya_principal_resolver.py`
(this package) and `test_identity_manager.py`/`test_tokens_api.py` (KAN-1738/1739). Every other
integration test in this suite is testing note/board *authorization*, not identity *resolution*, so
it can override ``get_principal`` directly with a fixed answer and skip the machinery entirely.

Two error codes, matching the real dependency's contract exactly (`app/auth/dependencies.py`): no
bearer at all is `authentication_required`, a bearer that names nobody known is `invalid_token` —
tests like `test_notes_api.py::test_every_route_requires_a_bearer` and
`test_graph_api.py::test_a_bearer_pandan_does_not_recognise_is_also_a_401` depend on that
distinction surviving the cutover unchanged.
"""

import uuid
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from app.auth.principal import Principal
    from app.identity.models import KayaAccount


def seed_kaya_account(session: Session, *, id: uuid.UUID, email: str) -> "KayaAccount":
    """A real `kaya_account` row for `id` — required alongside `override_get_principal` below,
    never a substitute for it.

    Overriding `get_principal` fakes *who resolved*, not *whether a backing row exists* — and one
    does have to, now: `note.owner_id`'s foreign key points at `kaya_account.id` (migration `0009`),
    so a `POST /api/v1/notes` for a principal with no matching row is a real, correctly-enforced
    `IntegrityError`, not a test artefact to work around. Every `alice`/`bob`-style fixture in this
    package calls this, then registers the identical id in `override_get_principal`'s `known` dict
    — the two together are what "alice" means in this suite.

    Written through the plain sync session, not `app.identity`'s async one: `KayaAccount` lives on
    kaya's one shared `Base`, and nothing about *reading or inserting* it needs the async engine —
    only `app.identity`'s own login/session code does, for reasons that don't apply to seeding a
    fixture row. `hashed_password` is a throwaway string; nothing in this suite ever authenticates
    as this account by password or by any path this repo has (GitHub OAuth is the only login).
    """
    from app.identity.models import KayaAccount

    account = KayaAccount(
        id=id,
        email=email,
        hashed_password="not-a-real-hash",
        is_active=True,
        is_superuser=False,
        is_verified=False,
    )
    session.add(account)
    session.commit()
    session.refresh(account)
    return account


def override_get_principal(app: FastAPI, known: dict[str, "Principal"]) -> None:
    """Wires ``app.dependency_overrides[get_principal]`` to resolve a bearer against ``known``.

    ``known`` is a plain, mutable dict the caller keeps a reference to — a fixture like `alice`
    below populates it *after* this override is installed, and the override reads it fresh on every
    request, so population order between fixtures never matters.
    """
    from app.auth import error_body, get_principal
    from app.auth.dependencies import bearer_scheme

    def resolve_principal_for_test(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    ) -> Any:
        if credentials is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=error_body("authentication_required", "a bearer token is required"),
                headers={"WWW-Authenticate": "Bearer"},
            )
        principal = known.get(credentials.credentials)
        if principal is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=error_body("invalid_token", "kaya did not accept this credential"),
                headers={"WWW-Authenticate": "Bearer"},
            )
        return principal

    app.dependency_overrides[get_principal] = resolve_principal_for_test
