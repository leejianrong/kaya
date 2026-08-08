"""Step 3 of ADR 0004's ordering: the ``summary``. **Attaches nothing in V2a, on purpose.**

The step that matters structurally even while it is empty. ADR 0005 adopts pandan's correction as a
rule — "``summary`` is attached **after** truncation, so its counts are structurally out of the
truncator's reach" — and this module is where *structurally* is bought: it takes a ``Payload`` and
returns a ``Shaped``, and nothing downstream of it accepts a ``Payload`` again. A truncator cannot
reach a summary because by the time one exists there is no ``Payload`` left to hand it.

V2b computes the counts here, from ``payload.records``, which are the rows **actually returned** —
"under a filter or ``--limit``, the returned set, not the whole corpus" (ADR 0005 §contract 5). Note
that this is true by construction rather than by care: this function is handed the returned set and
has no access to a corpus, so the tempting wrong answer is not reachable from inside it.

An ``ENTITY`` payload gets no summary: a summary describes a returned *set*, and one note is not a
set of anything. That stays true in V2b.
"""

from kaya_client.payloads import Payload, Shaped


def attach_summary(payload: Payload) -> Shaped:
    """Wrap the shaped payload with its aggregate. In V2a the aggregate is always ``None``."""
    return Shaped(payload=payload, summary=None)
