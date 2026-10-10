"""The pure half of the folder move (KAN-2000): segment rules mirroring ``tree.ts``."""

import pytest

from app.api.schemas import PATH_MAX
from app.folders import FolderMoveError, plan_move, rewrite, segments


def test_segments_drop_leading_trailing_and_doubled_slashes() -> None:
    assert segments("/a//b/c/") == ["a", "b", "c"]
    assert segments("") == []
    assert segments("///") == []


@pytest.mark.parametrize("raw", ["", "/", "//"])
def test_empty_from_or_to_is_refused(raw: str) -> None:
    with pytest.raises(FolderMoveError):
        plan_move(raw, "x")
    with pytest.raises(FolderMoveError):
        plan_move("x", raw)


def test_a_blank_segment_is_refused() -> None:
    with pytest.raises(FolderMoveError, match="blank"):
        plan_move("a/ /b", "x")
    with pytest.raises(FolderMoveError, match="blank"):
        plan_move("a", "x/  ")


@pytest.mark.parametrize("target", ["a/b/c", "/a//b/c/", "a/b/c/d"])
def test_moving_into_itself_or_a_descendant_is_refused(target: str) -> None:
    with pytest.raises(FolderMoveError, match="itself"):
        plan_move("a/b", target)


def test_moving_to_the_same_folder_is_planned_not_refused() -> None:
    assert plan_move("a/b", "/a//b/") == (["a", "b"], ["a", "b"])


def test_a_sibling_sharing_a_string_prefix_is_not_a_descendant() -> None:
    assert plan_move("a/b", "a/bc") == (["a", "b"], ["a", "bc"])


def test_rewrite_replaces_the_prefix_and_keeps_the_rest() -> None:
    assert rewrite("a/b/c/note.md", ["a", "b"], ["x"]) == "x/c/note.md"
    assert rewrite("a/b/note.md", ["a", "b"], ["x", "y"]) == "x/y/note.md"


def test_rewrite_matches_whole_segments_only() -> None:
    assert rewrite("a/bc/note.md", ["a", "b"], ["x"]) is None


def test_a_leaf_named_like_the_folder_is_not_inside_it() -> None:
    assert rewrite("a/b", ["a", "b"], ["x"]) is None
    assert rewrite("/a/b/", ["a", "b"], ["x"]) is None


def test_a_note_outside_the_folder_or_unpathed_is_untouched() -> None:
    assert rewrite("other/note.md", ["a"], ["x"]) is None
    assert rewrite("", ["a"], ["x"]) is None


def test_rewrite_normalises_a_messy_stored_path() -> None:
    assert rewrite("/a//b/note.md", ["a", "b"], ["x"]) == "x/note.md"


def test_a_result_over_the_column_limit_is_refused() -> None:
    long = "d" * (PATH_MAX - 5)
    with pytest.raises(FolderMoveError, match="longer"):
        rewrite("a/note.md", ["a"], [long])
