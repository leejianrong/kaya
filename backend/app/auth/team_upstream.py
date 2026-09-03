"""The one place kaya talks to pandan about team membership.

Mirrors `app/auth/upstream.py`'s shape for identity, behind a `Protocol` for the same reason: faking
at this boundary is what keeps "pandan is down", "the caller belongs to no teams" and "the caller
belongs to several" all reachable in the unit layer with no network.

The contract (pandan ADR 0021, `backend/app/routers/teams.py`):

    GET /api/v1/teams, Authorization: Bearer <pat>
        ->  200 [{"id": <int>, "name": ..., "role": ...}, ...]

scoped server-side to the teams the bearer's owner is a member of. Only `id` is read here. `name`
and `role` are pandan's business — mirroring either into kaya would be exactly the staleness
`app/models/team.py`'s module docstring argues against, and neither is needed to answer "is this
note's team one the caller belongs to?". **`id` is an integer, not a UUID** — pandan's own `Team.id`
is a `BigInteger` (`app/models/team.py`'s docstring has the full argument), unlike its `User.id`.
"""

from typing import Protocol

import httpx

from app.auth.principal import UpstreamUnavailable

TEAMS_PATH = "/api/v1/teams"
"""Pandan's team-list endpoint (ADR 0021), scoped server-side to the caller's own memberships."""


class TeamMembershipUpstream(Protocol):
    """Resolves a bearer to the set of team ids its owner belongs to."""

    def member_teams(self, bearer: str) -> frozenset[int]:
        """The caller's team ids — zero is a legitimate, common answer, not a rejection.

        Raise `UpstreamUnavailable` when pandan could not be asked. There is no rejection case to
        represent here the way `IdentityUpstream.introspect` has one: a bearer only ever reaches
        this call after ADR 0002's resolver has already accepted it, so a `401`/`403` from this
        endpoint would be pandan disagreeing with itself moments later — treated as
        `UpstreamUnavailable` rather than invented a third outcome to carry.
        """
        ...


class PandanTeamUpstream:
    """`TeamMembershipUpstream` over real HTTP. The bearer is forwarded byte-for-byte, unparsed —
    same discipline as `PandanIdentityUpstream`, for the same reason (ADR 0002: pandan owns the
    token format)."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: httpx.Timeout | float,
        client: httpx.Client | None = None,
    ) -> None:
        self._url = base_url.rstrip("/") + TEAMS_PATH
        self._client = client if client is not None else httpx.Client(timeout=timeout)

    def member_teams(self, bearer: str) -> frozenset[int]:
        try:
            response = self._client.get(
                self._url,
                headers={"Authorization": f"Bearer {bearer}"},
            )
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(f"{self._url} is unreachable") from exc

        if response.status_code != 200:
            # Includes 401/403 — see the Protocol docstring for why those are not distinguished
            # from any other failure to answer here.
            raise UpstreamUnavailable(f"{self._url} answered {response.status_code}")

        try:
            body = response.json()
            return frozenset(int(row["id"]) for row in body)
        except (ValueError, TypeError, KeyError, httpx.HTTPError) as exc:
            # A 200 kaya cannot read is an outage wearing a success code, same reasoning as
            # `PandanIdentityUpstream` — never the response body in the message.
            raise UpstreamUnavailable(f"{self._url} returned a body kaya could not read") from exc
