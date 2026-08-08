"""ADR 0005 §contract 3's ``arg`` slot, specified against every error the backend actually emits.

``_implied_arg`` reads **the first scalar extra, in insertion order**. That is a rule with a shape:
it is unambiguous only while a refusal carries at most one scalar, and it is unambiguous against
every ``error_body(...)`` call site in `backend/app/` today — checked one by one, and enumerated
below with its source named. So the risk is real and currently unreachable, and the job of this file
is to make sure it stays that way *out loud* rather than by luck.

Three things are pinned here:

1. **A regression corpus.** Every backend error shape, with the ``arg`` it resolves to. Fixtures
   rather than an import: the dependency arrow runs `kaya-cli` → `kaya-client`, and never to
   `backend/`. A client that imported the API's error module would be a client that could not be
   installed without it.
2. **The `409`, explicitly.** ADR 0009 puts two whole notes in that refusal so a caller can diff
   them, and the error layer must not be where they get lost. ``arg`` is ``""`` because neither
   extra is a scalar, and both objects survive whole in the structured form.
3. **The tie-break itself.** A body with two scalar extras resolves to the first in insertion order.
   Nothing produces one today; pinning it makes the behaviour *specified* rather than emergent, so a
   backend change that makes it wrong lands on a test that states the rule and has to be argued
   with rather than on silence.

The other half of this guard lives in `backend/tests/unit/test_error_extras_stay_addressable.py`,
where the change would actually be made. This file cannot see a new backend extra; that one can.
"""

import pytest

from kaya_client import ARG_KEY, ERROR_MARKER, AdapterFormat, ApiError, error_payload, render_error

# Every `error_body(...)` call site in `backend/app/`, copied rather than imported, with the file
# it came from. When one of these changes, `backend/tests/unit/test_error_extras_stay_addressable`
# is what will have gone red first.
BACKEND_SHAPES: list[tuple[str, int, dict[str, object], str]] = [
    (
        "app/auth/resolver.py — principal_from_bearer, no credential",
        401,
        {"code": "authentication_required", "message": "a bearer token is required"},
        "",
    ),
    (
        "app/auth/resolver.py — TokenRejected",
        401,
        {"code": "invalid_token", "message": "pandan did not accept this token"},
        "",
    ),
    (
        "app/auth/resolver.py — Q9's 503, upstream named",
        503,
        {
            "code": "upstream_unavailable",
            "message": "kaya could not reach pandan to resolve this token: timed out",
            "upstream": "pandan",
        },
        "pandan",
    ),
    (
        "app/auth/authorization.py — a missing note",
        404,
        {"code": "note_not_found", "message": "no such note"},
        "",
    ),
    (
        "app/auth/authorization.py — someone else's note",
        403,
        {"code": "note_forbidden", "message": "this note belongs to another user"},
        "",
    ),
    (
        "app/api/refs.py — invalid_note_ref, the offending segment echoed back",
        400,
        {
            "code": "invalid_note_ref",
            "message": "not a note reference: '#NOTE-12'. Use NOTE-12, note-12 or 12.",
            "ref": "#NOTE-12",
        },
        "#NOTE-12",
    ),
    (
        "app/api/errors.py — handle_validation_error, the first offending field",
        422,
        {"code": "invalid_request", "message": "title: field required", "field": "title"},
        "title",
    ),
    (
        "app/api/errors.py — code_for_status, Starlette's own 405",
        405,
        {"code": "method_not_allowed", "message": "Method Not Allowed"},
        "",
    ),
    (
        "app/api/concurrency.py — ADR 0009's 409, two whole notes",
        409,
        {
            "code": "note_conflict",
            "message": "NOTE-12 has changed since you read it. Nothing was written.",
            "attempted": {"ref": "NOTE-12", "body": "mine"},
            "stored": {"ref": "NOTE-12", "body": "theirs"},
        },
        "",
    ),
    (
        "kaya_client.client._error_payload — a proxy's non-JSON 502",
        502,
        {"code": "http_error", "message": "the API answered 502", "status": "502"},
        "502",
    ),
]


