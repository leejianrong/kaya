"""The tool bodies: open a session, call one `KayaClient` method, return the `Payload`.

Same discipline `kaya_cli.verbs` documents for the CLI — this file is the second adapter ADR 0004
requires it of, and this module is the proof: every function below is one client call, nothing
here formats, projects, truncates or counts anything, and `kaya_mcp.server` is the only place
`render()` is called — the same split `kaya_cli.verbs` (returns a `Payload`) and
`kaya_cli.__main__.main` (calls `render` on it) make.

`open_client` is imported into this module's namespace and called by name — the same seam
`kaya_cli.verbs` exposes — so a test replaces it with `monkeypatch.setattr(tools, "open_client",
…)` and drives a tool end to end against an `httpx.MockTransport`: no network and no PAT anywhere
near this repository.
"""

from kaya_client import Payload, open_client

from kaya_mcp.errors import ARG, MESSAGE, BacklinksNotAvailable


def list_notes() -> Payload:
    """`list_notes`: every note the caller owns, newest first."""
    with open_client() as client:
        return client.list_notes()


def get_note(ref: str) -> Payload:
    """`get_note`: one note. The ref reaches the API untouched (ADR 0008)."""
    with open_client() as client:
        return client.get_note(ref)


def create_note(title: str, *, body: str | None, path: str | None) -> Payload:
    """`create_note`. A write — no `fields` here or on the tool above it (ADR 0006 §1)."""
    with open_client() as client:
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
    with open_client() as client:
        return client.update_note(
            ref, title=title, body=body, path=path, if_updated_at=if_updated_at
        )


def search_notes(q: str) -> Payload:
    """`search_notes`: the same `list_notes` call with `q` forwarded (KAN-558/559).

    There is no separate search method on `KayaClient` — the API returns the same `NoteList`
    shape either way — so there is no separate call here either.
    """
    with open_client() as client:
        return client.list_notes(q)


def get_backlinks(ref: str) -> Payload:
    """`get_backlinks`: refuses, every time. See `kaya_mcp.errors` for why this is a refusal
    rather than a stub returning an empty list, and this module's own docstring for why the
    refusal lives here and not in `kaya_client` or `kaya-cli`.

    `ref` is accepted and unused: it documents the shape this tool will need once KAN-566 lands,
    so that landing is a change to this function's body and not to its signature or registration.
    """
    raise BacklinksNotAvailable(MESSAGE, arg=ARG)
