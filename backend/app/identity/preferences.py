"""Per-account preferences: a small key/value table (KAN-1815).

One row per ``(user_id, key)``, ``ON DELETE CASCADE`` from ``kaya_account``. A key/value table
rather than a column on ``KayaAccount`` because the next preference should cost a registry entry
here and nothing else — no migration, no model change on the identity table.

**An absent row means the registry's default.** That is how every existing account came to have
"format on save" ON with no backfill: nothing was written for them, and the default is applied at
read time. It also means a preference never has to be *created* before it can be read.

``PREFERENCES`` is the closed set of keys the API will read or write; a key not in it is not
storable (the API's body schema is built from the same names), so this table cannot become a
free-form dumping ground by accident.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.models.base import Base


class UserPreference(Base):
    """One stored preference value for one account. Absent row == the registry default."""

    __tablename__ = "user_preference"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_user_preference_user_id_key"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("kaya_account.id", ondelete="cascade"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


@dataclass(frozen=True)
class PreferenceSpec:
    key: str
    default: Any


FORMAT_ON_SAVE = "format_on_save"

PREFERENCES: dict[str, PreferenceSpec] = {
    FORMAT_ON_SAVE: PreferenceSpec(FORMAT_ON_SAVE, True),
}


def read_preferences(db: Session, user_id: uuid.UUID) -> dict[str, Any]:
    """Every registered preference for `user_id`, defaults filled in for absent rows."""
    stored = {
        row.key: row.value
        for row in db.scalars(select(UserPreference).where(UserPreference.user_id == user_id))
    }
    return {key: stored.get(key, spec.default) for key, spec in PREFERENCES.items()}


def write_preference(db: Session, user_id: uuid.UUID, key: str, value: Any) -> None:
    """Upsert one registered preference. The caller commits."""
    if key not in PREFERENCES:
        raise KeyError(key)
    row = db.scalar(
        select(UserPreference).where(UserPreference.user_id == user_id, UserPreference.key == key)
    )
    if row is None:
        db.add(UserPreference(user_id=user_id, key=key, value=value))
    else:
        row.value = value
        row.updated_at = func.now()
