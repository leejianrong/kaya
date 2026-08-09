"""Step 2 of ADR 0004's ordering: prose truncation. **Live since KAN-547.**

V2a held this module's place and pinned that it did nothing, so V2b would arrive as a visible diff
rather than as a change of behaviour nobody can date. This is that diff, and it is the second half
of the one `projection` spent: `tests/test_passthrough_is_a_no_op.py` is gone, because after this
card neither parameter passes anything through and a file named for a no-op would be a lie a reader
trusts. Its ``text_limit`` assertions are below, its ``fields`` ones are in `tests/test_projection`.

Everything V2a wrote down here has landed unchanged, which is the sequencing rule paying out —
``render``'s signature did not move for this card either:

- **the allow-list is ``payload.prose_fields``**, supplied by ``KayaClient`` because it is knowledge
  of the API's schema. ADR 0005 is emphatic that it is *named fields*, never a length heuristic —
  "a blanket rule eventually cuts a ``next_cursor`` and silently breaks pagination, or mangles a
  URL". For a note the list is ``{"body"}``: ``title`` and ``path`` are ``String(255)`` and
  ``String(1024)``, bounded by the schema, and pass through at any length.
- **the hint carries a true total**, available because ``records`` arrive whole (ADR 0004
  §Consequences). It is the length of the value the API returned, never the length of what is left
  after the cut, and `tests/test_truncation.py` states that as its own assertion because the wrong
  one is the easy one to write.
- **``--full`` is ``text_limit=0``**, and ``0`` disables. That is why the parameter is an ``int``
  and not an ``int | None``: "no limit" already has a spelling, and a second one would be two ways
  to say the same thing that a config layer would eventually disagree about.
- **``KAYA_MAX_TEXT_CHARS`` is resolved by `config.max_text_chars`** and arrives here as a number.
  Reading an environment variable inside the shaping step would make the same payload render
  differently depending on the process, which is the kind of thing a test cannot pin.

### The hint is **in-band**, and that is the decision this card had to make

A truncated ``body`` is ``"…the first `text_limit` characters…\\n\\n(truncated, 2847 chars total —
use --full to see complete body)"``. The hint is part of the string, not a second key and not
something the ``human`` serializer appends on its way past.

The alternative — a human-only hint, with structured output carrying a silently shortened string —
fails on ADR 0005 §contract 6 read as a whole rather than clause by clause. Contract 6 asks for two
things at once: a **true total**, and **no key added, removed or retyped**. Under a human-only hint
the total does not exist by the time ``human`` could print it, because truncation is step 2 and
serialization is step 4; the only ways to carry it forward are a new key (which contract 6 forbids
in the same sentence) or truncating inside the serializer (which is ADR 0004's rule, broken, and
would put a shaping decision in the step that branches on format). In-band is what is left, and it
is also the only reading under which the promise is kept to the audience that needs it: an agent on
``--format json`` can otherwise not distinguish a 500-char note from a truncated 3,000-char one, so
"a true total" would be a promise kept only to the reader who could have counted.

It costs one thing, honestly: a consumer that wants the prose alone gets the hint with it. The
answer is ``--full``, which is exactly the flag contract 6 pairs with the total. The sibling tool
does the same — `pandan get KAN-716` prints its hint inside the description text — and pandan's V45
is the slice §contract 6 was derived from.

**One string, two renderings, no rule in the formatter.** `serialization._entity` prints prose
unlabelled and last, so the hint lands after a blank line without disturbing a byte of the label
block above it; `serialization._cell` collapses whitespace, so the same value in a
``--fields ref,body`` table is one line and the grid stays aligned. Neither formatter knows this
module exists.

### What the multi-byte guarantee actually is

**Code points, not grapheme clusters.** ``str[:n]`` slices by code point, so no cut can produce a
lone surrogate, a broken UTF-8 sequence or a replacement character, and the count in the hint is the
same unit ``text_limit`` is expressed in. A cut *can* fall inside a grapheme cluster — between a
letter and its combining accent, inside a ZWJ emoji sequence, between a base emoji and its skin-tone
modifier — and `tests/test_truncation.py` demonstrates exactly that rather than hiding it. Fixing it
needs a UAX #29 segmentation table, which is a dependency, and ``kaya-client`` has exactly one
runtime dependency (SLICES §V2a). Claiming clusters while implementing code points would be worse
than the honest narrower claim.
"""

from kaya_client.payloads import Payload, Record

DEFAULT_TEXT_LIMIT = 500
"""ADR 0005 §contract 6 and SLICES §V2b. Named here rather than written into ``render``'s default,
so the number has one home — `config.max_text_chars` reads it as the value ``KAYA_MAX_TEXT_CHARS``
falls back to, and KAN-551's ``config show`` reports whatever that resolves to."""

