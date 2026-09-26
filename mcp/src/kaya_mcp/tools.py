"""The tool bodies: open a session, call one `KayaClient` method, return the `Payload`.

Same discipline `kaya_cli.verbs` documents for the CLI — this file is the second adapter ADR 0004
requires it of, and this module is the proof: every function below is one client call, nothing
here formats, projects, truncates or counts anything, and `kaya_mcp.server` is the only place
`render()` is called — the same split `kaya_cli.verbs` (returns a `Payload`) and
`kaya_cli.__main__.main` (calls `render` on it) make.

"Every function below is one client call" is **true without exception as of KAN-964**, and was not
before it: `get_backlinks` raised instead, because ADR 0006 froze the name while `/links` and
`/backlinks` had landed nowhere. KAN-566 landed them, so the exception is gone and so is the module
that held it (`kaya_mcp.errors`, deleted — see `get_backlinks` below).

**`_client()`, not `open_client()` directly, since KAN-1744.** The stdio transport is one process
per user, so `open_client()` (reading `KAYA_TOKEN` from the environment once) was always correct.
The hosted Streamable HTTP transport is one process serving every caller, so it cannot rely on that
env-var singleton — `kaya_mcp.request_auth` carries the validated caller's own bearer in a
per-request contextvar instead (set by `backend/app/identity/mcp_host.py`'s auth middleware before
a tool ever runs), and `_client()` builds a **fresh** `KayaClient` from it when present, falling
back to `open_client()`'s stdio-singleton behaviour when it isn't. The stdio transport never sets
the override, so it always takes the `open_client()` branch, unchanged.

`open_client` is imported into this module's namespace and called by name — the same seam
`kaya_cli.verbs` exposes — so a test replaces it with `monkeypatch.setattr(tools, "open_client",
…)` and drives a tool end to end against an `httpx.MockTransport`: no network and no PAT anywhere
near this repository.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from kaya_client import KayaClient, Payload, api_url, open_client

from kaya_mcp.request_auth import get_request_token


@contextmanager
def _client() -> Iterator[KayaClient]:
    """A `KayaClient` for this call — the hosted transport's per-request override if one is live,
    else the stdio transport's own singleton session. See the module docstring."""
    token_override = get_request_token()
    if token_override is not None:
        yield KayaClient(api_url(), token_override)
        return
    with open_client() as client:
        yield client


def list_notes() -> Payload:
    """`list_notes`: every note the caller owns, newest first."""
    with _client() as client:
        return client.list_notes()


def get_note(ref: str) -> Payload:
    """`get_note`: one note. The ref reaches the API untouched (ADR 0008)."""
    with _client() as client:
        return client.get_note(ref)


def create_note(title: str, *, body: str | None, path: str | None) -> Payload:
    """`create_note`. A write — no `fields` here or on the tool above it (ADR 0006 §1)."""
    with _client() as client:
        return client.create_note(title, body=body, path=path)


def edit_note(
    ref: str,
    *,
    title: str | None,
    body: str | None,
    path: str | None,
    if_updated_at: str | None,
) -> Payload:
    """`edit_note`: a `PATCH`, guarded only when `if_updated_at` is given (ADR 0009)."""
    with _client() as client:
        return client.update_note(
            ref, title=title, body=body, path=path, if_updated_at=if_updated_at
        )


def search_notes(q: str) -> Payload:
    """`search_notes`: the same `list_notes` call with `q` forwarded (KAN-558/559).

    There is no separate search method on `KayaClient` — the API returns the same `NoteList`
    shape either way — so there is no separate call here either.
    """
    with _client() as client:
        return client.list_notes(q)


def get_backlinks(ref: str) -> Payload:
    """`get_backlinks`: the notes whose body links to this one.

    **KAN-964 replaced a refusal with this line, and the line is all it took.** KAN-569 registered
    this tool against ADR 0006's frozen six with nothing behind it — no backend route, no
    `KayaClient` method, no CLI verb — and every call raised `kaya_mcp.errors.BacklinksNotAvailable`
    so a caller could not mistake "not built yet" for "this note has no backlinks". KAN-566 landed
    all three layers (`backend/app/api/links.py`, `KayaClient.backlinks`, `kaya backlinks <ref>`),
    which made the refusal a false statement rather than an honest gap, so `kaya_mcp/errors.py` is
    **gone**: it existed for this one refusal and nothing else ever referenced it, and this package
    now invents no failure of its own.

    Nothing here knows that the payload is a *note* collection — `KayaClient.backlinks` attaches
    the note noun, the note columns and the note prose fields at the call, because `/backlinks`
    answers with the very same `NoteList` a plain list does. That is why `fields`, truncation and
    the `{"count": n}` aggregate all came out right for this tool with **no** line written for them
    anywhere in `mcp/` (ADR 0004), and why `kaya_cli.verbs._backlinks` says the same thing about
    itself one adapter over.
    """
    with _client() as client:
        return client.backlinks(ref)
