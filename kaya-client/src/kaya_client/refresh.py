"""Renewing a short-lived access token with its refresh token (ADR 0016, KAY-172).

**Why this is a module of its own, and why it takes a lock.** The server rotates a refresh token on
every use and a consumed one fails (`oauth_refresh_token`, ADR 0016). Two `kaya` processes that both
hold the same refresh token and both get a `401` would each try to rotate it; the second loses, and
the user is logged out for what was only bad timing. A shell with two panes, or the CLI running
beside the stdio MCP server from one config file, is enough to cause it.

So the whole renewal runs under an exclusive lock on a file beside the config file, and **the holder
re-reads the config before it spends anything**. If the access token on disk is no longer the stale
one that earned this caller its `401`, somebody else already rotated, and the right answer is to
use theirs. That re-read is the load-bearing line: the lock alone only makes the processes queue,
and the second one would still spend a token the first had consumed.

**What is and is not renewed.** Only a token that came from the config file, because the refresh
token belongs to that file's access token. A `KAYA_TOKEN` in the environment is the caller's own
credential and is never swapped for one the file holds (`config.open_client` decides this). A
manually minted `kaya_pat_…` has no refresh token and so is never renewed: `refresh_access_token`
returns `None` and the original `401` stands.

**Never in a message.** Neither token is logged, echoed or put in an exception; the same rule
`config.py` states for the bearer (Q41/Q42).
"""

import contextlib
import os
from collections.abc import Iterator, Mapping
from pathlib import Path

import httpx

from kaya_client.config import (
    REFRESH_TOKEN_KEY,
    TOKEN_KEY,
    config_path,
    read_settings_file,
    remove_refresh_token,
    save_login,
)
from kaya_client.device_login import DEFAULT_TIMEOUT, DEVICE_TOKEN_PATH
from kaya_client.errors import TransportError

try:  # POSIX only. kaya ships a Linux binary; a platform without `fcntl` degrades to no lock.
    import fcntl
except ImportError:  # pragma: no cover - exercised only off POSIX
    fcntl = None  # type: ignore[assignment]

REFRESH_CLIENT_ID = "kaya-cli"
"""The device flow registers no client, so its refresh tokens are bound to this fixed literal. The
server re-checks it on every refresh (ADR 0016)."""

LOCK_SUFFIX = ".lock"


@contextlib.contextmanager
def _locked(path: Path) -> Iterator[None]:
    """An exclusive, blocking lock on ``<config>.lock``. The lock file is never the config file
    itself, because ``_atomic_write`` replaces that file and a lock held on a replaced inode
    protects nothing. The holder is bounded by the refresh request's own timeout."""
    if fcntl is None:  # pragma: no cover
        yield
        return
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = path.with_name(path.name + LOCK_SUFFIX)
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)  # closing releases the lock


def _post_refresh(api_url: str, refresh_token: str, client: httpx.Client | None) -> dict:
    url = api_url.rstrip("/") + DEVICE_TOKEN_PATH
    owns = client is None
    http = client if client is not None else httpx.Client(timeout=DEFAULT_TIMEOUT)
    try:
        try:
            response = http.post(
                url,
                json={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": REFRESH_CLIENT_ID,
                },
            )
        except httpx.HTTPError as exc:
            raise TransportError(f"{url} is unreachable") from exc
    finally:
        if owns:
            http.close()
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def refresh_access_token(
    stale_token: str,
    *,
    api_url: str,
    env: Mapping[str, str] | None = None,
    client: httpx.Client | None = None,
) -> str | None:
    """A usable access token to replace ``stale_token``, or ``None`` when none can be had.

    ``None`` means "nothing to refresh with, or the server refused": the caller keeps the `401` it
    already holds. A **refused** refresh token (`invalid_grant`: consumed, expired or revoked) is
    dropped from the file, so the next command fails fast with a `401` instead of spending another
    round trip, and the message the user then needs is simply "log in again". An unreachable server
    is a `TransportError`, not a `None`: that is an outage, not a verdict on the token.
    """
    with _locked(config_path(env)):
        stored = read_settings_file(env)

        current = str(stored.get(TOKEN_KEY) or "").strip()
        if current and current != stale_token:
            return current  # another process already rotated; spend nothing

        refresh_token = str(stored.get(REFRESH_TOKEN_KEY) or "").strip()
        if not refresh_token:
            return None

        body = _post_refresh(api_url, refresh_token, client)

        access = body.get("access_token")
        if body.get("error") or not isinstance(access, str) or not access:
            if body.get("error") == "invalid_grant":
                remove_refresh_token(env)
            return None

        rotated = body.get("refresh_token")
        save_login(access, rotated if isinstance(rotated, str) and rotated else None, env)
        return access