HINT_SEPARATOR = "\n\n"
"""A blank line between the cut prose and the hint.

Markdown's own paragraph break, so a truncated note is still a valid document, and the thing that
makes the hint read as a footer rather than as a sentence the author wrote. In a table cell it is
collapsed to one space by `serialization._cell` along with every other run of whitespace, which is
why this module does not need to know whether it is rendering a row or a block."""

FULL_SPELLING = "--full"
"""How the hint tells a reader to get the whole value back.

**A known tension, recorded rather than guessed at.** `projection` states the rule that a message
written in this package names "the parameter they share, never a flag's spelling", because an MCP
caller has no ``--flag`` to drop. That rule is about *refusals*, which are addressed to whoever made
the mistake; this is rendered content, and SLICES §V2b's demo line fixes its wording verbatim —
``(truncated, 2847 chars total — use --full to see complete body)`` — as an acceptance criterion.
The CLI is also the only surface that exists today. So the demo's wording ships, and the spelling is
a constant because V6 is where it stops being right: an MCP tool's caller sets ``text_limit=0``, and
the tool that renders for it is the thing that should decide how to say so. One string to change,
named here, rather than an f-string buried in a function."""


def truncate(payload: Payload, text_limit: int) -> Payload:
    """Return ``payload`` with its prose fields cut to ``text_limit``, each carrying a true total.

    Only fields named by ``payload.prose_fields`` are considered, only when the value is a ``str``,
    and only when it is *longer* than the limit — a value of exactly ``text_limit`` characters is
    not truncated, because it is not. That is the mechanism behind "under-limit output is
    byte-identical": a payload with nothing over the limit comes back as **the same object**, so the
    claim is about identity rather than about two renders that happen to agree.

    Refusing a non-``Payload`` is what turns ADR 0005's "``summary`` is attached after truncation,
    structurally out of the truncator's reach" from a convention into a fact: once `aggregates` has
    produced a ``Shaped``, this function will not accept it.

    Records are **rebuilt, never edited**. The payload is the complete API response (ADR 0004
    §Consequences) and the caller may still hold it; a truncator that mutated in place would make
    ``--full`` unsatisfiable, because the untruncated text would be gone by the time anything asked.
    """
    if not isinstance(payload, Payload):
        raise TypeError(
            "truncate takes a Payload — a summary is attached after truncation and is not "
            "reachable from here (ADR 0005)"
        )
    check_text_limit(text_limit)
    if text_limit == 0 or not payload.prose_fields:
        return payload

    cut = [_cut_record(record, payload.prose_fields, text_limit) for record in payload.records]
    if all(after is before for after, before in zip(cut, payload.records, strict=True)):
        return payload
    return payload.with_records(cut)


def _cut_record(record: Record, prose_fields: frozenset[str], text_limit: int) -> Record:
    """One record with its over-limit prose cut. The same record object if nothing was over.

    Key order is the record's own and every key survives: ADR 0005 §contract 6's "no key added,
    removed or retyped" is a property of this comprehension, and `tests/test_truncation.py` asserts
    it against the record rather than against a rendering, because a serializer could hide it.
    """
    cut = {
        name: truncate_text(value, text_limit, name)
        if name in prose_fields and isinstance(value, str)
        else value
        for name, value in record.items()
    }
    return record if cut == record else cut


def truncate_text(text: str, text_limit: int, field: str) -> str:
    """``text`` cut to ``text_limit`` characters plus the hint, or ``text`` itself if it fits.

    The returned value's first ``text_limit`` characters are byte-for-byte the original's, with no
    stripping and no ellipsis substituted into the prose. A caller that wants the leading text back
    can slice for it, and a cut that quietly dropped a trailing space would make that false.
    """
    if text_limit == 0 or len(text) <= text_limit:
        return text
    return f"{text[:text_limit]}{HINT_SEPARATOR}{hint(len(text), field)}"


def hint(total: int, field: str) -> str:
    """SLICES §V2b's line, verbatim, with the **true** total — the length before the cut.

    ``field`` is named rather than hard-coded to ``body`` because the allow-list is a set: KAN-566's
    ``/links`` and any later unbounded ``TEXT`` column join it without this sentence becoming wrong
    about which value the reader is looking at.
    """
    return f"(truncated, {total} chars total — use {FULL_SPELLING} to see complete {field})"


def check_text_limit(text_limit: int) -> None:
    """A character count. ``0`` disables; negative is a caller bug, not "extra disabled"."""
    if isinstance(text_limit, bool) or not isinstance(text_limit, int):
        raise TypeError("text_limit must be an int number of characters")
    if text_limit < 0:
        raise ValueError("text_limit must be >= 0 — 0 disables truncation")
