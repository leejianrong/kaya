"""What ``render`` is handed, and what the four shaping steps pass between them.

The reason this type exists at all is ADR 0005's sequencing rule. ``render``'s signature is fixed by
ADR 0004 as ``render(payload, *, fields, text_limit, fmt)`` — four parameters, no room for a fifth —
and V2b needs facts about the payload that a raw ``dict`` cannot carry:

- **list or single entity?** ``--fields`` is "a usage error on single-entity verbs, never a silent
  no-op" (ADR 0005 §contract 2). Sniffing for a ``"notes"`` key would work today and break the day
  `/links` and `/backlinks` land (KAN-566) with envelopes nobody taught the sniffer about.
- **which fields are prose?** V2b truncates over "an allow-list of prose fields … rather than a
  length heuristic", because a blanket rule "eventually cuts a ``next_cursor``". The allow-list is
  knowledge of the API's schema, so it belongs next to the client that made the call, not inside a
  formatter.
- **which fields make the default human row?** V2a pins that row byte-identically so V2b's
  ``--fields`` can prove it changed nothing. The row therefore has to be *narrow already*, and its
  columns have to come from somewhere other than "every key in the record" — a note's record carries
  its whole ``body``.

So ``KayaClient`` returns one of these rather than a ``dict``. That is the ADR 0004 rule applied to
its own package: if the client returned a raw dict, every one of the three facts above would have to
be re-derived by whoever formatted it, which is precisely how a shaping rule ends up in an adapter.

``records`` stay **whole**. Nothing here narrows, truncates or reorders; the payload is the complete
API response plus the metadata needed to shape it, and ADR 0004 §Consequences requires that ("the
API returns complete records, since it is what both adapters project from").
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

Record = Mapping[str, Any]


class Kind(StrEnum):
    """Whether the payload describes a set of things or one thing.

    Not derived from ``len(records)``: a collection of exactly one note is still a collection, and
    a `list` verb that happens to return one row must not start behaving like `get`.
    """

    COLLECTION = "collection"
    ENTITY = "entity"


@dataclass(frozen=True)
class Payload:
    """A complete API response, plus what shaping needs to know about it.

    ``envelope_key`` is the API's own key (``{"notes": [...]}``, per PLAN §Implementation
    decisions), so a structured render reproduces the wire shape rather than inventing a second one.
    ``noun`` is the singular, which V2b's ``summary`` line needs for wording.
    """

    kind: Kind
    noun: str
    envelope_key: str
    records: tuple[Record, ...]
    columns: tuple[str, ...]
    """The default human row, in order. V2b's ``--fields`` replaces this set; V2a pins what it
    produces, so "``--fields`` omitted leaves the default row byte-identical" is a checkable claim
    rather than a hope."""

    prose_fields: frozenset[str] = frozenset()
    """V2b's truncation allow-list (ADR 0005: named prose fields, never a length heuristic).
    Unused in V2a — ``truncation.truncate`` is a no-op — but supplied from the first call, so V2b
    adds a step rather than a parameter."""

    @classmethod
    def collection(
        cls,
        *,
        noun: str,
        envelope_key: str,
        records: Iterable[Record],
        columns: Sequence[str],
        prose_fields: Iterable[str] = (),
    ) -> "Payload":
        return cls(
            kind=Kind.COLLECTION,
            noun=noun,
            envelope_key=envelope_key,
            records=tuple(dict(record) for record in records),
            columns=tuple(columns),
            prose_fields=frozenset(prose_fields),
        )

    @classmethod
    def entity(
        cls,
        *,
        noun: str,
        envelope_key: str,
        record: Record,
        columns: Sequence[str],
        prose_fields: Iterable[str] = (),
    ) -> "Payload":
        return cls(
            kind=Kind.ENTITY,
            noun=noun,
            envelope_key=envelope_key,
            records=(dict(record),),
            columns=tuple(columns),
            prose_fields=frozenset(prose_fields),
        )

    @property
    def record(self) -> Record:
        """The sole record of an ``ENTITY`` payload."""
        if self.kind is not Kind.ENTITY:
            raise ValueError(f"{self.noun} payload is a {self.kind}, not a single entity")
        return self.records[0]

    def field_names(self) -> tuple[str, ...]:
        """Every key present in the returned records, in first-seen order.

        ADR 0004: ``--fields``' vocabulary is "derived from the payload's own keys so it cannot
        drift from the API". Derived here rather than in `projection`, because the same vocabulary
        is what an error message has to list, and there should be one answer to "what can I ask
        for?".
        """
        seen: dict[str, None] = {}
        for record in self.records:
            for key in record:
                seen.setdefault(key, None)
        return tuple(seen)

    def with_columns(self, columns: Sequence[str]) -> "Payload":
        """The same records under a different default row. V2b's ``--fields`` lands here."""
        return replace(self, columns=tuple(columns))


@dataclass(frozen=True)
class Shaped:
    """A payload that has been through projection and truncation, with its aggregate attached.

    A separate type from ``Payload``, and that is the whole point rather than bookkeeping. ADR 0005
    requires ``summary`` to be "attached after truncation, so its counts are structurally out of the
    truncator's reach" — and *structurally* is a stronger claim than *by convention*. Because
    ``truncate`` takes and returns a ``Payload`` while ``attach_summary`` returns a ``Shaped``,
    there is no order in which a truncator could reach a summary: by the time one exists, the type
    the truncator accepts is gone. ``tests/test_shaping_order.py`` pins that.

    ``summary`` is ``None`` throughout V2a. V2b fills it, and every serializer below already knows
    where to look.
    """

    payload: Payload
    summary: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        """**The** shaped dict — the one thing all four serializers render from (ADR 0004 §4).

        A collection reproduces the API's envelope; an entity is the bare object. That is PLAN's
        fixed shape, not a choice made here, and it is why `--format json` output is something a
        caller can feed straight back to the API's own contract.
        """
        if self.payload.kind is Kind.COLLECTION:
            shaped: dict[str, Any] = {
                self.payload.envelope_key: [dict(record) for record in self.payload.records]
            }
        else:
            shaped = dict(self.payload.record)

        if self.summary is not None:
            shaped["summary"] = dict(self.summary)
        return shaped
