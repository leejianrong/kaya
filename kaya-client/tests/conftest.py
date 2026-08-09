"""The corpus every shaping test renders.

Copied from what `/api/v1/notes` actually returns rather than invented: `NoteRead` in
`backend/app/api/schemas.py` fixes the seven keys, the timestamps carry their offset, and
``updated_at`` keeps microseconds because ADR 0009's precondition compares to the microsecond. A
fixture that rounded them would be testing a payload kaya never emits.

The two notes are chosen to make the alignment assertions mean something: the shorter ``ref``
belongs to the longer ``title``, so a row is wrong in a visible way if either column's width is
computed from the wrong axis, and one note has an empty ``path`` and an empty ``body`` because
`NoteCreate` defaults both to ``""`` and a note created from a title alone is the common case.
"""

from typing import Any

import pytest

from kaya_client import config
from kaya_client.client import (
    NOTE_COLUMNS,
    NOTE_ENVELOPE,
    NOTE_LIST_COLUMNS,
    NOTE_NOUN,
    NOTE_PROSE_FIELDS,
)
from kaya_client.hints import HELP_PREFIX
from kaya_client.payloads import Payload

GROCERIES: dict[str, Any] = {
    "ref": "NOTE-12",
    "id": 12,
    "title": "Groceries",
    "body": "milk\neggs",
    "path": "home/groceries.md",
    "created_at": "2026-08-01T09:15:00+00:00",
    "updated_at": "2026-08-09T11:02:33.123456+00:00",
}

READING_LIST: dict[str, Any] = {
    "ref": "NOTE-3",
    "id": 3,
    "title": "A reading list",
    "body": "",
    "path": "",
    "created_at": "2026-07-14T18:00:00+00:00",
    "updated_at": "2026-07-14T18:00:00+00:00",
}

NOTE_LIST_BODY: dict[str, Any] = {"notes": [GROCERIES, READING_LIST]}


def note_collection(*records: dict[str, Any]) -> Payload:
    return Payload.collection(
        noun=NOTE_NOUN,
        envelope_key=NOTE_ENVELOPE,
        records=records,
        columns=NOTE_LIST_COLUMNS,
        prose_fields=NOTE_PROSE_FIELDS,
    )


def note_entity(record: dict[str, Any]) -> Payload:
    return Payload.entity(
        noun=NOTE_NOUN,
        envelope_key=NOTE_ENVELOPE,
        record=record,
        columns=NOTE_COLUMNS,
        prose_fields=NOTE_PROSE_FIELDS,
    )


def without_help(rendered: object) -> str:
    """A ``human`` render with KAN-550's trailing ``help:`` block taken back off.

    Every human render gained one (ADR 0005 §contract 8), which would otherwise turn every
    assertion about the *end* of an output — KAN-548's footer, KAN-547's truncation hint — into an
    assertion about the hints. This keeps those tests about the thing they were written for, and
    keeps them failing if their own subject moves.

    It strips a trailing run of ``help:`` lines and the blank line above them, rather than slicing a
    known length off, so a test using it does not have to know how many templates a payload happens
    to carry. `test_hints.py` and `test_human_row_is_pinned.py` are where the block itself is
    asserted, in full, against literals — this helper is never on that path.
    """
    assert isinstance(rendered, str)
    lines = rendered.splitlines()
    while lines and lines[-1].startswith(HELP_PREFIX):
        lines.pop()
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


@pytest.fixture
def notes() -> Payload:
    """The `note list` payload: two notes, in the API's own order."""
    return note_collection(GROCERIES, READING_LIST)


@pytest.fixture
def note() -> Payload:
    """The `note get` payload: one note."""
    return note_entity(GROCERIES)


@pytest.fixture(autouse=True)
def no_ambient_configuration(monkeypatch, tmp_path) -> None:
    """No deployment, no credential, no text limit, and a config directory nobody else owns.

    `kaya_client.config` resolves from the environment and then from a file on disk, so without
    this a developer with a PAT exported would have `open_client()` reach a real deployment from
    the fast test layer, and `write_settings` would edit their own
    ``~/.config/kaya/config.json``. Both variables that locate the file are redirected, not only
    the first: a test that cleared ``XDG_CONFIG_HOME`` would otherwise fall through to ``HOME``.

    Autouse rather than opt-in, for the reason the CLI's copy gives — a test that forgot to ask
    would pass on a laptop with nothing configured and fail on one that has been used.
    """
    for name in (config.API_URL_ENV, config.TOKEN_ENV, config.MAX_TEXT_CHARS_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(config.CONFIG_HOME_ENV, str(tmp_path / "xdg"))
    monkeypatch.setenv(config.HOME_ENV, str(tmp_path / "home"))
