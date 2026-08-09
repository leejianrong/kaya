#!/usr/bin/env python
"""What ``--format toon`` costs against ``--format json``, and what ``--fields`` and truncation cut.

KAN-541's acceptance criterion, KAN-546's and KAN-547's, and CLAUDE.md §Conventions' rule that "it's
fast" is not an acceptance criterion but a number is. ADR 0005 §Alternatives is explicit that TOON
"doesn't always pay (`get` was +2% vs compact JSON)" in pandan's V47, and instructs kaya to "measure
and record per payload, as V47 did". This script is that measurement, and its output goes in the PR.

**KAN-546 added the second table.** ADR 0004 rests its whole argument on one number — pandan's
44,902-token `list_cards` read falling to 7,204 when narrowed to five useful fields — and that
number was measured on pandan's board, not on kaya's notes. The projection table below is the same
measurement taken here, against the shipped `render`, so the ADR's claim is carried rather than
cited. It is also the reason the "V2b's row only" row of the first table is now produced by passing
``fields`` to ``render`` instead of by narrowing the corpus by hand: projection exists now, so a
harness that reimplemented it would be measuring itself, which is the mistake pandan's V49 made.

**KAN-547 added the third.** Truncation is the other half of what makes a read cheap, and it is the
half that is *free* on a narrowed read and expensive on a complete one — ``--fields ref,title`` has
no prose in it to cut. The table therefore measures complete records, where the whole saving is
``body``, and reports how much of the corpus is even over the limit: a saving quoted without that
number is a fact about the generated notes rather than about truncation. ``--full`` is the baseline
because ``text_limit=0`` is what a read cost before this card, so the percentages are what the
default now *saves* rather than what an opt-out costs.

Method
------
* **Unit: tokens, not bytes.** An agent's context is billed in tokens, and the two formats differ in
  exactly the characters a BPE tokenizer treats unevenly — quotes, braces, repeated key names. Bytes
  would over-report the saving, because the quotes TOON drops are cheap ones.
* **Tokenizer: ``o200k_base`` via ``tiktoken``.** Not Claude's tokenizer, and not a billing figure.
  It is the yardstick pandan's V47 and ADR 0019 used, so every token measurement across the two
  repositories is comparable, and it is a defensible proxy: all modern BPE vocabularies price
  repeated ASCII identifiers and punctuation within a few percent of each other, and the *sign* and
  rough magnitude of a structural saving do not depend on the vocabulary. A tokenizer that needs a
  network fetch on first use is why this is a script and not a test.
* **The baseline is compact JSON**, which is what ``--format json`` actually emits (KAN-540 chose
  ``separators=(",", ":")`` deliberately — pandan measured pretty-printing at 16% of a 44,902-token
  payload). Measuring against indented JSON would flatter TOON by that 16% before the encoder did
  anything at all.
* **Both formats come from the shipped code.** Every row below is produced by calling ``render``,
  the same function the CLI and V6's MCP adapter call. Pandan's V49 learned this the hard way: its
  first harness kept a private copy of the shaping rule and would have over-reported the saving. A
  measurement that reimplements what it measures is measuring itself.
* **The corpus is not tuned.** It is generated once from a fixed seed and used for every row, so
  ``list`` and ``get`` are measured over the *same* notes. If TOON loses on a shape, the honest
  thing is to report the loss — a number that makes it look uniformly good is more likely to be a
  bad measurement than a good encoder.

Run it
------
``tiktoken`` is not a dependency of this package and must not become one: ``kaya-client`` has one
runtime dependency and the encoder is stdlib-only (SLICES §V2a). It is supplied for the run only::

    cd kaya-client && uv run --with tiktoken python scripts/measure_toon_delta.py

``--notes`` and ``--body-words`` vary the corpus; ``--markdown`` prints the table for a PR body.
"""

import argparse
import random
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kaya_client.client import (  # noqa: E402 - after the path insert, so a checkout runs unbuilt
    NOTE_COLUMNS,
    NOTE_ENVELOPE,
    NOTE_LIST_COLUMNS,
    NOTE_NOUN,
    NOTE_PROSE_FIELDS,
)
from kaya_client.payloads import Payload  # noqa: E402
from kaya_client.render import render  # noqa: E402
from kaya_client.truncation import DEFAULT_TEXT_LIMIT  # noqa: E402

ENCODING = "o200k_base"

NO_TEXT_LIMIT = 0
"""``--full``. The baseline every truncation row below is a percentage of, because it is what a read
cost before KAN-547 — so the numbers report what the default *saves*, not what an opt-out costs."""

TIGHT_TEXT_LIMIT = 200
"""A second limit, so the table shows a slope rather than one point. An agent skimming for which
notes to open wants far less than 500 characters of each, which is the read `--fields` alone cannot
make cheap because the field it is expensive in is the one being read."""

DEFAULT_NOTES = 40
DEFAULT_BODY_WORDS = 60

