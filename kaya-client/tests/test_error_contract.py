"""ADR 0005 §contract 3, at the seam it lives on rather than through a CLI that has no verbs yet.

KAN-541 brings `note list` and `note get`, so until then there is no way to make a real `404`
happen end to end. That is fine and is the sequencing working: the contract is a property of
`kaya_client`'s error layer, so it is provable by constructing the failures the client raises and
asserting on what comes out. When 541 lands, its end-to-end assertions are checking the wiring, not
the shape — the shape is already pinned here.

The corpus is copied from what the backend actually emits (`app/auth/`, `app/api/refs.py`,
`app/api/concurrency.py`), not invented, for the same reason `conftest`'s notes are.
"""

import json

import httpx
import pytest

from kaya_client import (
    ARG_KEY,
    CODE_KEY,
    CONTRACT_KEYS,
    ERROR_MARKER,
    MESSAGE_KEY,
    ROW_SEPARATOR,
    AdapterFormat,
    ApiError,
    Format,
    KayaClient,
    KayaError,
    TransportError,
    UnknownFormat,
    UsageError,
    error_payload,
    render_error,
)
from kaya_client.serialization import _ERROR_SERIALIZERS, _SERIALIZERS

# --------------------------------------------------------------- the corpus

NOT_FOUND = ApiError(404, {"error": {"code": "note_not_found", "message": "no such note"}})
"""`app/auth/authorization.py`, verbatim. No extras, so ``arg`` has nothing to be filled from."""

INVALID_REF = ApiError(
    400,
    {
        "error": {
            "code": "invalid_note_ref",
            "message": "not a note reference: '#NOTE-12'. Use NOTE-12, note-12 or 12.",
            "ref": "#NOTE-12",
        }
    },
)
"""`app/api/refs.py`. One scalar extra, which is ADR 0005's ``arg`` slot in the wild."""

CONFLICT = ApiError(
    409,
    {
        "error": {
            "code": "note_conflict",
            "message": "NOTE-12 has changed since you read it.\nNothing was written.",
            "attempted": {"ref": "NOTE-12", "body": "mine"},
            "stored": {"ref": "NOTE-12", "body": "theirs"},
        }
    },
)
"""ADR 0009's `409`: two whole notes, and a message with a newline in it. Both are load-bearing."""


# --------------------------------------------------------- all keys, always

@pytest.mark.parametrize(
    "failure",
    [NOT_FOUND, INVALID_REF, CONFLICT, TransportError("nowhere is reachable"), UsageError("no")],
)
def test_every_contract_key_is_present_whatever_failed(failure: BaseException) -> None:
    """The whole of "all keys always present", as one assertion over every failure class.

    A key that vanishes when it is empty forces every consumer to write ``if "arg" in error``, and
    a conditional on an error path is a branch nobody exercises until the day it matters.
    """
    error = error_payload(failure)[ERROR_MARKER]

    assert set(CONTRACT_KEYS) <= set(error)
    assert all(isinstance(error[key], str) for key in CONTRACT_KEYS)


def test_an_empty_arg_is_a_value_not_a_missing_key() -> None:
    """The case the rule exists for: a refusal with nothing to say in the ``arg`` slot."""
    error = error_payload(NOT_FOUND)[ERROR_MARKER]

    assert error[ARG_KEY] == ""
    assert ARG_KEY in error


def test_the_contract_keys_come_first_and_in_order() -> None:
    """So ``--format json`` output is stable byte for byte, and a human reading it finds the three
    facts that matter before the payload-specific ones."""
    assert tuple(error_payload(CONFLICT)[ERROR_MARKER])[:3] == CONTRACT_KEYS


def test_the_contract_keys_are_exactly_three() -> None:
    """A literal, so widening the guaranteed set is a conscious edit.

    ``status`` is the one that keeps being suggested. It is not here because a ``TransportError``
    has none, and a synthesised `0` would be a fact the failure does not have.
    """
    assert CONTRACT_KEYS == ("code", "message", "arg")


# ------------------------------------------------------- the whole payload survives

def test_the_api_object_arrives_unflattened() -> None:
    """ADR 0009's `409` carries two whole notes so a client can diff them.

    An error object that kept only ``code`` and ``message`` would drop the half of that response the
    caller acts on, which is why `errors.py` keeps ``ApiError.payload`` whole in the first place.
    """
    error = error_payload(CONFLICT)[ERROR_MARKER]

    assert error["attempted"] == {"ref": "NOTE-12", "body": "mine"}
    assert error["stored"] == {"ref": "NOTE-12", "body": "theirs"}


