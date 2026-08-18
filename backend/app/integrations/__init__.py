"""Kaya's read-only calls to a *sibling* app's public API, made with the caller's own credential.

Distinct from ``app/auth/``, deliberately: that package owns the token itself — ADR 0002's
resolver, `app/auth/cache.py`'s digest-keyed cache, and `test_no_token_prefix_logic.py`'s blanket
ban on `.startswith`/`.endswith`/etc. anywhere under it, because *any* prefix inspection there is
suspicious until proven otherwise. `card_resolution.py` forwards the same bearer, but it never
inspects the bearer's own shape — the `.startswith("KAN-")` inside it classifies a **ticket ref**
a wikilink already carries, the identical distinction `app/wikilinks.py` makes for the same
prefixes outside `app/auth/`. Keeping this package one level away from `app/auth/` is what lets
that guard stay blunt rather than growing an exception clause for "prefix checks that aren't about
the token," which is exactly the kind of carve-out that erodes a structural guard over time.
"""
