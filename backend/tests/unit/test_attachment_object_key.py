"""``object_key`` — R14, KAN-1067: the filename is cosmetic, the UUID is the identity.

The whole property under test is the one line in `app/api/attachments.py`'s module docstring:
never the caller-supplied filename verbatim. A key built from the filename would be a
path-traversal-shaped key the moment a caller names a file `../../secret` or embeds a `/`.
"""

import io
import re
from typing import Any

import pytest
from fastapi import HTTPException, UploadFile

from app.api.attachments import MAX_EXTENSION_LENGTH, _read_capped, object_key

UUID_HEX = r"[0-9a-f]{32}"


def _upload(content: bytes) -> Any:
    return UploadFile(file=io.BytesIO(content), filename="f.bin")


def test_the_key_is_namespaced_by_note_id() -> None:
    key = object_key(42, "photo.png")
    assert key.startswith("42/")


def test_a_missing_filename_produces_a_bare_note_id_and_uuid() -> None:
    key = object_key(1, None)
    assert re.fullmatch(rf"1/{UUID_HEX}", key)


def test_an_empty_filename_is_treated_the_same_as_none() -> None:
    key = object_key(1, "")
    assert re.fullmatch(rf"1/{UUID_HEX}", key)


def test_the_extension_is_kept_when_the_filename_has_one() -> None:
    key = object_key(1, "diagram.svg")
    assert key.endswith(".svg")


def test_a_path_traversal_shaped_filename_leaves_no_traversal_in_the_key() -> None:
    key = object_key(1, "../../secrets/passwd")
    assert ".." not in key
    assert "secrets" not in key
    assert "passwd" not in key
    # Exactly one `/`: the note-id prefix. Nothing from the filename can introduce a second one.
    assert key.count("/") == 1


def test_a_slash_embedded_in_the_extension_position_cannot_escape_the_prefix() -> None:
    key = object_key(1, "name.evil/../../etc")
    assert key.count("/") == 1


def test_two_uploads_of_the_same_filename_get_two_different_keys() -> None:
    """The UUID is the identity; nothing about the filename may collide two attachments onto one
    object."""
    assert object_key(1, "same.png") != object_key(1, "same.png")


def test_a_multi_dot_filename_keeps_only_the_final_suffix() -> None:
    key = object_key(1, "archive.tar.gz")
    assert key.endswith(".gz")
    assert ".tar" not in key


def test_an_absurdly_long_extension_is_capped_and_lowercased() -> None:
    key = object_key(1, "file." + "X" * 100)
    ext = key.rsplit(".", 1)[1]
    assert len(ext) <= MAX_EXTENSION_LENGTH
    assert ext == ext.lower()


def test_a_non_alphanumeric_extension_is_stripped_to_nothing() -> None:
    """A suffix that is punctuation rather than a real extension — `PurePosixPath('x.--').suffix`
    is `'.--'` — must not survive into the key as anything but nothing."""
    key = object_key(1, "x.--")
    assert re.fullmatch(rf"1/{UUID_HEX}", key)


# --- _read_capped -----------------------------------------------------------------------------


def test_a_body_under_the_cap_reads_through_whole() -> None:
    assert _read_capped(_upload(b"hello"), max_bytes=10) == b"hello"


def test_a_body_at_exactly_the_cap_is_accepted() -> None:
    assert _read_capped(_upload(b"12345"), max_bytes=5) == b"12345"


def test_a_body_over_the_cap_is_refused_with_a_413() -> None:
    with pytest.raises(HTTPException) as raised:
        _read_capped(_upload(b"123456"), max_bytes=5)

    assert raised.value.status_code == 413
    assert raised.value.detail["error"]["code"] == "attachment_too_large"


def test_an_empty_body_is_accepted_as_zero_bytes() -> None:
    assert _read_capped(_upload(b""), max_bytes=5) == b""
