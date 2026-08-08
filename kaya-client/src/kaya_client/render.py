"""The one seam. Everything both adapters print comes out of this function.

ADR 0004 fixes the signature and the ordering, and this module is four lines of pipeline plus the
argument for why those four lines are all there is. The concerns live in `projection`, `truncation`,
`aggregates` and `serialization` — separate composable steps with their own tests, which is ADR
0004's own stated mitigation for the risk it flags against itself ("``render`` is a single function
accumulating four concerns, which is how a god function starts"). V2b fills three of those modules
and does not touch this one.

### The signature, and why each of V2b's requirements lands on it unchanged

    render(payload, *, fields=None, text_limit=500, fmt="human") -> str | dict

ADR 0005's sequencing rule says this signature has to absorb V2b without moving. Taking V2b's build
plan item by item:

- **``--fields a,b,c``, vocabulary from the payload's own keys.** ``fields`` is here; the vocabulary
  is ``Payload.field_names()``, which is already derived from the records rather than from a list
  somebody maintains.
- **An unknown field name errors, naming it.** Needs the vocabulary, which is in scope inside
  `projection`. No new argument.
- **``--fields`` is a usage error on a single-entity verb.** This is the requirement that would have
  forced a signature change, and it is why ``payload`` is a ``Payload`` and not a ``dict``:
  ``payload.kind`` answers it. Had the client returned a raw dict, ``render`` would have to be told
  which it was — a fifth parameter, added in V2b, which is exactly the failure ADR 0005 describes.
- **Truncation over an allow-list, with a true total.** ``text_limit`` is here; the allow-list is
  ``payload.prose_fields``; the true total is available because ``records`` arrive whole.
- **``--full``** is ``text_limit=0``, and **``KAYA_MAX_TEXT_CHARS``** is the adapter's config
  resolving to the same integer. Neither is a new parameter.
- **A ``summary`` describing the returned set, attached after truncation.** Computed inside
  `aggregates`, from the records this call actually returned — not by the caller, and not passed in.
  The ordering below is what makes "after truncation" true, and the ``Payload``/``Shaped`` type
  split is what makes it unfalsifiable.

The one thing V2b will find missing is deliberate: there is no ``full=True`` flag, because ADR
0005's ``--full`` already has a spelling here (``text_limit=0``) and two spellings of one state is
how a config layer ends up disagreeing with a flag.

### When it returns a ``str`` and when a ``dict``

``fmt="data"`` returns the shaped dict; every other format returns a string. ``data`` is
adapter-facing — it lives in ``AdapterFormat``, not in the user-facing ``Format``, so it is not a
``--format`` value and cannot become one by someone iterating the wrong enum for an argparse
``choices`` list. See `serialization`'s module docstring for why it exists at all. Both halves are
pinned in ``tests/test_serialization.py``.
"""

from collections.abc import Sequence
from typing import Any

from kaya_client.aggregates import attach_summary
from kaya_client.payloads import Payload
from kaya_client.projection import project
from kaya_client.serialization import Format, serialize
from kaya_client.truncation import DEFAULT_TEXT_LIMIT, truncate


def render(
    payload: Payload,
    *,
    fields: Sequence[str] | None = None,
    text_limit: int = DEFAULT_TEXT_LIMIT,
    fmt: str = Format.HUMAN,
) -> str | dict[str, Any]:
    """Shape ``payload`` and serialize it. The only way anything leaves this package as output.

    In V2a ``fields`` and ``text_limit`` are validated for shape and then pass through untouched;
    ``tests/test_passthrough_is_a_no_op.py`` proves it, so V2b's arrival is a visible diff.
    """
    if not isinstance(payload, Payload):
        raise TypeError(
            "render takes a Payload from KayaClient, not a raw response body — a client that "
            "returned a dict for an adapter to format is the mistake ADR 0004 exists to prevent"
        )

    projected = project(payload, fields)
    truncated = truncate(projected, text_limit)
    shaped = attach_summary(truncated)
    return serialize(shaped, fmt)
