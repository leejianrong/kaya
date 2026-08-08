"""The one place a credential is taken out of anything on its way to a log line.

ADR 0002's whole point is that kaya never *holds* a live credential: it forwards the caller's
bearer to pandan and keeps only ``sha256(raw)``, so a heap dump or a stray log line cannot yield
something an attacker can replay. Adding request logging is the single most likely way that
promise gets broken, and the ways it breaks are all boring:

- an ``Authorization`` header logged along with the rest of the headers, because logging *all* the
  headers is one line shorter than choosing which ones;
- a ``repr()`` of a request or an ``httpx`` object that carries its headers inside it;
- an exception whose message was built with an f-string over the thing that failed.

None of those are prevented by care at the call site, because the call site that does it will be
written by someone who has not read this module. So the rule is applied **at serialization**:
``app.observability.logs.JsonFormatter`` passes its whole assembled payload through ``scrub``
immediately before ``json.dumps``, and there is no other way for a record to reach stdout. A field
added to a log line next year is scrubbed without anyone remembering that this file exists — the
same reasoning that put ref resolution in one resolver (ADR 0008) and payload shaping behind one
``render()`` seam (ADR 0004).

**Two layers, and it matters which one is the guarantee.** The structural layer is primary:
``app.observability.middleware`` logs a fixed allowlist of fields, and no header is in it, so
nothing derived from a credential is ever assembled in the first place. This module is the
*backstop* for the three accidents above, and a backstop has a shape it can recognise. It knows
credential-flavoured syntax — a sensitive header name followed by a value, a ``Bearer `` scheme,
this suite's own PAT prefixes. It cannot know that some bare eight-character fragment used to be
part of a token, because knowing that would require holding the token to compare against, which is
exactly what ADR 0002 forbids. That gap is why
``tests/unit/test_log_redaction.py`` asserts against every contiguous fragment of a fake token
rather than against the whole string: the test's job is to prove kaya never emits a fragment,
because a fragment is the one thing this file could not clean up afterwards.

The PAT-prefix rule below is deliberately the same shape as ``.gitleaks.toml``'s ``kayatoast-pat``.
One suite, two prefixes still live (pandan ADR 0018 kept ``kanban_pat_`` accepted after the
rebrand), and the same answer in the scanner that guards the repository and the scrubber that
guards the logs.
"""

import re
from collections.abc import Mapping
from typing import Any

REDACTED = "[redacted]"

SENSITIVE_HEADERS = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "x-auth-token",
    }
)
"""Header names whose *value* is never printable, matched case-insensitively.

``cookie`` and ``set-cookie`` are here even though kaya's API is bearer-only and sets no cookie
(ADR 0002). They cost nothing, and the SPA sharing this origin (ADR 0010) is exactly the kind of
change that quietly introduces one.
"""

MAX_DEPTH = 6
"""How far ``scrub`` will walk before giving up on a structure.

A log payload is a handful of scalars and at most a nested dict. Anything deeper is a mistake
worth truncating rather than a structure worth serializing — and an unbounded walk over a
self-referential object would hang the request that logged it.
"""

_HEADER_ASSIGNMENT = re.compile(
    # A sensitive header name, then whatever punctuation the surrounding format used to attach a
    # value to it — `Authorization: Bearer x`, `'authorization': 'Bearer x'`, `authorization=x`.
    # The value runs to the first delimiter that could plausibly end it, so a redaction inside a
    # `repr()` of a dict removes one value rather than the rest of the line.
    r"(?i)((?:"
    + "|".join(sorted(SENSITIVE_HEADERS))
    + r")['\"]?\s*[:=]\s*['\"]?)[^\r\n,;}\)\]'\"]+"
)

_BEARER_SCHEME = re.compile(r"(?i)\bbearer\s+[^\r\n\s,;}\)\]'\"]+")

_SUITE_PAT = re.compile(r"\b(?:pandan_pat_|kanban_pat_|kaya_pat_)[A-Za-z0-9_-]+")
"""This suite's PAT shapes, for a token logged bare with no header and no scheme around it.

Unlike ``.gitleaks.toml``'s rule there is no ``{20,}`` tail requirement and no allowlist for
documented placeholders. gitleaks has to stay quiet about the prose that explains the prefix, or
the gate fails on its own repository. A log line has no such duty: over-redacting the string
``pandan_pat_example`` in a log costs nothing, and requiring twenty characters would let a
*truncated* token through, which is the failure mode this rule exists for.
"""


