"""Verifying a pasted pandan PAT before kaya stores it (ADR 0012's amendment, KAN-1741).

`app/api/pandan_link.py`'s `POST` route is the one place in kaya that asks a caller to paste a
credential kaya did not itself mint, so it is also the one place worth checking the paste actually
works before committing to it — the alternative (store it unverified, find out it was wrong the
next time a board embed silently renders "not connected") is a worse failure mode for a one-time,
foreground action the caller is watching than the extra round trip costs.

**Deliberately the smallest possible seam**, unlike `card_resolution.py`/`board_embed.py`'s
upstream classes: no cache (a link is verified once, at connect time, never again on this path —
`board_embed.py` is what re-forwards the stored token on every render, and it has its own
timeouts), no single-flight (one caller, one paste, nothing to coalesce), and a plain function
(`httpx.get`, not a pooled `httpx.Client`) because this is not a per-request hot path where a TLS
handshake per call would show up in a measurement.

Mirrors `PandanBoardEmbedUpstream`'s split-timeout, catch-and-translate shape for the one thing
worth reusing from it: pandan being unreachable and pandan rejecting the token are different facts,
and `app/api/pandan_link.py` answers them differently (`503` vs `422`) for the same Q9 reason ADR
0002 gives — a wrong guess about a credential is worse than an honest "couldn't check".
"""

from typing import Protocol

import httpx

from app.config import Settings
from app.pandan_timeout import split_timeout

ME_PATH = "/api/v1/me"


class PandanLinkUnreachable(Exception):
    """Pandan could not be asked at all — a transport failure, not a rejected token. Caught in
    `app/api/pandan_link.py` and turned into a `503` naming the upstream, never a `422`: a caller
    who pasted a good token must not be told it was rejected when the real story is that kaya could
    not check."""


class PandanLinkVerifier(Protocol):
    def verify(self, token: str) -> bool:
        """`True` if pandan's own `GET /api/v1/me` accepts this bearer. Raises
        `PandanLinkUnreachable` rather than returning `False` when pandan could not be reached at
        all — the two are not the same fact and must not collapse to one boolean."""
        ...


class PandanHttpVerifier:
    """`PandanLinkVerifier` over real HTTP, calling the same `GET /api/v1/me` ADR 0002 added to
    pandan for kaya's own now-retired identity resolver — still live and still useful standalone
    (that ADR's own words), which is what makes it the right endpoint to reuse here rather than
    inventing a second one."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: httpx.Timeout | float,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        # `timeout` configures the client this builds; a `client` passed in (tests only) carries
        # its own — same asymmetry as `PandanBoardEmbedUpstream`'s constructor.
        self._client = client if client is not None else httpx.Client(timeout=timeout)

    def verify(self, token: str) -> bool:
        url = self._base_url + ME_PATH
        try:
            response = self._client.get(url, headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as exc:
            raise PandanLinkUnreachable(f"{url} is unreachable") from exc
        return response.status_code == 200


def default_verifier(settings: Settings) -> PandanLinkVerifier:
    return PandanHttpVerifier(
        settings.pandan_url,
        timeout=split_timeout(
            connect=settings.pandan_link_connect_timeout_seconds,
            read=settings.pandan_link_read_timeout_seconds,
        ),
    )
