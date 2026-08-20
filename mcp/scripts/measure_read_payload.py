"""What a real MCP tool CALL costs against kaya's own data — the number ADR 0006 §3 and
`measure_schema_compaction.py`'s docstring both name as still owed: KAN-574.

Unlike that script, this one cannot run with no I/O. `measure_schema_compaction.py` only needs the
`server` object in-process — `tools/list` is static, so a fake API and an in-memory transport are
enough. A tool *call* needs a real backend behind a real `KayaClient`, so this script needs three
things `measure_schema_compaction.py` does not: a live kaya backend, a real pandan PAT, and a real
`kaya-mcp` **subprocess** talked to over stdio (the transport an MCP host actually launches this
server with — the same shape `scripts/verify_stdio_image.py` drives against a built image, here
against `python -m kaya_mcp` so no image build is required).

That is also why this is a script and not a test, and not wired into `make check`, `make test` or
CI: there is no hosted kaya (ADR 0010) and no committed fixture corpus realistic enough to be
honest about truncation, so "run this in CI" would mean either standing up a stack on every push
for a number that does not change between runs, or teaching CI a secret it does not otherwise need.
Follows `make measure-auth`'s contract instead (CLAUDE.md's own words for it): reads a credential,
never prints it, and exits 0 having done nothing when the infrastructure it needs is absent — so
nothing here can turn into a red CI check over a missing secret.

Stand up an isolated stack first — **not** the shared dev one on :8010/:5434, which another agent
or the maintainer's own browser session may depend on:

    COMPOSE_PROJECT_NAME=kaya-measure KAYA_DB_PORT=5443 KAYA_APP_PORT=8023 make up

Then, from `mcp/`:

    KAYA_MCP_MEASURE_URL=http://localhost:8023 \\
    KAYA_MCP_MEASURE_PAT=$(python3 -c "import tomllib as t; \\
        print(t.load(open('$HOME/.config/pandan/config.toml','rb'))['pandan']['token'])") \\
    uv run --with tiktoken python scripts/measure_read_payload.py --seed-notes 40 --markdown

`KAYA_MCP_MEASURE_URL` is the target backend. `KAYA_MCP_MEASURE_PAT` is a real pandan PAT — it
falls back to `~/.config/pandan/config.toml`, same as `backend/scripts/measure_introspection_
latency.py` — and is held in one local, handed straight to the subprocess's environment, and never
printed, logged or included in any output this script produces. With either missing, this script
says so and exits 0.

`--seed-notes N` creates N fresh notes through a real `KayaClient` (not through MCP — the tools have
no bulk-create) with realistic, non-uniform multi-paragraph markdown bodies before measuring, so the
corpus this measures is not forty one-line placeholders: KAN-547's own PR found truncation's effect
invisible on trivially short bodies and only honest against real documents. Omit it to measure
whatever the target backend already holds — useful for a second run against the same seeded stack.

### What is measured, and why two rows per call

Same shape as `measure_schema_compaction.py`'s two rows, and the same reason: quoting only one
would be misleading in either direction.

- **`structuredContent` only** is the shaped JSON payload the tool computed — `kaya_client.render`'s
  output, compact-encoded (`json.dumps(..., separators=(",", ":"))`, the same baseline
  `kaya-client/scripts/measure_toon_delta.py` uses, because that is what a transport sends and so
  what a size should be measured on). This is the number directly comparable to ADR 0004's own
  84%-narrowing figure and to the `--fields`/truncation savings those cards measured on `render`
  in isolation — here produced by a real tool call instead.
- **whole tool result** is `content` (the SDK's own plain-text mirror of the same JSON, *pretty-
  printed* with a two-space indent) plus `structuredContent` together — what a `tools/call` response
  actually contains over the wire. Measured here because it is a real cost this script's own probe
  found and ADR 0006 never priced: the SDK sends the answer **twice**, once as the shaped dict and
  once again as an indented string a text-only host would read instead. Reported as its own row
  rather than folded into the first one, the same way the schema script keeps "input schemas only"
  and "whole tools/list reply" apart.

Both rows exclude the outer JSON-RPC envelope (request id, protocol version, method name) — small,
fixed per call, and not what `fields`/truncation/aggregate touch, so including it would dilute the
percentage without changing the finding.

### Two tools, and why

`list_notes` is the natural first call: it is where KAN-546's narrowing, KAN-547's truncation and
KAN-548's aggregate all apply at once, and it is pandan ADR 0019's own comparison point
(`list_cards`). Measured twice — `fields=None` (a complete, unnarrowed response) against
`fields=["ref", "title", "path"]`, `kaya_client.client.NOTE_LIST_COLUMNS` itself: the smallest set a
caller could still identify and open a note from, and the columns a `human` render already shows by
default with no flag.

`get_note` is the second, complementary point: a single-entity read, where KAN-548's aggregate does
not apply (`attach_summary` never runs for one record) and truncation is the whole story. There is
no CLI-style `--full` flag on an MCP call, so the two arms are two **subprocess environments**
instead of two arguments — `KAYA_MAX_TEXT_CHARS=0` (what `--full` sets it to) against
`KAYA_MAX_TEXT_CHARS` unset (the shipped default, 500) — against the corpus's longest body, so the
truncation this measures is one that actually fires. Reported full-first, matching the printed
before → after order below: truncation only removes text, so the untruncated side is always the
larger one, and the saving is the same "complete → narrowed" framing `list_notes`' row uses.

Prints markdown with `--markdown`, matching the other two measurement scripts so a PR body can
paste the tables directly.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import tomllib
from pathlib import Path
from typing import Any

import anyio
from mcp import StdioServerParameters
from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "kaya-client" / "src"))
from kaya_client.client import KayaClient  # noqa: E402 - after the path insert, source checkout

URL_ENV = "KAYA_MCP_MEASURE_URL"
PAT_ENV = "KAYA_MCP_MEASURE_PAT"
PANDAN_CONFIG = Path.home() / ".config" / "pandan" / "config.toml"

HANDSHAKE_TIMEOUT_SECONDS = 30
"""Generous, the same reasoning `verify_stdio_image.py` gives: this is a measurement run, not a
latency budget, and a cold subprocess import is not what is being timed."""

NARROW_FIELDS = ("ref", "title", "path")
"""`kaya_client.client.NOTE_LIST_COLUMNS` restated rather than imported by name, so this script
reads as a plain literal beside the numbers it produces."""


# --------------------------------------------------------------------------------- credential


def _credential() -> str | None:
    """`KAYA_MCP_MEASURE_PAT`, or the same pandan config file `measure_introspection_latency.py`
    falls back to. Never logged, never returned to a caller that might print it — only handed to a
    subprocess's environment."""
    token = os.environ.get(PAT_ENV, "").strip()
    if token:
        return token
    if not PANDAN_CONFIG.exists():
        return None
    try:
        data = tomllib.loads(PANDAN_CONFIG.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return None
    value = data.get("pandan", {}).get("token")
    return value.strip() if isinstance(value, str) and value.strip() else None


# ------------------------------------------------------------------------------------- corpus


PARAGRAPH_WORDS: tuple[str, ...] = (
    "the",
    "migration",
    "ran",
    "clean",
    "against",
    "a",
    "cold",
    "replica",
    "and",
    "the",
    "index",
    "rebuild",
    "finished",
    "before",
    "the",
    "maintenance",
    "window",
    "closed",
    "we",
    "still",
    "owe",
    "a",
    "runbook",
    "entry",
    "for",
    "the",
    "rollback",
    "path",
    "since",
    "nobody",
    "has",
    "exercised",
    "it",
    "under",
    "load",
    "the",
    "cache",
    "hit",
    "rate",
    "climbed",
    "past",
    "ninety",
    "percent",
    "once",
    "the",
    "warm",
    "pool",
    "settled",
    "but",
    "the",
    "cold",
    "start",
    "budget",
    "is",
    "still",
    "the",
    "open",
    "question",
    "worth",
    "raising",
    "at",
    "standup",
    "tomorrow",
    "morning",
    "with",
    "the",
    "on-call",
    "engineer",
    "who",
    "watched",
    "the",
    "dashboards",
    "overnight",
    "and",
    "flagged",
    "three",
    "slow",
    "queries",
    "that",
    "correlate",
    "with",
    "the",
    "backup",
    "job",
    "rather",
    "than",
    "with",
    "traffic",
    "itself",
    "so",
    "the",
    "next",
    "step",
    "is",
    "probably",
    "staggering",
    "the",
    "schedule",
    "instead",
    "of",
    "adding",
    "another",
    "replica",
    "which",
    "would",
    "just",
    "move",
    "the",
    "same",
    "contention",
    "somewhere",
    "else",
    "in",
    "the",
    "cluster",
    "and",
    "cost",
    "more",
)
"""A closed vocabulary that reads as ordinary engineering prose rather than lorem ipsum — real
notes are not word salad, and a tokenizer prices structured English differently from noise."""

HEADINGS: tuple[str, ...] = (
    "Context",
    "Decision",
    "Open questions",
    "Follow-ups",
    "What changed",
    "Risks",
    "Rollback plan",
    "Next steps",
)

TITLES: tuple[str, ...] = (
    "Postgres failover runbook",
    "Weekly on-call handoff",
    "Cache warm-up notes",
    "Migration 0042 retro",
    "Incident review: cold start",
    "Deploy checklist v3",
    "Backup schedule staggering",
    "Index rebuild timing",
    "Replica lag investigation",
    "Auth token rotation plan",
    "Search relevance tuning",
    "Editor conflict banner design",
    "Sidebar folder grouping",
    "Backlinks rail placement",
    "Schema compaction findings",
    "Release provenance checklist",
    "k3d smoke test steps",
    "Alembic hook wiring",
    "Client deadline budget",
    "Single-flight coalescing",
)

FOLDERS: tuple[str, ...] = ("runbooks", "meetings", "retros", "design", "inbox", "ops/postgres")


def _paragraph(rng: random.Random, sentences: int) -> str:
    words: list[str] = []
    for _ in range(sentences):
        length = rng.randint(10, 22)
        sentence = [rng.choice(PARAGRAPH_WORDS) for _ in range(length)]
        sentence[0] = sentence[0].capitalize()
        words.append(" ".join(sentence) + ".")
    return " ".join(words)


def _body(rng: random.Random) -> str:
    """A multi-paragraph markdown document, deliberately not uniform in length — a mean around
    kaya-client's own measurement corpus (KAN-547's PR: 1,351 chars over 40 notes), not a fixed
    size, so a percentage measured against it is about truncation and not about a generator."""
    sections = rng.randint(2, 5)
    parts: list[str] = []
    for _ in range(sections):
        heading = rng.choice(HEADINGS)
        paragraph = _paragraph(rng, rng.randint(2, 5))
        parts.append(f"## {heading}\n\n{paragraph}")
        if rng.random() < 0.5:
            bullets = "\n".join(
                f"- {rng.choice(PARAGRAPH_WORDS)} {rng.choice(PARAGRAPH_WORDS)}"
                f" {rng.choice(PARAGRAPH_WORDS)}"
                for _ in range(rng.randint(2, 4))
            )
            parts.append(bullets)
    return "\n\n".join(parts)


def seed_notes(client: KayaClient, count: int, *, seed: int = 574) -> list[dict[str, Any]]:
    """Create `count` real notes through the API, realistic in shape, and return what each call
    echoed back (so the caller can pick the longest body without a second round trip)."""
    rng = random.Random(seed)
    created: list[dict[str, Any]] = []
    for index in range(count):
        title = f"{rng.choice(TITLES)} #{index + 1}"
        body = _body(rng)
        path = f"{rng.choice(FOLDERS)}/{title.lower().replace(' ', '-').replace('#', '')}.md"
        payload = client.create_note(title, body=body, path=path)
        created.append(dict(payload.records[0]))
    return created


def _corpus_stats(notes: list[dict[str, Any]]) -> str:
    lengths = [len(n.get("body") or "") for n in notes]
    if not lengths:
        return "corpus: 0 notes"
    mean = sum(lengths) / len(lengths)
    return (
        f"corpus: {len(lengths)} notes, body length mean {mean:.0f} chars, "
        f"range {min(lengths)}–{max(lengths)}"
    )


# --------------------------------------------------------------------------------- the tool call


def _blob(value: Any) -> str:
    """Compact JSON — what a transport sends, and so what a size should be measured on. Same
    helper `measure_schema_compaction.py` uses, restated rather than imported across scripts."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


async def _call(
    base_url: str, token: str, tool: str, arguments: dict[str, Any], *, max_text_chars: str | None
) -> CallToolResult:
    env = dict(os.environ)
    env["KAYA_API_URL"] = base_url
    env["KAYA_TOKEN"] = token
    if max_text_chars is None:
        env.pop("KAYA_MAX_TEXT_CHARS", None)
    else:
        env["KAYA_MAX_TEXT_CHARS"] = max_text_chars
    params = StdioServerParameters(command=sys.executable, args=["-m", "kaya_mcp"], env=env)
    with anyio.fail_after(HANDSHAKE_TIMEOUT_SECONDS):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, arguments)
    if result.is_error:
        text = result.content[0].text if result.content else "<no content>"
        raise RuntimeError(f"{tool}({arguments!r}) failed over the real stack: {text}")
    return result


def _rows_for(result: CallToolResult) -> tuple[str, str]:
    """(structuredContent only, whole tool result) as the two blobs `_counts` measures."""
    structured_only = _blob(result.structured_content)
    whole = _blob(
        {
            "content": [block.text for block in result.content if hasattr(block, "text")],
            "structuredContent": result.structured_content,
        }
    )
    return structured_only, whole


# ------------------------------------------------------------------------------------- reporting


def _counts(text: str, encoding: Any) -> tuple[int, int | None]:
    return len(text.encode("utf-8")), (len(encoding.encode(text)) if encoding else None)


def _print_table(
    title: str,
    rows: list[tuple[str, str, str]],
    *,
    markdown: bool,
    encoding: Any,
    encoding_name: str,
) -> None:
    print(f"\n{title}")
    if markdown:
        print(f"| what | bytes | tokens (`{encoding_name}`) |")
        print("|---|---|---|")
    for label, before, after in rows:
        before_bytes, before_tokens = _counts(before, encoding)
        after_bytes, after_tokens = _counts(after, encoding)
        byte_delta = (after_bytes - before_bytes) / before_bytes * 100 if before_bytes else 0.0
        byte_note = f"{before_bytes} → {after_bytes} ({byte_delta:+.1f}%)"
        token_note = "n/a"
        if before_tokens and after_tokens:
            token_delta = (after_tokens - before_tokens) / before_tokens * 100
            token_note = f"{before_tokens} → {after_tokens} ({token_delta:+.1f}%)"
        if markdown:
            print(f"| {label} | {byte_note} | {token_note} |")
        else:
            print(f"  {label}:\n    bytes  {byte_note}\n    tokens {token_note}")


async def _measure(args: argparse.Namespace, base_url: str, token: str) -> None:
    encoding = None
    encoding_name = args.encoding
    try:
        import tiktoken

        encoding = tiktoken.get_encoding(encoding_name)
    except ImportError:  # pragma: no cover - this script's own advice
        print("no tiktoken; reporting bytes only (see this file's docstring for the run command)")

    if args.seed_notes:
        print(f"▸ seeding {args.seed_notes} notes against {base_url} ...")
        with KayaClient(base_url, token) as client:
            seed_notes(client, args.seed_notes)

    with KayaClient(base_url, token) as client:
        all_notes = [dict(r) for r in client.list_notes().records]
    print(_corpus_stats(all_notes))
    if not all_notes:
        print("no notes on the target backend; pass --seed-notes N to create some")
        return
    longest_ref = max(all_notes, key=lambda n: len(n.get("body") or ""))["ref"]

    # list_notes: fields=None (complete) vs fields=NARROW_FIELDS, default truncation both times.
    before = await _call(base_url, token, "list_notes", {}, max_text_chars=None)
    after = await _call(
        base_url, token, "list_notes", {"fields": list(NARROW_FIELDS)}, max_text_chars=None
    )
    before_structured, before_whole = _rows_for(before)
    after_structured, after_whole = _rows_for(after)
    _print_table(
        f"list_notes — complete vs fields={list(NARROW_FIELDS)}",
        [
            ("structuredContent only", before_structured, after_structured),
            ("whole tool result", before_whole, after_whole),
        ],
        markdown=args.markdown,
        encoding=encoding,
        encoding_name=encoding_name,
    )

    # get_note on the longest body: KAYA_MAX_TEXT_CHARS=0 (--full) vs the default 500-char
    # truncation — full first, so the title's word order matches the printed before → after order
    # below (full is always the larger side; truncation only removes text).
    truncated = await _call(base_url, token, "get_note", {"ref": longest_ref}, max_text_chars=None)
    full = await _call(base_url, token, "get_note", {"ref": longest_ref}, max_text_chars="0")
    trunc_structured, trunc_whole = _rows_for(truncated)
    full_structured, full_whole = _rows_for(full)
    _print_table(
        f"get_note {longest_ref} (longest body in corpus) — --full equivalent vs default 500 chars",
        [
            ("structuredContent only", full_structured, trunc_structured),
            ("whole tool result", full_whole, trunc_whole),
        ],
        markdown=args.markdown,
        encoding=encoding,
        encoding_name=encoding_name,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--markdown", action="store_true", help="emit tables for a PR body")
    parser.add_argument("--encoding", default="o200k_base", help="tiktoken encoding name")
    parser.add_argument(
        "--seed-notes",
        type=int,
        default=0,
        metavar="N",
        help="create N realistic notes on the target backend before measuring (default: 0, "
        "measure whatever is already there)",
    )
    args = parser.parse_args()

    base_url = os.environ.get(URL_ENV, "").strip()
    if not base_url:
        print(
            f"no {URL_ENV} set — this script needs a live, isolated kaya backend to call a real "
            "tool against (see this file's docstring for how to stand one up). Doing nothing."
        )
        return 0

    token = _credential()
    if not token:
        print(
            f"no credential — set {PAT_ENV} or put one in {PANDAN_CONFIG}. Doing nothing, and "
            "nothing was printed from it."
        )
        return 0

    anyio.run(_measure, args, base_url, token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
