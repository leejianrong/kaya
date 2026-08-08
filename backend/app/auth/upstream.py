"""The one place kaya talks to pandan about identity.

Behind a Protocol, because ADR 0002 makes pandan a *runtime dependency for cold authentication* —
the sharpest cost of the whole decision. Faking at the HTTP boundary is what keeps that cost out
of the test suite: valid token, rejected token, upstream down and upstream slow are all reachable
without a network, and none of them needs a real PAT to exist anywhere near this repository.

The contract, verified live against `https://simple-kanban-jian.fly.dev` on 2026-08-08 rather than
inferred from pandan's source:

    GET /api/v1/me, Authorization: Bearer <pat>  ->  200 {"id": "<uuid4>", "email": "<str>"}
    no Authorization header                      ->  401 {"detail": "authentication required"}
    garbage bearer                               ->  401 {"detail": "authentication required"}

Note the last two lines are byte-identical. Pandan will not tell kaya whether a token is malformed
or merely revoked, and that is the empirical reason kaya has no prefix logic to lean on.
"""

import uuid
from typing import Protocol

import httpx

from app.auth.principal import Principal, UpstreamUnavailable

ME_PATH = "/api/v1/me"
"""Pandan's introspection endpoint. Added to pandan for kaya's benefit; see ADR 0002 §Decision."""


def split_timeout(*, connect: float, read: float) -> httpx.Timeout:
    """The deadline for one introspection, as two budgets rather than one (KAN-666).

    A single number cannot be right for both of pandan's failure modes, because they are not the
    same failure. **Down** shows up in the connect phase — nothing answers on port 443, or nothing
    resolves — and wants a short deadline so Q9's `503` is prompt. **Asleep** shows up entirely in
    the read phase: fly's edge proxy completes the TCP and TLS handshakes on its own while the app
    machine boots behind it, so the connection is established in the usual few tens of milliseconds
    and then nothing comes back for twenty seconds. Measured, not assumed — the numbers are on
    KAN-666 and in `scripts/measure_introspection_latency.py --split-only`.

    `write` and `pool` take the connect budget rather than the read one. The request is one small
    segment, so a `write` that blocks past the connect budget is a broken socket rather than a busy
    pandan; and `pool` is contention for a local connection slot, which has nothing to do with how
    awake the upstream is. Neither is left to httpx's default, because `httpx.Timeout` requires all
    four to be given once any of them is, and a phase nobody thought about is how one of these ends
    up unbounded.
    """
    return httpx.Timeout(connect=connect, read=read, write=connect, pool=connect)


class IdentityUpstream(Protocol):
    """Resolves a bearer to a principal, or declines to."""

    def introspect(self, bearer: str) -> Principal | None:
        """``None`` means the upstream was reached and rejected the bearer.

        Raise ``UpstreamUnavailable`` when the upstream could not be *asked*. Returning ``None``
        for an outage is the Q9 bug: it would surface to the caller as a `401` and read as "your
        token is bad" when the token is fine.
        """
        ...


class PandanIdentityUpstream:
    """``IdentityUpstream`` over real HTTP.

    The bearer is forwarded byte-for-byte. It is not parsed, measured, or looked at — pandan owns
    the token format and is the only thing entitled to have an opinion about it.
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout: httpx.Timeout | float,
        client: httpx.Client | None = None,
    ) -> None:
        self._url = base_url.rstrip("/") + ME_PATH
        # `timeout` configures the client this builds; it does **not** apply to one passed in,
        # which arrives carrying its own. Only tests pass `client`, and they pass a MockTransport
        # that never blocks — but the asymmetry is easy to misread, so: if you inject a client,
        # set its timeout on the client.
        self._client = client if client is not None else httpx.Client(timeout=timeout)

    def introspect(self, bearer: str) -> Principal | None:
        try:
            response = self._client.get(
                self._url,
                headers={"Authorization": f"Bearer {bearer}"},
            )
        except httpx.HTTPError as exc:
            # Connection refused, DNS failure, timeout — pandan was not reached, so kaya does not
            # know. `from exc` is safe: httpx puts the URL in its messages, never the headers.
            raise UpstreamUnavailable(f"{self._url} is unreachable") from exc

        if response.status_code in (401, 403):
            return None

        if response.status_code != 200:
            # A 5xx, a redirect to a login page, a proxy error. Any of these means kaya has no
            # answer, and inventing one — in either direction — is worse than saying so.
            raise UpstreamUnavailable(f"{self._url} answered {response.status_code}")

        try:
            body = response.json()
            return Principal(id=uuid.UUID(str(body["id"])), email=str(body["email"]))
        except (ValueError, TypeError, KeyError, httpx.HTTPError) as exc:
            # A 200 kaya cannot read is an outage wearing a success code — most likely a CDN or
            # tunnel interstitial. Never the response body in the message; it is unvetted, and
            # this string reaches an HTTP response.
            raise UpstreamUnavailable(f"{self._url} returned a body kaya could not read") from exc
