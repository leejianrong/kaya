"""The central ref resolver, with no database and no framework.

ADR 0008 asks for two things and they are tested differently. The **grammar** (``NOTE-12``,
``note-12``, ``12`` in; ``#NOTE-12`` out) is a pure function and belongs here. The **property** —
that both spellings produce identical results including identical error codes — is asserted here
against a fake session and again in ``tests/integration/test_notes_api.py`` over real HTTP, because
a property about two code paths is only proven where both paths actually run.

What the fake session buys that Postgres cannot: the statements themselves. A test that only
compares two `404` bodies passes against an implementation where the two spellings diverge somewhere
harmless today, and the divergence is what eventually grows a different error code. Here the
statements are captured, so "the only difference between the spellings is which column is matched"
is checked directly.
"""

from typing import Any

import pytest
from fakes import ALICE
from fastapi import HTTPException

from app.api.refs import (
    POSTGRES_INTEGER_MAX,
    NoteRef,
    invalid_note_ref,
    parse_note_ref,
    resolve_note,
)
from app.auth.authorization import note_addressed_as_id, note_addressed_as_ref

# --- The grammar --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    ["NOTE-12", "note-12", "NoTe-12", "nOTE-12"],
    ids=["upper", "lower", "mixed", "ragged"],
)
def test_the_prefixed_form_is_case_insensitive(raw: str) -> None:
    parsed = parse_note_ref(raw)

    assert parsed == NoteRef(number=12, prefixed=True)
    assert parsed.canonical == "NOTE-12", "case is normalised so the unique index is usable"


def test_a_bare_integer_is_accepted_and_remembered_as_the_other_name() -> None:
    """SLICES §V1: "the ref parser accepts `NOTE-12`, `note-12`, `12`"."""
    parsed = parse_note_ref("12")

    assert parsed.number == 12
    assert parsed.prefixed is False, "a bare integer addresses `id`, not the ref minus its prefix"


def test_a_leading_hash_is_rejected() -> None:
    """The case ADR 0008 §Decision pins by name.

    "Leniency beyond that is not a goal — a leading `#` is a usage error, pinned by a test, because
    leniency in an identifier parser buys a future ambiguity for no measured need."
    """
    with pytest.raises(HTTPException) as raised:
        parse_note_ref("#NOTE-12")

    assert raised.value.status_code == 400
    assert raised.value.detail["error"]["code"] == "invalid_note_ref"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "NOTE-",
        "NOTE12",
        "note_12",
        "KAN-12",
        "-12",
        "+12",
        "12.0",
        "12a",
        "NOTE-12-old",
        " 12",
        "12 ",
        "NOTE 12",
        "[[NOTE-12]]",
        "NOTE-12|alias",
        "٣",
    ],
    ids=[
        "empty",
        "prefix-alone",
        "no-separator",
        "wrong-separator",
        "another-app's-prefix",
        "signed-negative",
        "signed-positive",
        "decimal",
        "trailing-letter",
        "trailing-suffix",
        "leading-space",
        "trailing-space",
        "space-for-hyphen",
        "wikilink-brackets",
        "wikilink-alias",
        "non-ascii-digit",
    ],
)
def test_everything_else_is_a_usage_error(raw: str) -> None:
    """``fullmatch``, not ``match``, and nothing stripped first.

    ``NOTE-12-old`` is the one to keep an eye on: under ``re.match`` it resolves to ``NOTE-12``
    silently, which is a caller getting a different note from the one it named. The non-ASCII digit
    is here because ``\\d`` under ``re.UNICODE`` — Python's default — matches Arabic-Indic digits,
    and ``int()`` cheerfully converts them, so ``٣`` and ``3`` would be two spellings of one ref
    that nothing else in the stack agrees on.
    """
    with pytest.raises(HTTPException) as raised:
        parse_note_ref(raw)

    assert raised.value.status_code == 400


def test_the_usage_error_is_not_a_miss() -> None:
    """`400`, not `404`. A typo and a genuine miss are different facts, and a caller that cannot
    tell them apart retries the typo."""
    assert invalid_note_ref("#NOTE-12").status_code == 400
    assert invalid_note_ref("#NOTE-12").status_code != 404


def test_the_usage_error_names_what_it_rejected() -> None:
    body = invalid_note_ref("[[NOTE-12]]").detail["error"]

    assert body["ref"] == "[[NOTE-12]]"
    assert "NOTE-12" in body["message"], "the message shows an accepted form"


