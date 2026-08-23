"""ADR 0005 §contract 4, pinned by **literal values** so a renumber cannot be quiet.

Every assertion here is written ``== 5``, never ``== EXIT_FOR_CODE["not_found"]``. A test derived
from the table it is testing passes for any table, which is the failure mode SLICES marks this
`[mutate]` for: the numbers came from pandan verbatim precisely so that an operator scripting both
tools never has to remember which is which, and the only thing standing between that promise and a
tidy-minded refactor is a test that says the number out loud.

The table is **add-only**. That is a property of a diff rather than of a value, so it is tested as
one: each shipped row is pinned individually and the table is checked as a *superset*, so adding a
row reddens nothing and changing one reddens exactly the row that moved.
"""

import pytest
from kaya_client import ApiError, KayaError, TransportError, UnknownFormat, UsageError

from kaya_cli.failures import (
    EXIT_CONFLICT,
    EXIT_FOR_CODE,
    EXIT_FOR_STATUS,
    EXIT_FORBIDDEN,
    EXIT_NOT_FOUND,
    EXIT_OK,
    EXIT_RUNTIME,
    EXIT_UNAUTHENTICATED,
    EXIT_USAGE,
    exit_code_for,
)

# ---------------------------------------------------------- the seven numbers


def test_ok_is_zero() -> None:
    assert EXIT_OK == 0


def test_runtime_is_one() -> None:
    assert EXIT_RUNTIME == 1


def test_usage_is_two() -> None:
    """Argparse's own number. It is `2` because argparse says `2`, not because it is tidy."""
    assert EXIT_USAGE == 2


def test_unauthenticated_is_three() -> None:
    assert EXIT_UNAUTHENTICATED == 3


def test_forbidden_is_four() -> None:
    assert EXIT_FORBIDDEN == 4


def test_not_found_is_five() -> None:
    assert EXIT_NOT_FOUND == 5


def test_conflict_is_six() -> None:
    """KAN-724, and the first number this repository chose rather than inherited. `6` because it is
    the next one, and it exists because ADR 0009's `409` is the one refusal where the caller did
    nothing wrong, kaya did not fail, and re-read-and-retry is the correct action."""
    assert EXIT_CONFLICT == 6


def test_the_seven_meanings_are_seven_distinct_numbers() -> None:
    """Two meanings sharing a number is the same bug as a renumber, arriving from the other side.

    Seven since KAN-724. The six below `6` are in the order and at the values V2a published them,
    which is the add-only rule read off one list: a meaning arrived at the end and nothing moved.
    """
    numbers = [
        EXIT_OK,
        EXIT_RUNTIME,
        EXIT_USAGE,
        EXIT_UNAUTHENTICATED,
        EXIT_FORBIDDEN,
        EXIT_NOT_FOUND,
        EXIT_CONFLICT,
    ]

    assert numbers == [0, 1, 2, 3, 4, 5, 6]
    assert len(set(numbers)) == 7


# ---------------------------------------------------------- the named-code table

SHIPPED_ROWS = {
    "usage": 2,
    "unreachable": 1,
    "runtime": 1,
}
"""Every row as shipped, written as literals. Adding a code adds a row *here* too — that is the
add-only rule expressed as the smallest possible chore, and it is what makes the diff say so."""


@pytest.mark.parametrize(("code", "number"), sorted(SHIPPED_ROWS.items()))
def test_each_shipped_row_maps_to_its_documented_number(code: str, number: int) -> None:
    assert EXIT_FOR_CODE[code] == number


def test_the_table_is_add_only_not_replace_only() -> None:
    """A superset check, so a *new* code is not a red test.

    Written as a superset on purpose. An equality check here would make adding a meaning — which is
    free and expected, KAN-541 and V2b both do it — indistinguishable from renumbering one, which is
    the thing that must never happen quietly.
    """
    assert SHIPPED_ROWS.items() <= dict(EXIT_FOR_CODE).items()


