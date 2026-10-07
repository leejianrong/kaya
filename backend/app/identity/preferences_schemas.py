"""``/api/v1/preferences`` wire shapes (KAN-1815)."""

from pydantic import BaseModel, ConfigDict


class PreferencesRead(BaseModel):
    """Every registered preference, defaults included."""

    format_on_save: bool


class PreferencesUpdate(BaseModel):
    """A partial write: only the fields sent are changed. Unknown keys are a 422, not ignored —
    a typo'd preference name that silently does nothing is worse than a refusal."""

    model_config = ConfigDict(extra="forbid")

    format_on_save: bool | None = None