WORDS: tuple[str, ...] = (
    'meeting', 'notes', 'deploy', 'rollback', 'postgres', 'migration', 'index', 'latency',
    'cache', 'token', 'refresh', 'board', 'card', 'epic', 'slice', 'adapter', 'serializer',
    'payload', 'envelope', 'truncation', 'aggregate', 'render', 'wikilink', 'backlink',
    'search', 'query', 'owner', 'principal', 'bearer', 'upstream', 'timeout', 'retry', 'digest',
    'the', 'a', 'of', 'to', 'and', 'in', 'for', 'with', 'on', 'that', 'this', 'it', 'is', 'are',
    'was', 'were', 'be', 'been', 'being', 'from',
)

FOLDERS = ["work", "work/meetings", "personal", "reference", "inbox", "projects/kaya"]


def build_notes(count: int, body_words: int, *, seed: int = 541) -> list[dict[str, Any]]:
    """A plausible `note list`: the seven keys `NoteRead` returns, with prose in ``body``.

    Deliberately *not* uniform in length — real notes are not — but uniform in **shape**, which is
    the property TOON's tabular header depends on and which `/api/v1/notes` guarantees because every
    row is a ``NoteRead``.
    """
    rng = random.Random(seed)
    notes: list[dict[str, Any]] = []
    for index in range(1, count + 1):
        title = " ".join(rng.sample(WORDS, rng.randint(2, 6))).capitalize()
        length = max(0, int(rng.gauss(body_words, body_words / 3)))
        body = " ".join(rng.choice(WORDS) for _ in range(length))
        if length > 25:
            # Real markdown has structure, and a newline is a character both formats must escape
            # or emit. A corpus of single paragraphs would quietly favour whichever handles them
            # better, which is the sort of tuning this measurement exists to avoid.
            body = f"# {title}\n\n{body[: length * 3]}\n\n- {body[:40]}\n- {body[40:80]}"
        notes.append(
            {
                "ref": f"NOTE-{index}",
                "id": index,
                "title": title,
                "body": body,
                "path": f"{rng.choice(FOLDERS)}/{title.lower().replace(' ', '-')}.md",
                "created_at": f"2026-0{rng.randint(1, 8)}-1{rng.randint(0, 9)}T09:15:00+00:00",
                "updated_at": f"2026-08-0{rng.randint(1, 9)}T11:02:33.{rng.randrange(10**6):06d}"
                "+00:00",
            }
        )
    return notes


def list_payload(notes: Sequence[dict[str, Any]]) -> Payload:
    return Payload.collection(
        noun=NOTE_NOUN,
        envelope_key=NOTE_ENVELOPE,
        records=notes,
        columns=NOTE_LIST_COLUMNS,
        prose_fields=NOTE_PROSE_FIELDS,
    )


def entity_payload(note: dict[str, Any]) -> Payload:
    return Payload.entity(
        noun=NOTE_NOUN,
        envelope_key=NOTE_ENVELOPE,
        record=note,
        columns=NOTE_COLUMNS,
        prose_fields=NOTE_PROSE_FIELDS,
    )


