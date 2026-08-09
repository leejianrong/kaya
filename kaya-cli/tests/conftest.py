"""What every CLI test runs against: no ambient configuration, and a faked API.

### The environment is cleared for every test, without exception

`kaya_client.config` reads ``KAYA_API_URL`` and ``KAYA_TOKEN`` from the environment at call time, so
a developer with a real PAT exported would otherwise have `note list` reach a real deployment from
inside the fast test layer — a network call in the layer that gates every local push, against
somebody's actual notes. The autouse fixture below removes both keys from ``os.environ``, which also
covers the subprocess tests: a child process inherits the parent's environment, so clearing it here
clears it there.

It is autouse rather than opt-in on purpose. A test that forgot to ask would pass on a laptop with
nothing exported and fail on one with a PAT, which is the worst failure mode a fixture can have.

### The API is an `httpx.MockTransport`, and everything above it is real

``fake_api`` replaces `kaya_cli.verbs.open_client` with one that builds a **real** ``KayaClient``
over a fake transport. Everything from argv down to the printed bytes is the shipped code path:
argparse, `verbs.run`, `KayaClient._request`, the exception classes, ``render``, the exit table.
Only the socket is imaginary.

That is what lets `test_failure_classes.py` prove SLICES §V2a's six classes end to end rather
than at a seam — a `404` is a real ``ApiError`` raised by the real client from a real response
object — and it is what keeps the promise that no PAT and no network go near these tests.
"""

import httpx
import pytest
from kaya_client import config

from kaya_cli import verbs

BASE_URL = "https://kaya.example"

TOKEN = "kanban_pat_notarealtokenatall"
"""Not a real credential, and shaped like a pre-rebrand one deliberately: ADR 0002 gives kaya no
token format and no prefix logic, so the tests must not accidentally imply one exists."""

GROCERIES = {
    "ref": "NOTE-12",
    "id": 12,
    "title": "Groceries",
    "body": "milk\neggs",
    "path": "home/groceries.md",
    "created_at": "2026-08-01T09:15:00+00:00",
    "updated_at": "2026-08-09T11:02:33.123456+00:00",
}

READING_LIST = {
    "ref": "NOTE-3",
    "id": 3,
    "title": "A reading list",
    "body": "",
    "path": "",
    "created_at": "2026-07-14T18:00:00+00:00",
    "updated_at": "2026-07-14T18:00:00+00:00",
}

NOTES = {"notes": [GROCERIES, READING_LIST]}
"""The same two notes `kaya-client`'s ``conftest`` renders, copied rather than imported — the two
packages are separately installable and a test suite that reached into its dependency's tests would
break the day one of them is released on its own. They are the corpus the human row is pinned
against, so the CLI's assertions and the client's are about the same bytes."""


@pytest.fixture(autouse=True)
def no_ambient_configuration(monkeypatch, tmp_path) -> None:
    """Every test starts with no deployment, no credential, no text limit and an empty config file.

    ``KAYA_MAX_TEXT_CHARS`` joined the list with KAN-547 for a weaker reason than the other two but
    the same failure mode: a developer with it exported would see every default-row assertion in
    this package pass or fail depending on their shell, and the subprocess tests would inherit it.

    **``XDG_CONFIG_HOME`` and ``HOME`` joined it with KAN-551, and for that card they are the
    strongest line in this file.** `kaya config set` writes a real file to a real path, so a suite
    that did not redirect the config directory would write to the developer's own
    ``~/.config/kaya/config.json`` — and, because ``write_settings`` merges, would do it *without*
    losing their settings, which is the version of this bug that goes unnoticed longest. Both
    variables are pointed at a per-test ``tmp_path``: ``XDG_CONFIG_HOME`` because it is what
    `config_path` consults first, and ``HOME`` because a test that unset the first must not fall
    through to the second.
    """
    monkeypatch.delenv(config.API_URL_ENV, raising=False)
    monkeypatch.delenv(config.TOKEN_ENV, raising=False)
    monkeypatch.delenv(config.MAX_TEXT_CHARS_ENV, raising=False)
    monkeypatch.setenv(config.CONFIG_HOME_ENV, str(tmp_path / "xdg"))
    monkeypatch.setenv(config.HOME_ENV, str(tmp_path / "home"))


@pytest.fixture
def fake_api(monkeypatch):
    """Install a fake API, returning the request log so a test can assert on what was sent."""
    seen: list[httpx.Request] = []

    def install(handler, *, token: str = TOKEN, base_url: str = BASE_URL) -> list[httpx.Request]:
        def recording(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return handler(request)

        def open_client():
            return config.open_client(
                {config.API_URL_ENV: base_url, config.TOKEN_ENV: token},
                transport=httpx.MockTransport(recording),
            )

        monkeypatch.setattr(verbs, "open_client", open_client)
        return seen

    return install


@pytest.fixture
def answering(fake_api):
    """The common case: one canned JSON body for whatever is asked."""

    def install(status: int, body: dict) -> list[httpx.Request]:
        return fake_api(lambda request: httpx.Response(status, json=body))

    return install
