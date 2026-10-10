"""Version history shaping (KAY-138): what a note's versions look like to a CLI or an agent.

All of it is pure, so it is unit-tested without a transport and shared by both adapters (ADR 0004).

**Version numbers are ordinals, oldest first** (``1`` is the first body the note ever had). The API
names a version only by an internal surrogate id that no route accepts, so a caller needs a stable,
human-typable handle; the ordinal is derived from the list the API already returns, in the API's own
(newest-first) order reversed, and so is only as stable as history is append-only, which it is.

**The diff is computed here, from the two bodies the versions list already carries.** No endpoint:
a version is a complete body (``NoteVersionRead``'s own docstring), so a diff is one read and
``difflib``, and a server route would only move the same work to where it is harder to change.
"""

import difflib
from collections.abc import Mapping, Sequence
from typing import Any

BEFORE_TRACKING = "before tracking"
"""What a version cut before actors were recorded reads as. Never a guess at who it was."""


def actor_label(actor: Mapping[str, Any] | None) -> str:
    """One short line: ``alice@x.com via web`` / ``alice@x.com via token ci-bot (kaya_pat_ab12)``.

    The prefix is the non-secret display hint Settings already shows; nothing secret is ever in the
    payload to print.
    """
    if not actor:
        return BEFORE_TRACKING
    who = actor.get("email") or ("an account" if actor.get("user_id") else "unknown")
    token = actor.get("token")
    if token:
        name = token.get("name") or "token"
        prefix = token.get("prefix")
        kind = token.get("kind")
        label = f"{name} ({prefix})" if prefix else name
        if kind:
            label = f"{label} [{kind}]"
        return f"{who} via token {label}"
    if actor.get("channel") == "session":
        return f"{who} via web"
    return str(who)


def number_versions(versions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The API's newest-first list, as records carrying an oldest-first ``version`` ordinal, an
    ``actor`` label line, and the ``body``. Order stays the API's (newest first)."""
    total = len(versions)
    return [
        {
            "version": total - index,
            "created_at": record.get("created_at"),
            "actor": actor_label(record.get("actor")),
            "body": record.get("body", ""),
        }
        for index, record in enumerate(versions)
    ]


def unified_diff(old: str, new: str, *, old_label: str, new_label: str) -> tuple[str, int, int]:
    """``(text, added, removed)``: a unified diff, and how many lines it adds and removes."""
    lines = list(
        difflib.unified_diff(
            old.splitlines(),
            new.splitlines(),
            fromfile=old_label,
            tofile=new_label,
            lineterm="",
        )
    )
    added = sum(1 for line in lines if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in lines if line.startswith("-") and not line.startswith("---"))
    return "\n".join(lines), added, removed
