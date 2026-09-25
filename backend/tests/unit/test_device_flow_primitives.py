"""`app/identity/device_flow.py`'s pure functions (ADR 0013, KAN-1743) — no database, no FastAPI.
"""

import re

from app.identity import device_flow

_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
USER_CODE_PATTERN = re.compile(rf"^[{_ALPHABET}]{{4}}-[{_ALPHABET}]{{4}}$")


def test_generate_device_code_is_long_and_url_safe() -> None:
    code = device_flow.generate_device_code()

    assert len(code) >= 32
    assert all(c.isalnum() or c in "-_" for c in code)


def test_two_device_codes_are_never_the_same() -> None:
    assert device_flow.generate_device_code() != device_flow.generate_device_code()


def test_generate_user_code_matches_the_documented_shape() -> None:
    code = device_flow.generate_user_code()

    assert USER_CODE_PATTERN.match(code), code


def test_user_code_never_contains_the_ambiguous_glyphs() -> None:
    """0/O/1/I/L are excluded on purpose — see the module docstring."""
    for _ in range(200):
        code = device_flow.generate_user_code()
        assert not set(code) & set("0O1IL")


def test_too_soon_to_poll_is_false_on_the_first_poll() -> None:
    assert device_flow.too_soon_to_poll("a-fresh-hash-nobody-has-polled-yet") is False


def test_too_soon_to_poll_is_true_immediately_after_a_poll() -> None:
    key = "a-hash-polled-twice-in-a-row"
    device_flow.too_soon_to_poll(key)

    assert device_flow.too_soon_to_poll(key) is True


def test_forget_poll_state_clears_the_too_soon_flag() -> None:
    key = "a-hash-about-to-be-forgotten"
    device_flow.too_soon_to_poll(key)

    device_flow.forget_poll_state(key)

    assert device_flow.too_soon_to_poll(key) is False


def test_forgetting_an_unknown_key_does_not_raise() -> None:
    device_flow.forget_poll_state("a-key-that-was-never-polled-at-all")
