"""ADR 0008's identity decision, held to by the metadata itself.

No infrastructure: every assertion here reads ``Base.metadata`` or the text of migration ``0001``.
The behavioural half — that the sequence really does allocate atomically, and that the migration
really does round-trip — is in ``tests/integration/test_migration_0001.py``.

What these tests defend is the set of things that look like harmless tidying and are not:
renaming the prefix, adding a unique index on ``path``, or letting the model and the migration
drift apart on the SQL that mints a ref.
"""

import re
from pathlib import Path

import pytest

from app.models import (
    NOTE_REF_PREFIX,
    NOTE_REF_SEQUENCE,
    NOTE_REF_SEQUENCE_NAME,
    Base,
    Note,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_0001 = (
    BACKEND_ROOT / "alembic" / "versions" / "0001_user_mirror_note_and_the_note_sequence.py"
)
NOTE_MODEL = BACKEND_ROOT / "app" / "models" / "note.py"


# --- the note ----------------------------------------------------------------------------------
#
# The "user mirror" section this file used to carry here (ADR 0002's pandan-mirror `User` model)
# was deleted in KAN-1740: migration `0009` drops the `user` table entirely and `app/models/user.py`
# is gone. `note.owner_id` now points at `app.identity.models.KayaAccount` instead — see
# `test_owner_points_at_kaya_account_and_will_not_cascade` below.


def test_the_ref_is_unique_and_allocated_by_the_database() -> None:
    ref = Note.__table__.c.ref

    assert ref.unique is True
    assert ref.nullable is False
    assert ref.default is None, "a Python-side default would race; the sequence must do this"
    assert NOTE_REF_SEQUENCE_NAME in str(ref.server_default.arg)


def test_the_sequence_reaches_metadata() -> None:
    """``create_all`` has to emit it, and nothing else in the metadata will pull it in — a sequence
    referenced only from a `server_default` string is invisible to SQLAlchemy."""
    assert NOTE_REF_SEQUENCE.metadata is Base.metadata
    assert NOTE_REF_SEQUENCE.name == NOTE_REF_SEQUENCE_NAME


def test_path_carries_no_uniqueness_and_no_index() -> None:
    """The whole of ADR 0008 in one assertion.

    A unique path is path-as-identity wearing a different hat: it makes a move able to fail, which
    is the Obsidian behaviour this schema exists to avoid. If a future slice wants fast lookup by
    path it adds a **non-unique** index and this test grows a carve-out for it deliberately.
    """
    path = Note.__table__.c.path

    assert path.unique is not True
    assert path.index is not True
    indexed = {tuple(c.name for c in index.columns) for index in Note.__table__.indexes}
    assert ("path",) not in indexed


def test_owner_points_at_kaya_account_and_will_not_cascade() -> None:
    """Since KAN-1740's cutover (ADR 0012) — before it, this pointed at `user.id`, the pandan-mirror
    table migration `0009` dropped."""
    (foreign_key,) = list(Note.__table__.c.owner_id.foreign_keys)

    assert foreign_key.target_fullname == "kaya_account.id"
    assert foreign_key.ondelete == "RESTRICT", (
        "CASCADE would let deleting someone's account silently delete their notes with it"
    )
    assert Note.__table__.c.owner_id.index is True, "every read is scoped by owner"


def test_updated_at_restamps_itself_on_every_write() -> None:
    """ADR 0009 uses this column as the optimistic-concurrency token, so a write that leaves it
    unchanged silently defeats the `409`."""
    assert Note.__table__.c.updated_at.onupdate is not None
    assert Note.__table__.c.updated_at.type.timezone is True


# --- the prefix, which is permanent --------------------------------------------------------------


def test_the_prefix_is_the_one_adr_0008_settled() -> None:
    assert NOTE_REF_PREFIX == "NOTE-"


@pytest.mark.parametrize("path", [NOTE_MODEL, MIGRATION_0001], ids=["model", "migration"])
def test_both_copies_carry_the_immutability_comment(path: Path) -> None:
    """ADR 0008 §Decision asks for a comment at the sequence saying the prefix can never change.

    It is required in *both* places because they are read at different moments: the model by
    whoever is adding a column, the migration by whoever is grepping history during a rename.
    Pandan's ADR 0018 is the precedent — its prefixes survived a full rebrand precisely because
    someone wrote down why they had to.
    """
    text = path.read_text(encoding="utf-8")

    assert "PERMANENT" in text
    assert "ADR 0018" in text, "the precedent is half the argument; cite it"


def test_the_model_and_the_migration_mint_refs_the_same_way() -> None:
    """Two hand-written copies of one SQL expression, kept honest.

    The migration is deliberately standalone (it must not import models — it is a snapshot of a
    schema, not of today's code), so the expression exists twice. This is the seam where a rename
    would land in one file and not the other, and the database would then hand out refs from a
    sequence nothing in the application believes in.
    """
    expected = f"'{NOTE_REF_PREFIX}' || nextval('{NOTE_REF_SEQUENCE_NAME}')"

    assert str(Note.__table__.c.ref.server_default.arg) == expected
    assert expected in MIGRATION_0001.read_text(encoding="utf-8")


def test_migration_0001_is_the_root_revision() -> None:
    source = MIGRATION_0001.read_text(encoding="utf-8")

    assert re.search(r"^revision: str = \"0001\"$", source, re.MULTILINE)
    assert re.search(r"^down_revision: str \| None = None$", source, re.MULTILINE)


def test_the_migration_creates_and_drops_the_sequence_by_hand() -> None:
    """Alembic autogenerate does not detect sequences. If someone regenerates this revision and
    pastes the output over it, both statements vanish and `upgrade` fails on the missing sequence
    — but only against a *fresh* database, so it can survive review."""
    source = MIGRATION_0001.read_text(encoding="utf-8")

    assert "CreateSequence" in source
    assert "DropSequence" in source