def test_no_row_maps_outside_the_published_range() -> None:
    """A row still has to name one of the *published* meanings. `8` is not a meaning anybody has.

    Both tables, because KAN-718 established that ``EXIT_FOR_STATUS`` grows too — a row added there
    is a status acquiring a published meaning, never a number invented at the table.

    KAN-724 widened this set to include `6`, and that is the one edit here that is not free: a new
    number is published by `failures.py` naming it and by ADR 0005 §contract 4's table carrying it,
    so widening this literal is the second half of that and belongs in the same diff as the first.
    A row pointing at `7` is still red, because `7` names nothing.
    """
    assert set(EXIT_FOR_CODE.values()) <= {0, 1, 2, 3, 4, 5, 6}
    assert set(EXIT_FOR_STATUS.values()) <= {0, 1, 2, 3, 4, 5, 6}


def test_the_table_cannot_be_mutated_at_runtime() -> None:
    """A verb registering a code by writing to the table would be a contract changed at import time
    and visible in no diff. Adding one is editing `failures.py`, where a reviewer sees it."""
    with pytest.raises(TypeError):
        EXIT_FOR_CODE["improvised"] = 9  # type: ignore[index]


def test_every_client_side_failure_class_has_a_row() -> None:
    """The tripwire for "a new failure class arrived without a meaning".

    Without this, a class added to `kaya_client.errors` with a fresh ``code`` silently exits `1`,
    and the first person to notice is whoever wrote a script around the number it should have had.
    """
    codes = {cls.code for cls in (KayaError, UsageError, UnknownFormat, TransportError)}

    assert codes <= set(EXIT_FOR_CODE)


# ------------------------------------------------------------- status → meaning


def test_the_four_status_rows_map_to_their_documented_numbers() -> None:
    """Literals again, and the reason `errors.py` says the table is keyed on meaning for these.

    `400` is KAN-718's row and is `2`, the number argparse already owns. Adding it moved nothing:
    the three rows below it are the same numbers this test asserted the day it was written, which is
    the add-only rule visible as a diff — one line added, none edited. `422` is KAN-839's row and
    reuses the same `2`, on the same argument as `400`'s.
    """
    assert EXIT_FOR_STATUS[400] == 2
    assert EXIT_FOR_STATUS[401] == 3
    assert EXIT_FOR_STATUS[403] == 4
    assert EXIT_FOR_STATUS[404] == 5
    assert EXIT_FOR_STATUS[409] == 6
    assert EXIT_FOR_STATUS[422] == 2


def test_the_status_table_is_add_only_too() -> None:
    """A superset, for the same reason ``EXIT_FOR_CODE``'s is one: KAN-718 adds a row and reddens
    nothing, while moving `404` off `5` reddens exactly the row that moved. KAN-724's `409` and
    KAN-839's `422` are both in the literal below now, so each is pinned as tightly as the rows
    before it."""
    assert {400: 2, 401: 3, 403: 4, 404: 5, 409: 6, 422: 2}.items() <= dict(EXIT_FOR_STATUS).items()


@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        (400, "invalid_note_ref", 2),
        (400, "a_400_code_this_package_has_never_heard_of", 2),
        (401, "authentication_required", 3),
        (401, "invalid_token", 3),
        (403, "note_forbidden", 4),
        (404, "note_not_found", 5),
        (404, "not_found", 5),
        (409, "note_conflict", 6),
        (409, "a_409_code_this_package_has_never_heard_of", 6),
        (422, "invalid_request", 2),
        (422, "a_422_code_this_package_has_never_heard_of", 2),
    ],
)
def test_a_refusal_is_keyed_on_its_status_not_on_the_apis_code_string(
    status: int, code: str, expected: int
) -> None:
    """The backend's code vocabulary grows without this package's knowledge — four different
    strings above already mean the same three things — and a new `404` code must still exit `5`.
    Keying on the status is the only version of that which cannot go stale."""
    failure = ApiError(status, {"error": {"code": code, "message": "no"}})

    assert exit_code_for(failure) == expected