TRIGGERS = tuple(sorted(SENSITIVE_HEADERS)) + ("bearer", "_pat_")
"""Substrings without which none of the three patterns above can possibly match.

A pre-filter, and it earns the extra concept because of where this runs. Every string in every log
record goes through ``scrub_text`` — for one access line that is nine keys and nine values, three
regex substitutions each. Formatting one access line cost **44 µs** that way; with this early
return and the ``isinstance`` ordering in ``scrub`` it is **28 µs**. Not free, but no longer real
money against a request that otherwise does one indexed Postgres read, and observability that makes
every request measurably slower is observability somebody turns off.

**Derived, not typed out**, which is the only reason it is safe. Every entry of
``SENSITIVE_HEADERS`` is here by construction, so adding a header name later cannot leave the fast
path silently skipping it — a hand-maintained list would fail by quietly ceasing to scrub, which is
worse than no scrubber at all because it still looks present. The two hand-written entries cover
the patterns that are not header names: ``bearer`` for the scheme, ``_pat_`` for the substring
common to all three of this suite's prefixes.
``test_the_fast_path_cannot_skip_anything_the_patterns_match`` runs both paths over a corpus and
requires them to agree.
"""


def scrub_text(value: str) -> str:
    """Every credential shape this module can recognise, removed from one string."""
    lowered = value.lower()
    if not any(trigger in lowered for trigger in TRIGGERS):
        return value

    value = _HEADER_ASSIGNMENT.sub(lambda m: m.group(1) + REDACTED, value)
    value = _BEARER_SCHEME.sub("Bearer " + REDACTED, value)
    return _SUITE_PAT.sub(REDACTED, value)


def scrub(value: Any, *, depth: int = 0) -> Any:
    """A log payload with credentials removed, and with **nothing left that is not JSON-native**.

    The second half is not a convenience. ``json.dumps`` falls back to ``default=`` for anything it
    does not recognise, and the obvious ``default=str`` would print the ``repr()`` of an object
    this function never inspected — an ``httpx.Request``, say, which carries its headers. So every
    leaf that is not a string, a number, a bool or ``None`` is turned into its ``repr()`` *here*,
    where it goes through ``scrub_text`` on the way. The formatter's ``default=`` then becomes
    genuinely unreachable, which is what makes it safe for it to refuse rather than guess.
    """
    if depth > MAX_DEPTH:
        return "[truncated]"

    # Ordered by how often each case is hit, and the `isinstance` forms are the tuple ones rather
    # than PEP 604 unions on purpose: `isinstance(x, bool | int | float)` goes through
    # `types.UnionType.__instancecheck__` and measured 2× the tuple, `isinstance(x, Sequence)`
    # walks the ABC registry and measured 17× `isinstance(x, str)`. This function runs on every
    # key and every value of every log record, so the difference is a fifth of the per-line cost.
    if isinstance(value, str):
        return scrub_text(value)

    if value is None or isinstance(value, (bool, int, float)):
        return value

    if isinstance(value, Mapping):
        return {
            # The key is scrubbed too. It is nearly always a field name, but a mapping keyed on
            # something a caller supplied is not exotic, and a key is as printable as a value.
            scrub_text(str(key)): (
                REDACTED
                if str(key).lower() in SENSITIVE_HEADERS
                else scrub(item, depth=depth + 1)
            )
            for key, item in value.items()
        }

    # The four concrete container types, not `collections.abc.Sequence`. A custom sequence falls
    # through to the `repr()` below, which is the safe direction: its `repr` is scrubbed, whereas
    # iterating something whose `__iter__` has opinions is how a log call becomes a side effect.
    if isinstance(value, (list, tuple, set, frozenset)):
        return [scrub(item, depth=depth + 1) for item in value]

    # Everything else — bytes, a datetime, a UUID, an exception, a Starlette `Headers` object.
    return scrub_text(repr(value))
