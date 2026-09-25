"""``split_timeout``, shared by every place kaya still calls pandan over HTTP — split out of
``app/auth/upstream.py`` (KAN-1740's deletion of that module).

Team-membership lookups (``app/auth/team_upstream.py``), card/epic wikilink resolution
(``app/integrations/card_resolution.py``), and the pandan-board embed
(``app/integrations/board_embed.py``) all still call pandan and all still want the same two-phase
budget this function builds — only *identity* resolution (ADR 0002's introspection, retired by ADR
0012) stopped needing it. A top-level module rather than a home inside any one of those three
integrations, because none of them is entitled to own a helper the other two also depend on.
"""

import httpx


def split_timeout(*, connect: float, read: float) -> httpx.Timeout:
    """The deadline for one pandan call, as two budgets rather than one (KAN-666).

    A single number cannot be right for both of pandan's failure modes, because they are not the
    same failure. **Down** shows up in the connect phase — nothing answers on port 443, or nothing
    resolves — and wants a short deadline so a caller's own `503`/soft-fail is prompt. **Asleep**
    shows up entirely in the read phase: fly's edge proxy completes the TCP and TLS handshakes on
    its own while the app machine boots behind it, so the connection is established in the usual
    few tens of milliseconds and then nothing comes back for twenty seconds. Measured on identity's
    own introspection call before ADR 0012 retired it (KAN-666); the shape of the failure is
    unchanged for every pandan call that remains, even though the script that measured it
    (`scripts/measure_introspection_latency.py`) went with the call it measured.

    `write` and `pool` take the connect budget rather than the read one. The request is one small
    segment, so a `write` that blocks past the connect budget is a broken socket rather than a busy
    pandan; and `pool` is contention for a local connection slot, which has nothing to do with how
    awake the upstream is. Neither is left to httpx's default, because `httpx.Timeout` requires all
    four to be given once any of them is, and a phase nobody thought about is how one of these ends
    up unbounded.
    """
    return httpx.Timeout(connect=connect, read=read, write=connect, pool=connect)
