"""ADR 0011's team-default access check, and its soft-fail decision, fully contained in one place.

Mirrors `app/auth/resolver.py`'s shape for identity — cache, single-flight, upstream, the same
double-checked miss path — with one deliberate difference. Where `PrincipalResolver.resolve`
propagates `UpstreamUnavailable` so ADR 0002's *hard* dependency on pandan becomes a `503`,
`TeamAccessResolver.member_of` never lets that exception escape at all: ADR 0011, Fork 3, decided
this dependency is soft. A note's owner is never gated on this call succeeding, and a teammate's
access to a team-shared note simply doesn't show up rather than erroring. **Nothing above this
class ever sees `UpstreamUnavailable` from a team-membership check** — asserted, not assumed, in
`tests/unit/test_team_resolver.py`.

Uses its own `SingleFlight` and `TeamMembershipCache` instances (`app/auth/dependencies.py`),
never identity's — a stampede on one bearer's team check must not queue behind, or coalesce with,
a stampede on that same bearer's identity check; they are different calls to different pandan
endpoints and have no business sharing a registry.
"""

from app.auth.principal import UpstreamUnavailable
from app.auth.single_flight import SingleFlight
from app.auth.team_cache import TeamMembershipCache, digest
from app.auth.team_upstream import TeamMembershipUpstream


class TeamAccessResolver:
    """Bearer in, the caller's team ids out — always, never raises.

    Three injected collaborators, same testability argument as `PrincipalResolver`: the whole of
    ADR 0011's soft-fail decision runs in a unit test against in-memory fakes, no network.
    """

    def __init__(
        self,
        *,
        upstream: TeamMembershipUpstream,
        cache: TeamMembershipCache,
        single_flight: SingleFlight,
    ) -> None:
        self._upstream = upstream
        self._cache = cache
        self._single_flight = single_flight

    def member_of(self, bearer: str) -> frozenset[int]:
        """The team ids `bearer`'s owner belongs to, or an empty set if that can't be known right
        now. Never raises — see the module docstring."""
        hit, cached = self._cache.lookup(bearer)
        if hit:
            return cached if cached is not None else frozenset()

        return self._single_flight.do(digest(bearer), lambda: self._introspect(bearer))

    def _introspect(self, bearer: str) -> frozenset[int]:
        """The uncached path, run by exactly one thread per bearer at a time.

        Never raises: a failure is caught here and converted into "no memberships known", cached
        under the negative TTL, and returned like any other answer. `SingleFlight` hands every
        waiter this same return value — there is no exception to re-raise to them, unlike
        `PrincipalResolver`'s Q9 case, because ADR 0011 made that choice on purpose.
        """
        # The double-check, same reason `PrincipalResolver._introspect` has one: a thread can miss
        # the cache, lose the single-flight race to a leader that finishes in the meantime, and
        # arrive here as a brand-new leader for an answer that is already cached.
        hit, cached = self._cache.lookup(bearer)
        if hit:
            return cached if cached is not None else frozenset()

        try:
            teams = self._upstream.member_teams(bearer)
        except UpstreamUnavailable:
            self._cache.remember(bearer, None)
            return frozenset()

        self._cache.remember(bearer, teams)
        return teams
