"""``sha256(token)``, the shared cache/single-flight key — split into its own module (KAN-1740).

Before ADR 0012's cutover this lived in ``app/auth/cache.py`` (``PrincipalCache``'s own key
function), and ``team_cache.py``/``card_resolution.py`` imported it from there rather than
reimplementing a two-line pure function. Now that the identity cache it was born beside is retired
(kaya no longer introspects a bearer against pandan, so there is nothing left to cache the answer
to), the function itself is not: `team_cache.py` and `app/integrations/card_resolution.py` still
key their own, unrelated caches on a digest, for the identical reason the original docstring gave —
a heap dump, a `repr()` in a traceback, or a debugger session must not yield a live credential.
"""

import hashlib


def digest(token: str) -> str:
    """The cache key for a token, and the only place a raw token is read in this module."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
