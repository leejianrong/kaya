"""**The shipped CLI surface never calls kaya's credential a pandan token.** KAN-1888.

Since ADR 0012 the credential kaya wants is a kaya-minted `kaya_pat_…`, from `kaya auth login`
(ADR 0013) or Settings > Tokens in the web app. A pandan PAT is only ever the optional pandan link
that powers card embeds and `[[KAN-n]]` resolution. Strings that still said otherwise survived the
cutover (the `config set --token` help, the bundled agent skill, two READMEs), so this scans what a
reader or an agent is shown: every verb's `--help`, the bundled `SKILL.md`, and the READMEs.

A line that is history is allowed, by an explicit marker below, never by a loose pattern.
"""

import argparse
import re
from pathlib import Path

import pytest

from kaya_cli.__main__ import build_parser

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "kaya-cli" / "src" / "kaya_cli" / "skills" / "kaya" / "SKILL.md"
DOCS = [
    SKILL,
    ROOT / "kaya-cli" / "README.md",
    ROOT / "mcp" / "README.md",
    ROOT / "README.md",
]

STALE = re.compile(
    r"pandan personal access token|pandan[_ ]pat_|pandan PAT"
    r"|a pandan (?:token|credential)|ADR 0002 gives",
    re.IGNORECASE,
)
HISTORY_MARKERS = ("superseded", "before that", "retired")
"""A line with one of these describes the pre-ADR-0012 past, so it may name the old model."""


def _all_help() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []

    def walk(parser: argparse.ArgumentParser, name: str) -> None:
        out.append((name, parser.format_help()))
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for sub_name, sub in action.choices.items():
                    walk(sub, f"{name} {sub_name}")

    walk(build_parser(), "kaya")
    return out


def _stale_lines(text: str) -> list[str]:
    # Help wraps lines, so match over each paragraph with whitespace collapsed.
    hits = []
    for para in re.split(r"\n\s*\n", text):
        flat = " ".join(para.split())
        if STALE.search(flat) and not any(m in flat.lower() for m in HISTORY_MARKERS):
            hits.append(flat[:160])
    return hits


@pytest.mark.parametrize(("name", "text"), _all_help(), ids=[n for n, _ in _all_help()])
def test_help_never_calls_the_credential_a_pandan_token(name: str, text: str) -> None:
    assert _stale_lines(text) == [], f"`{name} --help` still describes a pandan credential"


@pytest.mark.parametrize("path", DOCS, ids=lambda p: str(p.relative_to(ROOT)))
def test_shipped_docs_never_call_the_credential_a_pandan_token(path: Path) -> None:
    rel = path.relative_to(ROOT)
    assert _stale_lines(path.read_text(encoding="utf-8")) == [], f"{rel} is stale"


def test_the_scan_sees_the_help_it_is_meant_to_guard() -> None:
    names = [n for n, _ in _all_help()]
    assert "kaya config set" in names
    assert "kaya auth login" in names