# --- The two statements -------------------------------------------------------------------------


def compiled(statement: Any) -> str:
    return str(statement.compile())


def test_each_spelling_matches_its_own_column() -> None:
    """ADR 0008 lists ``id`` and the ``NOTE-n`` ref as two distinct names. They come from two
    sequences, so they are not interchangeable and neither is derivable from the other."""
    assert "note.ref = " in compiled(note_addressed_as_ref("NOTE-12"))
    assert "note.id = " in compiled(note_addressed_as_id(12))


def test_a_single_note_fetch_is_deliberately_not_owner_scoped() -> None:
    """The counterpart to ``notes_owned_by``, and the reason `403` is possible at all.

    A fetch filtered on the owner comes back empty for somebody else's note, and the caller is then
    told `404` — a different promise from the one PLAN §Authorization and SLICES §V1 make. This
    assertion is the one that should fail loudly if someone "hardens" these two statements.
    """
    for statement in (note_addressed_as_ref("NOTE-12"), note_addressed_as_id(12)):
        # `owner_id` in the projection is a column being read; in the `WHERE` it is a filter.
        assert "WHERE note.owner_id" not in compiled(statement)
        assert compiled(statement).count("WHERE") == 1, "one predicate, on the addressing column"


# --- The property: one resolution, two spellings --------------------------------------------------


class FakeSession:
    """Just enough ``Session`` for ``resolve_note``: it records statements and finds nothing."""

    def __init__(self) -> None:
        self.statements: list[Any] = []

    def scalars(self, statement: Any) -> Any:
        self.statements.append(statement)
        return self

    def one_or_none(self) -> None:
        return None


def refusal(raw: str) -> tuple[int, dict[str, Any]]:
    with pytest.raises(HTTPException) as raised:
        resolve_note(FakeSession(), ALICE, raw)  # type: ignore[arg-type]
    return raised.value.status_code, dict(raised.value.detail)


def test_a_miss_is_byte_identical_for_either_spelling() -> None:
    """SLICES §V1's `[mutate]` guard, at the level where it is cheapest to check.

    Not merely "the same code": the same status and the same body, key for key.
    ``authorize_note`` never sees an identifier, so there is nothing in the refusal that *could*
    carry one — which is why this holds structurally rather than because two branches were kept in
    step by hand.
    """
    assert refusal("NOTE-9999") == refusal("9999")
    assert refusal("NOTE-9999")[0] == 404


def test_the_spellings_differ_in_the_column_matched_and_in_nothing_else() -> None:
    by_ref, by_id = FakeSession(), FakeSession()

    with pytest.raises(HTTPException):
        resolve_note(by_ref, ALICE, "NOTE-9999")  # type: ignore[arg-type]
    with pytest.raises(HTTPException):
        resolve_note(by_id, ALICE, "9999")  # type: ignore[arg-type]

    assert len(by_ref.statements) == len(by_id.statements) == 1
    assert compiled(by_ref.statements[0]) != compiled(by_id.statements[0])
    assert compiled(by_ref.statements[0]) == compiled(note_addressed_as_ref("NOTE-9999"))
    assert compiled(by_id.statements[0]) == compiled(note_addressed_as_id(9999))


def test_a_number_too_big_for_the_id_column_is_a_miss_and_never_reaches_postgres() -> None:
    """The shape of pandan's bug, wearing bigger numbers.

    ``note.id`` is an ``INTEGER``. Handing psycopg a value above its range raises rather than
    returning nothing, so an id form would be a `500` while the ref form — a string comparison —
    stayed a `404`, and the error would once again depend on how the note was addressed. Answered in
    the resolver, without a query, so every ref-taking verb inherits it.
    """
    session = FakeSession()
    huge = str(POSTGRES_INTEGER_MAX + 1)

    with pytest.raises(HTTPException) as raised:
        resolve_note(session, ALICE, huge)  # type: ignore[arg-type]

    assert raised.value.status_code == 404
    assert session.statements == [], "the database was asked a question it cannot answer"
    assert refusal(huge) == refusal(f"NOTE-{huge}")


def test_a_number_the_id_column_can_hold_is_still_asked_about() -> None:
    """The other half: the clamp must not swallow legitimate ids near the boundary."""
    session = FakeSession()

    with pytest.raises(HTTPException):
        resolve_note(session, ALICE, str(POSTGRES_INTEGER_MAX))  # type: ignore[arg-type]

    assert len(session.statements) == 1