def test_the_api_code_is_carried_not_translated() -> None:
    """ADR 0005: branch on the stable ``code`` string. Rewriting it here would break that promise —
    and the exit table does not need it rewritten, because a refusal is keyed on its status."""
    assert error_payload(NOT_FOUND)[ERROR_MARKER][CODE_KEY] == "note_not_found"


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (TransportError("nope"), "unreachable"),
        (UsageError("nope"), "usage"),
        (UnknownFormat("nope"), "usage"),
        (KayaError("nope"), "runtime"),
    ],
)
def test_a_client_side_failure_names_its_meaning(failure: KayaError, code: str) -> None:
    """The raise site picked a class; the class *is* the meaning. Nobody chose a number."""
    assert error_payload(failure)[ERROR_MARKER][CODE_KEY] == code


def test_a_plain_exception_degrades_to_runtime() -> None:
    """Nothing should reach here that is not a ``KayaError``. Something will, one day."""
    error = error_payload(RuntimeError("the disk is on fire"))[ERROR_MARKER]

    assert error[CODE_KEY] == "runtime"
    assert error[MESSAGE_KEY] == "the disk is on fire"


# ------------------------------------------------------------------ the arg slot

def test_arg_is_filled_from_the_refusals_own_scalar() -> None:
    """``ref`` on a bad identifier — the thing the refusal is *about*, in contract 3's slot."""
    assert error_payload(INVALID_REF)[ERROR_MARKER][ARG_KEY] == "#NOTE-12"


def test_arg_is_empty_when_the_extras_are_objects() -> None:
    """Two whole notes do not fit in a tab-separated column, and they are still there in full."""
    assert error_payload(CONFLICT)[ERROR_MARKER][ARG_KEY] == ""


def test_an_explicit_arg_wins_over_a_derived_one() -> None:
    """A raise site that names its argument is not overruled by a heuristic reading its extras."""
    assert error_payload(UsageError("bad flag", arg="--nope"))[ERROR_MARKER][ARG_KEY] == "--nope"


# --------------------------------------------------------------------- the row

def test_the_error_row_is_pinned_byte_for_byte() -> None:
    """ADR 0005 §contract 3's exact spelling, tabs and all. The trailing tab is an empty ``arg``."""
    assert render_error(NOT_FOUND) == "error\tnote_not_found\tno such note\t"


def test_the_error_row_carries_its_arg_in_the_fourth_field() -> None:
    assert render_error(INVALID_REF) == (
        "error\tinvalid_note_ref\t"
        "not a note reference: '#NOTE-12'. Use NOTE-12, note-12 or 12.\t#NOTE-12"
    )


@pytest.mark.parametrize("failure", [NOT_FOUND, INVALID_REF, CONFLICT, TransportError("no")])
def test_the_row_always_has_exactly_four_fields(failure: BaseException) -> None:
    """Fixed arity is the row's spelling of "all keys always present".

    ``split("\\t")[3]`` must be a value and never an ``IndexError``, or every consumer counts the
    fields before indexing them — the conditional this contract exists to remove, in positional
    clothing.
    """
    rendered = render_error(failure)
    assert isinstance(rendered, str)

    fields = rendered.split(ROW_SEPARATOR)
    assert len(fields) == 4
    assert fields[0] == ERROR_MARKER


def test_the_row_is_one_line_even_when_the_message_is_not() -> None:
    """ADR 0009's `409` message contains a newline. A raw one would turn one row into two, and the
    consumer would read the remainder as a second, malformed record."""
    rendered = render_error(CONFLICT)
    assert isinstance(rendered, str)

    assert "\n" not in rendered
    assert "you read it. Nothing was written." in rendered


def test_the_unmangled_message_is_one_format_away() -> None:
    """Collapsing is a property of the *row*, not of the error. Nothing is lost, only reshaped."""
    error = render_error(CONFLICT, fmt=AdapterFormat.DATA)
    assert isinstance(error, dict)

    assert "\n" in error[ERROR_MARKER][MESSAGE_KEY]


# --------------------------------------------------------------- the structured object

