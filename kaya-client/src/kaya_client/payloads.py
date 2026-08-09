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

``records`` arrive **whole**. Nothing *constructs* a narrowed payload here; the payload a
``KayaClient`` method returns is the complete API response plus the metadata needed to shape it, and
ADR 0004 §Consequences requires that ("the API returns complete records, since it is what both
adapters project from"). Narrowing is a later, explicit act — `narrowed_to`, called by `projection`
when and only when a caller asked for ``fields`` — and it returns a *new* payload, so the complete
one is still there for anything that needs it.
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
    """The default human row, in order. ``--fields`` replaces this set (KAN-546); V2a pinned what it
    produces, so "``--fields`` omitted leaves the default row byte-identical" is a checkable claim
    rather than a hope."""

    prose_fields: frozenset[str] = frozenset()
    """The truncation allow-list (ADR 0005: named prose fields, never a length heuristic). Read by
    `truncation.truncate` since KAN-547, and supplied from the very first call, which is why that
    card added a step rather than a parameter.

    **It survives `narrowed_to` whole**, deliberately: it is a fact about the *API's schema* (which
    columns are unbounded ``TEXT``), not about which columns a caller asked to see. Narrowing it to
    the projected set would be correct today by accident and wrong the moment KAN-550 reads it for
    something other than truncating a column that is currently on screen."""

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
        """The same records under a different row. Half of what ``--fields`` needs; see
        `narrowed_to` for the other half and for why KAN-546 did not settle for this one alone."""
        return replace(self, columns=tuple(columns))

    def with_records(self, records: Iterable[Record]) -> "Payload":
        """The same shape carrying different values. This is how `truncation` rewrites prose.

        A **new** payload, and the records are copied: the one this was called on is the complete
        API response and ADR 0004 §Consequences requires it to stay that way, because ``--full`` and
        anything else that wants the untruncated text has nowhere else to get it. ``columns``,
        ``kind`` and ``prose_fields`` come through untouched — truncation changes what a value says,
        never which keys exist (ADR 0005 §contract 6), and the *caller* is what guarantees that:
        this method would take a narrower record, which is why `truncation._cut_record` rebuilds
        from ``record.items()`` rather than from a field list.
        """
        return replace(self, records=tuple(dict(record) for record in records))

    def limited_to(self, count: int) -> "Payload":
        """The first ``count`` records, in the order they arrived. ``--fields``' rows-wise twin.

        This is where KAN-549's "recent" slice happens, and the *placement* is the decision. A slice
        is a shaping act — it changes what a consumer is shown and therefore what a read costs — so
        ADR 0004 puts it in this package and not in an adapter, where the obvious spelling
        (``payload.records[:5]`` in `kaya_cli`) would be a projection rule in the one place ADR 0004
        forbids one. It is **not** a parameter of ``render``: ADR 0005 freezes that signature, and a
        fifth parameter is the stop signal rather than a step. It is a method on the payload, called
        by `client.KayaClient.recent_notes`, so a caller states the slice at the *call* and what
        comes back is a payload like any other.

        Two consequences fall out of that placement rather than being arranged:

        - **The aggregate describes the rows actually shown.** `aggregates.attach_summary` counts
          ``len(payload.records)`` of whatever it is handed, and it is handed this. ADR 0005
          §contract 5's "under a filter or ``--limit``, the returned set, not the whole corpus" is
          satisfied because there is no corpus left in scope by the time a summary exists.
        - **Truncation and projection compose with it untouched.** A limited payload is a
          ``Payload`` and goes through the same four steps in the same order.

        ``columns``, ``kind``, ``noun``, ``envelope_key`` and ``prose_fields`` come through
        unchanged: keeping fewer rows says nothing about which keys exist or which of them are
        prose. A **new** payload, like `narrowed_to` and `with_records`, so the complete response is
        still there for anything that needs it.

        A negative ``count`` is a ``ValueError`` rather than Python's silent "all but the last n",
        which is the wrong answer to a caller bug and would be wrong quietly.
        """
        if count < 0:
            raise ValueError(f"a limit is 0 or more, not {count}")
        return replace(self, records=self.records[:count])

    def narrowed_to(self, fields: Sequence[str]) -> "Payload":
        """The same payload with ``records`` **and** ``columns`` cut to ``fields``, in that order.

        This is ``--fields`` (KAN-546), and it is one operation rather than two on purpose. ADR 0004
        §Decision describes projection as narrowing the shaped dict — the thing that takes pandan's
        44,902-token read to 7,204 — while ADR 0005 §contract 2 describes it as widening the human
        row. Doing only the second would leave the structured formats paying the full field breadth
        that ADR 0004 exists to recover; doing only the first would leave `human` showing the same
        three columns whatever was asked for. So both, from one call, for every format: the CLI's
        ``--fields`` and MCP's ``fields`` are the same parameter through the same seam, and a
        projection that depended on ``fmt`` would put a behavioural difference between the two
        adapters *inside* the shared step. See ADR 0005's 2026-08-09 (KAN-546) amendment.

        Three details, each of which is a decision:

        - **The caller's order is the order.** ``fields=["path", "ref"]`` renders ``path`` first,
          and the narrowed record's keys are in that order too, so `json` and `toon` agree with the
          table rather than quietly re-imposing the API's ordering.
        - **Duplicates collapse, first occurrence winning.** A record is a dict and cannot hold one
          key twice, so ``["ref", "ref"]`` is unrepresentable in the structured formats. Printing
          the column twice under `human` while `json` showed it once would be the formats
          disagreeing about one argument, which is the drift this seam exists to prevent.
        - **A name the vocabulary has but a given record lacks is a hole, not an error.** The
          comprehension below skips it, `serialization._cell` renders it blank, and sparse rows stay
          the API's business — the same rule `test_a_missing_column_renders_blank_rather_than_
          raising` already pins for the default columns.

        ``prose_fields`` is untouched; see its docstring above.
        """
        selected = tuple(dict.fromkeys(fields))
        records = tuple(
            {name: record[name] for name in selected if name in record} for record in self.records
        )
        return replace(self, records=records, columns=selected)


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