@pytest.mark.parametrize(
    ("source", "status", "error", "expected"),
    BACKEND_SHAPES,
    ids=[shape[0].split(" — ")[1] for shape in BACKEND_SHAPES],
)
def test_every_backend_error_shape_resolves_the_documented_arg(
    source: str, status: int, error: dict[str, object], expected: str
) -> None:
    """The corpus. One row per refusal kaya can actually produce, ``arg`` written out."""
    failure = ApiError(status, {"error": error})

    assert error_payload(failure)[ERROR_MARKER][ARG_KEY] == expected, source


@pytest.mark.parametrize(
    ("source", "status", "error", "expected"), BACKEND_SHAPES, ids=[s[0] for s in BACKEND_SHAPES]
)
def test_no_backend_shape_carries_two_scalar_extras(
    source: str, status: int, error: dict[str, object], expected: str
) -> None:
    """The precondition ``_implied_arg``'s rule needs, asserted over the corpus rather than assumed.

    While every refusal carries at most one scalar, "first scalar in insertion order" has nothing to
    choose between and the heuristic is a description rather than a decision. This is the assertion
    that would go red if the corpus above were updated to a backend that had stopped being true —
    and `backend/tests/unit/test_error_extras_stay_addressable` is what makes someone update it.
    """
    scalars = [
        key
        for key, value in error.items()
        if key not in ("code", "message")
        and isinstance(value, str | int | float)
        and not isinstance(value, bool)
    ]

    assert len(scalars) <= 1, f"{source}: two scalars make the arg slot a coin toss — {scalars}"


def test_the_conflict_keeps_two_whole_notes_and_still_has_an_empty_arg() -> None:
    """ADR 0009, carried through the error layer intact.

    The `409` exists so a caller can diff ``attempted`` against ``stored`` and retry. Both are
    objects, so there is nothing for a tab-separated column to hold and ``arg`` is correctly ``""``
    — and that emptiness must cost nothing: the structured form still carries both notes whole.
    A layer that flattened them to make the row prettier would break the one refusal whose whole
    value is its payload.
    """
    _, status, error, _ = BACKEND_SHAPES[-2]
    failure = ApiError(status, dict(error=error))

    rendered = render_error(failure, fmt=AdapterFormat.DATA)
    assert isinstance(rendered, dict)
    detail = rendered[ERROR_MARKER]

    assert detail[ARG_KEY] == ""
    assert detail["attempted"] == {"ref": "NOTE-12", "body": "mine"}
    assert detail["stored"] == {"ref": "NOTE-12", "body": "theirs"}

    row = render_error(failure)
    assert isinstance(row, str)
    assert row.endswith("\t"), "the empty arg is still a field; the row keeps its four"


def test_two_scalar_extras_resolve_to_the_first_in_insertion_order() -> None:
    """The tie-break, specified rather than emergent.

    Nothing in `backend/app/` produces this today. It is pinned anyway, because a heuristic with no
    test is a behaviour nobody chose: the day a backend refusal grows a second scalar, this is the
    assertion that states what will happen, and whoever made that change has to read it and decide
    whether the first key is still the one the caller wants in the ``arg`` slot.
    """
    failure = ApiError(
        418,
        {"error": {"code": "two_scalars", "message": "no", "ref": "NOTE-12", "field": "title"}},
    )

    assert error_payload(failure)[ERROR_MARKER][ARG_KEY] == "NOTE-12"


def test_a_scalar_after_an_object_is_still_found() -> None:
    """Insertion order, not "the first extra". An object in the way is skipped rather than fatal."""
    failure = ApiError(
        409,
        {
            "error": {
                "code": "mixed",
                "message": "no",
                "stored": {"ref": "NOTE-12"},
                "ref": "NOTE-12",
            }
        },
    )

    assert error_payload(failure)[ERROR_MARKER][ARG_KEY] == "NOTE-12"


def test_a_boolean_is_not_a_scalar_for_this_purpose() -> None:
    """``arg`` names the thing a refusal is *about*. ``retryable=true`` is a flag, not a subject,
    and rendering it as ``True`` in the fourth column would be a fact with no referent."""
    failure = ApiError(
        503,
        {"error": {"code": "flagged", "message": "no", "retryable": True, "upstream": "pandan"}},
    )

    assert error_payload(failure)[ERROR_MARKER][ARG_KEY] == "pandan"