def test_json_parses_back_to_the_same_object_as_data() -> None:
    """One builder behind both, so the string and structured forms cannot drift (ADR 0005 §1)."""
    for failure in (NOT_FOUND, INVALID_REF, CONFLICT):
        encoded = render_error(failure, fmt=Format.JSON)
        assert isinstance(encoded, str)
        assert json.loads(encoded) == render_error(failure, fmt=AdapterFormat.DATA)


def test_the_structured_object_keeps_the_api_envelope() -> None:
    """``{"error": {…}}`` — the same shape `app/api/errors.py` puts on the wire, so there is one
    error shape to learn across HTTP, the CLI and MCP rather than two."""
    rendered = render_error(NOT_FOUND, fmt=AdapterFormat.DATA)

    assert set(rendered) == {ERROR_MARKER}  # type: ignore[arg-type]


def test_the_structured_object_is_a_copy() -> None:
    """A caller that mutates what it was handed must not reach into ``ApiError.payload``."""
    rendered = render_error(CONFLICT, fmt=AdapterFormat.DATA)
    assert isinstance(rendered, dict)

    rendered[ERROR_MARKER][CODE_KEY] = "tampered"
    assert CONFLICT.payload["error"]["code"] == "note_conflict"


def test_json_is_compact_for_errors_too() -> None:
    """The same 16%-of-the-payload argument as the success path. An error is an output."""
    encoded = render_error(CONFLICT, fmt=Format.JSON)
    assert isinstance(encoded, str)

    assert '", "' not in encoded
    assert "\n" not in encoded


# -------------------------------------------------------------- the format vocabulary

def test_errors_render_in_every_format_successes_do() -> None:
    """The tripwire that caught KAN-541's ``toon``, and will catch the next format too.

    A format that rendered a note list but not a `404` would fail exactly when the user most needs
    output, and it would fail as an ``UnknownFormat`` raised from inside an error handler — which
    reads as a client bug rather than as a missing encoder.
    """
    assert set(_ERROR_SERIALIZERS) == set(_SERIALIZERS)


@pytest.mark.parametrize("fmt", ["yaml", "HUMAN", "TOON", "", "csv"])
def test_an_unknown_format_fails_the_same_way_on_the_error_path(fmt: str) -> None:
    with pytest.raises(UnknownFormat) as raised:
        render_error(NOT_FOUND, fmt=fmt)
    assert "human, json, toon" in str(raised.value)


def test_the_error_paths_unknown_format_message_hides_the_adapter_format() -> None:
    """Same reason as the success path: a suggestion in an error message is a contract too."""
    with pytest.raises(UnknownFormat) as raised:
        render_error(NOT_FOUND, fmt="hunan")
    assert "data" not in str(raised.value)


def test_serialize_error_refuses_a_bare_detail() -> None:
    """The mirror of ``serialize``'s refusal of an unshaped payload: one builder, or none."""
    from kaya_client import serialize_error

    with pytest.raises(TypeError, match="error_payload"):
        serialize_error({"code": "usage", "message": "no"}, "human")


# ------------------------------------------------------------------ no credential

BASE_URL = "https://kaya.example"
TOKEN = "kanban_pat_notarealtokenatall"


@pytest.mark.parametrize(
    "handler",
    [
        lambda request: httpx.Response(401, json={"error": {"code": "invalid_token", "m": 1}}),
        lambda request: httpx.Response(502, text="<html>bad gateway</html>"),
    ],
)
def test_no_rendered_error_contains_any_fragment_of_the_bearer(handler: object) -> None:
    """The rule `errors.py` states, enforced where it is easiest to break.

    `test_client.py` already asserts this of the exception *message*. This asserts it of the thing
    that is actually printed, in every format, because an error row goes to **stdout** — the
    cheapest way there is to give away the one property ADR 0002 buys with everything it costs. The
    assertion is over every contiguous fragment, because a truncated token is still a token
    (Q41/Q42).
    """
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    client = KayaClient(BASE_URL, TOKEN, client=httpx.Client(transport=transport))
    with client, pytest.raises(KayaError) as raised:
        client.list_notes()

    rendered = " ".join(
        json.dumps(render_error(raised.value, fmt=fmt), ensure_ascii=False)
        for fmt in ("human", "json", "toon", "data")
    )
    fragments = {
        TOKEN[start:stop]
        for start in range(len(TOKEN))
        for stop in range(start + 6, len(TOKEN) + 1)
    }
    assert not [fragment for fragment in fragments if fragment in rendered]
