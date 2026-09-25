"""What a caller *is*, kept in its own module so ``authorization.py`` depends on a type rather than
on how one gets resolved.

``Principal`` carried exactly what pandan's ``GET /api/v1/me`` returned before ADR 0012's cutover
(KAN-1740); it now carries the same two fields sourced from kaya's own ``KayaAccount`` instead
(``app/auth/kaya_principal.py``). Keeping the shape identical is what let ``authorization.py``,
``app/api/notes.py`` and everything downstream of ``get_principal`` stay untouched by the cutover —
they read a UUID and an email, and neither cares where either came from.
"""

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Principal:
    """A resolved caller. ``id`` is a ``KayaAccount``'s own id (ADR 0012) — before KAN-1740's
    cutover this was pandan's UUID instead; existing notes' `owner_id` still points at the old
    pandan-mirror `user` table (`app/models/user.py`, ADR 0002) and is not reachable under a new
    `KayaAccount` id. That is a deliberate, accepted cutover cost — see
    `docs/roadmap/BREADBOARD.md`'s R19 section — not something this dataclass, or anything else in
    this module, tries to paper over."""

    id: uuid.UUID
    email: str


class UpstreamUnavailable(Exception):
    """Pandan could not be asked, so kaya does not know and says so.

    No longer raised by anything in this package — ``kaya_principal.py``'s resolution is a local
    database lookup with no upstream to be unavailable. Still raised by the *unrelated* stacks that
    still call pandan over HTTP: `app/auth/team_upstream.py` (team-default access, ADR 0011),
    `app/integrations/card_resolution.py` (wikilink resolution) and
    `app/integrations/board_embed.py` (the pandan-board embed) — each catches it and degrades
    gracefully per its own ADR, never a `401`, because in every one of those cases the credential is
    fine and the *upstream* is what failed to answer.
    """
