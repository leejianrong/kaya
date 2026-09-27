"""`app/identity/backend.py`'s builders, exercised as pure objects — no app, no database.

`RedirectingCookieTransport` is the one piece of this module with actual behaviour rather than
wiring; the rest (`build_database_strategy`, `build_github_oauth_client`) is covered indirectly by
`test_identity_router.py` and `tests/integration/test_identity_manager.py`.
"""

import asyncio

from app.identity.backend import POST_LOGIN_REDIRECT, RedirectingCookieTransport


def _transport() -> RedirectingCookieTransport:
    return RedirectingCookieTransport(cookie_name="kayaauth", cookie_secure=False)


def test_a_successful_login_redirects_home_rather_than_a_bare_204() -> None:
    """The browser lands on `/auth/github/callback` by a full-page navigation GitHub itself makes
    -- a `204` (`CookieTransport`'s own default) leaves the tab on a blank page. Redirects to `/`,
    not `/tokens`: `App.svelte` mints its own bearer silently from the fresh cookie this response
    also sets, so there is no page it needs to visit by hand to finish signing in."""
    response = asyncio.run(_transport().get_login_response("a-real-session-token"))

    assert response.status_code == 302
    assert response.headers["location"] == POST_LOGIN_REDIRECT == "/"


def test_the_session_cookie_is_still_set_on_the_redirect() -> None:
    """The override changes the response *type*, not the one thing `get_login_response` exists to
    do: nothing here should be able to drop the `Set-Cookie` header along the way."""
    response = asyncio.run(_transport().get_login_response("a-real-session-token"))

    assert "kayaauth=a-real-session-token" in response.headers["set-cookie"]


def test_logout_is_untouched_and_still_answers_204() -> None:
    """`Tokens.svelte`'s `signOut()` calls this over `fetch()`, never a navigation -- a redirect
    here would be silently followed by `fetch()` rather than the empty body the caller expects."""
    response = asyncio.run(_transport().get_logout_response())

    assert response.status_code == 204
