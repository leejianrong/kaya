"""Step 1 of ADR 0004's ordering: ``fields`` selection. **A no-op in V2a, on purpose.**

The card is explicit — "V2a implements only the ``fmt`` dimension; ``fields`` and ``text_limit``
exist in the signature and pass through". So this module exists to hold the step's *place* in the
pipeline and its type, and `tests/test_passthrough_is_a_no_op.py` pins that it does nothing, so V2b
arriving is visible as a diff rather than as a subtle change of behaviour nobody can date.

What is validated here is the **shape of the argument**, not its **vocabulary**. That line matters:

- ``fields="ref,title"`` is a ``TypeError``. A bare string is an iterable of characters, so the
  no-op would swallow it today and V2b would project a payload down to ``r``, ``e``, ``f``… The
  split-on-comma is argv's job (the adapter's), and the seam should say so now rather than after
  someone debugs it.
- ``fields=["nope"]`` is **accepted** in V2a. Rejecting an unknown name is V2b's job ("unknown name
  → a clean error naming it"), it needs ``Payload.field_names()`` to already be the vocabulary, and
  doing it now would make the pass-through claim above false.

### One tension V2b has to settle, recorded here so it is met rather than discovered

ADR 0004 §Decision calls this step "projection — ``fields`` selection", motivated by pandan's
measurement that field breadth is what makes an MCP payload cost 44,902 tokens. ADR 0005 §contract 2
says ``--fields`` "widens the human row" and "does not affect structured output, which is already
complete."

Those are not the same operation. The first narrows the shaped dict — which is what recovers the
~84% on the MCP surface. The second only chooses columns for the human table. Both are reachable
from here without touching ``render``'s signature (narrowing means rebuilding ``records``; widening
means ``Payload.with_columns``), and this module can do either. It is V2b's call, and the honest
reading is probably *both*: the CLI's ``--format json`` wants the complete record, and MCP's
``fields`` wants the narrow one — same parameter, and the difference is already legible here
because ``fmt`` is in scope on the same call.
"""

from collections.abc import Sequence

from kaya_client.payloads import Payload


def project(payload: Payload, fields: Sequence[str] | None) -> Payload:
    """Return ``payload`` selected down to ``fields``. In V2a: unchanged, always.

    The identity is exact — the same object, not a copy — so "``fields`` is a no-op" is provable
    with ``is`` rather than with an equality that a future accidental rebuild would still satisfy.
    """
    if not isinstance(payload, Payload):
        raise TypeError("project takes a Payload — it is the first step, before anything shapes it")
    check_fields(fields)
    return payload


def check_fields(fields: Sequence[str] | None) -> None:
    """Reject an argument that could not be a field list, whatever V2b does with one."""
    if fields is None:
        return
    if isinstance(fields, str | bytes):
        raise TypeError(
            "fields must be a sequence of field names, not a string — split the comma-separated "
            "argv value in the adapter"
        )
    if not all(isinstance(name, str) for name in fields):
        raise TypeError("fields must contain only field names")