@pytest.mark.parametrize("status", [500, 503])
def test_a_refusal_with_no_row_is_runtime_not_usage(status: int) -> None:
    """`1`, not `2`. A failure the table has no row for is not evidence that argv was wrong, and
    reporting "usage" for a server-side `503` sends a caller to re-read the manual over a refusal
    that had nothing to do with what they typed.

    `400` used to be in this list and is now a row of its own (KAN-718); `409` left it the same way
    with KAN-724; `422` left it the same way with KAN-839. The rule they were proving is untouched:
    the default is still `1`, and all three left by *acquiring a meaning*, not by the default being
    widened to cover statuses nobody decided about. `422` no longer stays here: KAN-724's docstring
    argued it needed no number because its `code` string already named the action better than one
    could, but that argument was never checked against what actually raises a `422` in `backend/` —
    KAN-839 did, found `handle_validation_error` is the only source, and moved it to `EXIT_USAGE`
    alongside `400` for the identical reason. See `kaya_cli.failures` for the full argument.
    """
    failure = ApiError(status, {"error": {"code": "something_new", "message": "no"}})

    assert exit_code_for(failure) == 1


def test_a_malformed_ref_is_the_callers_error_not_a_runtime_failure() -> None:
    """KAN-718, with the exact body `backend/app/api/refs.py` builds — ``ref`` extra and all.

    ADR 0008 makes `#NOTE-12` a `400` deliberately: `404` would answer "no such note" about a string
    that is not a note reference at all. That makes a `400` a *designed* outcome of the central ref
    resolver rather than an edge case, so exit `1` was telling every script that a typo was kaya
    failing — and a script branching on exit codes would plausibly retry it forever.
    """
    failure = ApiError(
        400,
        {
            "error": {
                "code": "invalid_note_ref",
                "message": "not a note reference: '#NOTE-12'. Use NOTE-12, note-12 or 12.",
                "ref": "#NOTE-12",
            }
        },
    )

    assert exit_code_for(failure) == 2


def test_a_malformed_precondition_is_the_callers_error_not_a_runtime_failure() -> None:
    """KAN-839, with the exact body `backend/app/api/errors.py::handle_validation_error` builds for
    the card's own reproduction — ``kaya note edit NOTE-11 --body x --if-updated-at nope``.

    `422` here is schema validation and nothing else: ``if_updated_at`` failed to parse as an
    aware datetime, which is a typo in argv exactly as `#NOTE-12` is, and is exactly as
    unretryable without editing the command. `arg` carries the field name (`_implied_arg` reads
    it off `field`), so a caller reading the row learns what was rejected without a second
    request — the same shape `refs.py`'s `ref` extra gives `400`.
    """
    failure = ApiError(
        422,
        {
            "error": {
                "code": "invalid_request",
                "message": "if_updated_at: Input should be a valid datetime or date, input is "
                "too short",
                "field": "if_updated_at",
            }
        },
    )

    assert exit_code_for(failure) == 2


# ------------------------------------------------------- meaning → number, end to end


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (UsageError("unrecognized arguments: --nope"), 2),
        (UnknownFormat("unknown format 'hunan'"), 2),
        (TransportError("https://kaya.example is unreachable"), 1),
        (KayaError("something"), 1),
        (ApiError(400, {"error": {"code": "invalid_note_ref", "message": "no"}}), 2),
        (ApiError(401, {"error": {"code": "invalid_token", "message": "no"}}), 3),
        (ApiError(403, {"error": {"code": "note_forbidden", "message": "no"}}), 4),
        (ApiError(404, {"error": {"code": "note_not_found", "message": "no"}}), 5),
        (ApiError(409, {"error": {"code": "note_conflict", "message": "no"}}), 6),
        (ApiError(422, {"error": {"code": "invalid_request", "message": "no"}}), 2),
    ],
)
def test_each_failure_class_reaches_its_number(failure: BaseException, expected: int) -> None:
    """The whole table as one parametrised assertion, with literal numbers on the right.

    These are the failure classes KAN-541's verbs will be the first to produce for real. Proven here
    at the seam because there is no verb yet to produce them end to end — which is the sequencing
    working, not a gap: when 541 lands, its assertions check the wiring and this file still owns the
    numbers.
    """
    assert exit_code_for(failure) == expected


def test_an_unrecognised_exception_is_runtime() -> None:
    """Nothing should reach here that is not a ``KayaError``. Something eventually will."""
    assert exit_code_for(RuntimeError("the disk is on fire")) == 1
