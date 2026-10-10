"""Folder move/rename as a path-prefix rewrite (KAN-2000, ADR 0008 amendment).

A folder is not a thing: it is the leading segments of ``note.path`` (``frontend/src/lib/tree.ts``
derives the tree from paths and there is no folder table). Moving or renaming one is therefore a
bulk rewrite of that prefix on every note beneath it. This module is the pure half of it, with no
database, so the segment rules are testable on their own.

Segment rules mirror ``tree.ts``: split on ``/`` and drop empty pieces, so leading, trailing and
doubled slashes vanish. The **last** segment of a path is the note's filename, never a folder, so a
note whose path is exactly the folder (``a/b`` when moving ``a/b``) is a leaf that happens to share
the folder's name and is not inside it. Segments match whole, so ``a/b`` never matches ``a/bc/x``.
"""

from app.api.schemas import PATH_MAX


class FolderMoveError(ValueError):
    """The request cannot be a folder move. The message is safe to show the caller."""


def segments(path: str) -> list[str]:
    """``path`` as ``tree.ts`` reads it: separators collapsed, nothing else altered."""
    return [piece for piece in path.split("/") if piece != ""]


def folder_segments(raw: str, label: str) -> list[str]:
    """A folder argument as segments, or ``FolderMoveError``.

    Empty (or only slashes) is refused, and so is a segment of nothing but whitespace: ``tree.ts``
    drops those, so such a folder could never be seen, let alone moved.
    """
    pieces = segments(raw)
    if not pieces:
        raise FolderMoveError(f"'{label}' must name a folder")
    if any(piece.strip() == "" for piece in pieces):
        raise FolderMoveError(f"'{label}' has a blank segment")
    return pieces


def plan_move(source: str, target: str) -> tuple[list[str], list[str]]:
    """Validate a move and return both sides as segments."""
    origin = folder_segments(source, "from")
    destination = folder_segments(target, "to")
    if origin != destination and destination[: len(origin)] == origin:
        raise FolderMoveError("a folder cannot be moved into itself or one of its descendants")
    return origin, destination


def rewrite(path: str, origin: list[str], destination: list[str]) -> str | None:
    """``path`` with the ``origin`` prefix replaced by ``destination``, or ``None`` if the note is
    not inside ``origin``. The result is normalised. Raises ``FolderMoveError`` if it is too long
    for the column."""
    pieces = segments(path)
    if len(pieces) <= len(origin) or pieces[: len(origin)] != origin:
        return None
    moved = "/".join(destination + pieces[len(origin) :])
    if len(moved) > PATH_MAX:
        raise FolderMoveError(f"moving would make a path longer than {PATH_MAX} characters")
    return moved
