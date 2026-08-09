#!/usr/bin/env python
"""Measure what ``--format toon`` costs — or saves — against ``--format json``, per payload shape.

KAN-541's acceptance criterion, and CLAUDE.md §Conventions' rule that "it's fast" is not an
acceptance criterion but a number is. ADR 0005 §Alternatives is explicit that TOON "doesn't always
pay (`get` was +2% vs compact JSON)" in pandan's V47, and instructs kaya to "measure and record per
payload, as V47 did". This script is that measurement; its output goes in the PR body.

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

ENCODING = "o200k_base"

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


def measure(payload: Payload, count_tokens) -> tuple[int, int, float]:
    """``(json tokens, toon tokens, delta %)`` for one payload, both from ``render``."""
    as_json = render(payload, fmt="json")
    as_toon = render(payload, fmt="toon")
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

    narrowed = [{key: note[key] for key in NOTE_LIST_COLUMNS} for note in notes]
    rows = [
        (
            f"`note list` ({args.notes} notes, full records)",
            measure(list_payload(notes), count_tokens),
        ),
        ("`note get` (one note)", measure(entity_payload(notes[0]), count_tokens)),
        (
            f"`note list`, V2b's row only (`ref`/`title`/`path`, {args.notes} notes)",
            measure(list_payload(narrowed), count_tokens),
        ),
    ]

    print(f"corpus: {args.notes} notes, mean body {body_chars} chars, {ENCODING} tokens")
    print()
    if args.markdown:
        print("| payload | compact JSON | toon | delta |")
        print("|---|---:|---:|---:|")
        for name, (as_json, as_toon, delta) in rows:
            print(f"| {name} | {as_json:,} | {as_toon:,} | {delta:+.1f}% |")
    else:
        for name, (as_json, as_toon, delta) in rows:
            print(f"{name}: json {as_json:,}  toon {as_toon:,}  delta {delta:+.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