def measure(
    payload: Payload,
    count_tokens,
    fields: Sequence[str] | None = None,
    text_limit: int = NO_TEXT_LIMIT,
) -> tuple[int, int, float]:
    """``(json tokens, toon tokens, delta %)`` for one payload, both from ``render``.

    ``fields`` and ``text_limit`` go to ``render`` untouched, so a projected or truncated row is the
    shipped shaping and not a corpus this script narrowed or cut for itself.

    ``text_limit`` defaults to ``0`` — untruncated — rather than to ``render``'s own 500, so the
    first two tables measure exactly what they measured before KAN-547 and stay comparable with the
    numbers already in ADR 0005's amendment. Truncation is the third table's subject, not a silent
    change to the other two.
    """
    as_json = render(payload, fields=fields, text_limit=text_limit, fmt="json")
    as_toon = render(payload, fields=fields, text_limit=text_limit, fmt="toon")
    assert isinstance(as_json, str) and isinstance(as_toon, str)

    json_tokens = count_tokens(as_json)
    toon_tokens = count_tokens(as_toon)
    return json_tokens, toon_tokens, (toon_tokens - json_tokens) / json_tokens * 100


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--notes", type=int, default=DEFAULT_NOTES)
    parser.add_argument("--body-words", type=int, default=DEFAULT_BODY_WORDS)
    parser.add_argument("--markdown", action="store_true", help="print a PR-body table")
    args = parser.parse_args(argv)

    try:
        import tiktoken
    except ModuleNotFoundError:
        print(
            "tiktoken is not installed, and must not become a dependency of this package.\n"
            "Run:  uv run --with tiktoken python scripts/measure_toon_delta.py",
            file=sys.stderr,
        )
        return 1

    encoding = tiktoken.get_encoding(ENCODING)

    def count_tokens(text: str) -> int:
        return len(encoding.encode(text))

    notes = build_notes(args.notes, args.body_words)
    body_chars = sum(len(note["body"]) for note in notes) // len(notes)
    listed = list_payload(notes)

    projections: list[tuple[str, Sequence[str] | None]] = [
        (f"complete records ({len(notes[0])} keys)", None),
        (f"`--fields {','.join(NOTE_LIST_COLUMNS)}` (the default human row)", NOTE_LIST_COLUMNS),
        ("`--fields ref,title`", ("ref", "title")),
        ("`--fields ref`", ("ref",)),
    ]

    rows = [
        (
            f"`note list` ({args.notes} notes, complete records)",
            measure(listed, count_tokens),
        ),
        ("`note get` (one note)", measure(entity_payload(notes[0]), count_tokens)),
        (
            f"`note list --fields {','.join(NOTE_LIST_COLUMNS)}` ({args.notes} notes)",
            measure(listed, count_tokens, NOTE_LIST_COLUMNS),
        ),
    ]

    projected = [
        (name, measure(listed, count_tokens, fields)) for name, fields in projections
    ]
    complete_json, complete_toon, _ = projected[0][1]

    single = entity_payload(notes[0])
    limits = [
        ("`--full` (`text_limit=0`)", NO_TEXT_LIMIT),
        (f"default (`{DEFAULT_TEXT_LIMIT}`)", DEFAULT_TEXT_LIMIT),
        (f"`KAYA_MAX_TEXT_CHARS={TIGHT_TEXT_LIMIT}`", TIGHT_TEXT_LIMIT),
    ]
    truncated = [
        (
            name,
            measure(listed, count_tokens, text_limit=limit),
            measure(single, count_tokens, text_limit=limit),
        )
        for name, limit in limits
    ]
    over_limit = sum(1 for note in notes if len(note["body"]) > DEFAULT_TEXT_LIMIT)
    listed_full_json = truncated[0][1][0]
    listed_full_toon = truncated[0][1][1]
    single_full_json = truncated[0][2][0]
    single_full_toon = truncated[0][2][1]

    print(f"corpus: {args.notes} notes, mean body {body_chars} chars, {ENCODING} tokens")
    print(
        f"        {over_limit}/{len(notes)} bodies are over the default {DEFAULT_TEXT_LIMIT}-char "
        f"limit, so the rest pass through byte-identical"
    )
    print()
    if args.markdown:
        print("| payload | compact JSON | toon | toon delta |")
        print("|---|---:|---:|---:|")
        for name, (as_json, as_toon, delta) in rows:
            print(f"| {name} | {as_json:,} | {as_toon:,} | {delta:+.1f}% |")
        print()
        print(f"| `note list`, {args.notes} notes | compact JSON | vs complete | toon | "
              "vs complete |")
        print("|---|---:|---:|---:|---:|")
        for name, (as_json, as_toon, _) in projected:
            print(
                f"| {name} | {as_json:,} | {_share(as_json, complete_json)} | "
                f"{as_toon:,} | {_share(as_toon, complete_toon)} |"
            )
        print()
        print(
            "| text limit, complete records | `note list` JSON | vs `--full` | toon | "
            "vs `--full` | `note get` JSON | vs `--full` |"
        )
        print("|---|---:|---:|---:|---:|---:|---:|")
        for name, listing, entity in truncated:
            print(
                f"| {name} | {listing[0]:,} | {_share(listing[0], listed_full_json)} | "
                f"{listing[1]:,} | {_share(listing[1], listed_full_toon)} | "
                f"{entity[0]:,} | {_share(entity[0], single_full_json)} |"
            )
    else:
        for name, (as_json, as_toon, delta) in rows:
            print(f"{name}: json {as_json:,}  toon {as_toon:,}  delta {delta:+.1f}%")
        print()
        for name, (as_json, as_toon, _) in projected:
            print(
                f"{name}: json {as_json:,} ({_share(as_json, complete_json)})  "
                f"toon {as_toon:,} ({_share(as_toon, complete_toon)})"
            )
        print()
        for name, listing, entity in truncated:
            print(
                f"{name}: list json {listing[0]:,} ({_share(listing[0], listed_full_json)})  "
                f"list toon {listing[1]:,} ({_share(listing[1], listed_full_toon)})  "
                f"get json {entity[0]:,} ({_share(entity[0], single_full_json)})  "
                f"get toon {entity[1]:,} ({_share(entity[1], single_full_toon)})"
            )
    return 0


def _share(tokens: int, complete: int) -> str:
    """A projected cost as a percentage change against the complete record. ``—`` for the baseline.

    Reported as a change rather than as a ratio because that is the shape of ADR 0004's own claim
    (44,902 → 7,204, "a `fields` argument would recover ~84%"), and a reader comparing the two
    should not have to do the arithmetic in a different direction.
    """
    if tokens == complete:
        return "—"
    return f"{(tokens - complete) / complete * 100:+.1f}%"


if __name__ == "__main__":
    raise SystemExit(main())
