"""Step 2 of ADR 0004's ordering: prose truncation. **A no-op in V2a, on purpose.**

Same deal as `projection`: the step's place and type land now, the behaviour lands in V2b, and
`tests/test_passthrough_is_a_no_op.py` pins the difference so V2b shows up as a diff.

What V2b puts here is already decided and does not need this signature to change:

- the allow-list is ``payload.prose_fields``, supplied by ``KayaClient`` because it is knowledge of
  the API's schema. ADR 0005 is emphatic that it is *named fields*, never a length heuristic — "a
  blanket rule eventually cuts a ``next_cursor`` and silently breaks pagination, or mangles a URL".
- the hint carries a **true** total, which is available because ``records`` arrive whole.
- ``--full`` is ``text_limit=0``, and ``0`` disables. That is why the parameter is an ``int`` and
  not an ``int | None``: "no limit" already has a spelling, and a second one would be two ways to
  say the same thing that a config layer would eventually disagree about.
- ``KAYA_MAX_TEXT_CHARS`` is read by the *adapter's* config layer and arrives here as a number.
  Reading an environment variable inside the shaping step would make the same payload render
  differently depending on the process, which is the kind of thing a test cannot pin.

A truncated value stays a string, and no key is added, removed or retyped (ADR 0005 §contract 6).
"""

from kaya_client.payloads import Payload

DEFAULT_TEXT_LIMIT = 500
"""ADR 0005 §contract 6 and SLICES §V2b. Named here rather than written into ``render``'s default,
so the number has one home when V2b's config layer needs to report "the effective value"."""


def truncate(payload: Payload, text_limit: int) -> Payload:
    """Return ``payload`` with prose fields cut to ``text_limit``. In V2a: unchanged, always.

    Refusing a non-``Payload`` is what turns ADR 0005's "``summary`` is attached after truncation,
    structurally out of the truncator's reach" from a convention into a fact: once `aggregates` has
    produced a ``Shaped``, this function will not accept it.
    """
    if not isinstance(payload, Payload):
        raise TypeError(
            "truncate takes a Payload — a summary is attached after truncation and is not "
            "reachable from here (ADR 0005)"
        )
    check_text_limit(text_limit)
    return payload


def check_text_limit(text_limit: int) -> None:
    """A character count. ``0`` disables; negative is a caller bug, not "extra disabled"."""
    if isinstance(text_limit, bool) or not isinstance(text_limit, int):
        raise TypeError("text_limit must be an int number of characters")
    if text_limit < 0:
        raise ValueError("text_limit must be >= 0 — 0 disables truncation")
