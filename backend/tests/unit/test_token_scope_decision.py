"""Every non-GET route has a recorded scope decision (KAN-1887), in the spirit of
`test_no_unscoped_note_query.py`.

A `kaya_pat_` token's `read` scope is enforced in one place: `get_principal`
(`app/auth/dependencies.py`) refuses an unsafe method for a read-scope principal. So a mutating
route is covered exactly when it resolves its caller through `get_principal`. A route that does
not has to say why in `NOT_REACHABLE_BY_A_BEARER`, and this file fails on both mistakes:

- a new POST/PATCH/PUT/DELETE route that neither depends on `get_principal` nor appears below, which
  would let a read token write the day it ships;
- an entry below that now depends on `get_principal`, or no longer exists, so the list cannot rot
  into decoration.

Mutating the guard: remove `Depends(get_principal)` from any mutating route and this fails naming
the route.
"""

from collections.abc import Iterator
from typing import Any

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

NOT_REACHABLE_BY_A_BEARER: dict[tuple[str, str], str] = {
    ("POST", "/auth/login"): "fastapi-users login; credentials in the body, no bearer read",
    ("POST", "/auth/logout"): "cookie session only",
    ("PATCH", "/users/me"): "fastapi-users, cookie session only",
    ("PATCH", "/users/{id}"): "fastapi-users, cookie session and superuser only",
    ("DELETE", "/users/{id}"): "fastapi-users, cookie session and superuser only",
    ("POST", "/auth/register"): "RFC 7591 client registration, unauthenticated by design",
    ("POST", "/auth/device/code"): "device flow step 1, unauthenticated by design (RFC 8628)",
    ("POST", "/auth/device/token"): "device flow polling, authenticated by the device code",
    ("POST", "/auth/device/{user_code}/approve"): "cookie session only",
    ("POST", "/auth/device/{user_code}/deny"): "cookie session only",
    ("POST", "/auth/authorize/approve"): "cookie session only",
    ("POST", "/auth/authorize/deny"): "cookie session only",
    ("POST", "/api/v1/tokens"): "cookie session only: a token cannot mint a token",
    ("DELETE", "/api/v1/tokens/{token_id}"): "cookie session only",
}


def walk(router: Any, prefix: str = "") -> Iterator[Any]:
    """Every concrete route, through `_IncludedRouter` nesting (FastAPI 0.141), with the full path
    on a `served_path` attribute copy."""
    for route in getattr(router, "routes", []):
        nested = getattr(route, "original_router", None)
        if nested is not None:
            context = getattr(route, "include_context", None)
            yield from walk(nested, prefix + getattr(context, "prefix", ""))
        elif getattr(route, "methods", None):
            yield prefix + route.path, route


def dependency_calls(dependant: Any) -> Iterator[Any]:
    for sub in dependant.dependencies:
        yield sub.call
        yield from dependency_calls(sub)


def mutating_routes() -> dict[tuple[str, str], bool]:
    """`(method, path) -> depends on get_principal`."""
    from app.auth import get_principal
    from app.main import app

    found: dict[tuple[str, str], bool] = {}
    for path, route in walk(app):
        dependant = getattr(route, "dependant", None)
        enforced = dependant is not None and get_principal in set(dependency_calls(dependant))
        for method in set(route.methods) - SAFE_METHODS:
            found[(method, path)] = enforced
    return found


def test_the_walker_sees_the_whole_api() -> None:
    found = mutating_routes()

    assert ("POST", "/api/v1/notes") in found
    assert ("DELETE", "/api/v1/notes/{ref}") in found
    assert len(found) >= 15


def test_every_mutating_route_is_scope_enforced_or_justified() -> None:
    undecided = sorted(
        key
        for key, enforced in mutating_routes().items()
        if not enforced and key not in NOT_REACHABLE_BY_A_BEARER
    )

    assert undecided == [], (
        "these routes do not resolve their caller through get_principal, so a read-scope token is "
        f"not stopped on them; route them through it or justify them in this file: {undecided}"
    )


def test_the_justification_list_has_no_stale_entries() -> None:
    found = mutating_routes()

    stale = sorted(key for key in NOT_REACHABLE_BY_A_BEARER if found.get(key) is not False)

    assert stale == [], f"remove these from NOT_REACHABLE_BY_A_BEARER: {stale}"


def test_every_token_scope_has_a_decision_in_get_principal() -> None:
    """KAY-141: the preset set is closed and enforced in `get_principal` alone. A new entry in
    `TOKEN_SCOPES` means a new branch there; this fails until the two are reconciled."""
    from app.identity.pat import TOKEN_SCOPES
    from app.identity.pat_schemas import TokenScope

    assert TOKEN_SCOPES == ("read", "write", "write-no-delete")
    assert {scope.value for scope in TokenScope} == set(TOKEN_SCOPES)


def test_a_principal_with_no_scope_given_is_a_full_access_one() -> None:
    """A cookie session, and every fixture that builds a `Principal` by hand, is not narrowed."""
    import uuid

    from app.auth.principal import Principal

    assert Principal(id=uuid.uuid4(), email="a@example.com").scope == "write"
