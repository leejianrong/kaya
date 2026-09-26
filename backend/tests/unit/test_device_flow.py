"""`device_flow.py`'s pure primitives — no database, no FastAPI (ADR 0013, KAN-1743)."""

import re

from app.identity.device_flow import (
    DEVICE_POLL_INTERVAL_SECONDS,
    _PollThrottle,
    generate_device_code,
    generate_user_code,
)

_GROUP = "[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{4}"
USER_CODE_PATTERN = re.compile(f"^{_GROUP}-{_GROUP}$")


def test_device_code_is_url_safe_and_high_entropy() -> None:
    code = generate_device_code()

    assert len(code) >= 32
    assert re.fullmatch(r"[A-Za-z0-9_-]+", code)


def test_two_device_codes_are_never_the_same() -> None:
    assert generate_device_code() != generate_device_code()


def test_user_code_matches_the_grouped_crockford_ish_shape() -> None:
    code = generate_user_code()

    assert USER_CODE_PATTERN.fullmatch(code), code


def test_user_code_never_contains_the_visually_ambiguous_glyphs() -> None:
    """0/O/1/I/L are excluded — the whole reason for the restricted alphabet rather than a plain
    base32/hex code."""
    excluded = set("0O1IL")
    for _ in range(200):
        code = generate_user_code()
        assert not (set(code) & excluded), code


def test_poll_throttle_allows_the_first_poll() -> None:
    throttle = _PollThrottle(clock=lambda: 100.0)

    assert throttle.too_soon("a-hash") is False


def test_poll_throttle_says_slow_down_before_the_interval_elapses() -> None:
    clock_value = [100.0]
    throttle = _PollThrottle(clock=lambda: clock_value[0])

    assert throttle.too_soon("a-hash") is False
    clock_value[0] += DEVICE_POLL_INTERVAL_SECONDS - 1
    assert throttle.too_soon("a-hash") is True


def test_poll_throttle_allows_a_poll_once_the_interval_has_elapsed() -> None:
    clock_value = [100.0]
    throttle = _PollThrottle(clock=lambda: clock_value[0])

    assert throttle.too_soon("a-hash") is False
    clock_value[0] += DEVICE_POLL_INTERVAL_SECONDS
    assert throttle.too_soon("a-hash") is False


def test_poll_throttle_tracks_each_device_code_hash_independently() -> None:
    throttle = _PollThrottle(clock=lambda: 100.0)

    assert throttle.too_soon("hash-a") is False
    assert throttle.too_soon("hash-b") is False, "a fresh code must not inherit another's cadence"


def test_forgetting_a_poll_state_drops_its_cadence_history() -> None:
    """The positive control: without `forget`, polling twice at the same instant is `slow_down` on
    the second call. `forget` in between is what makes the third call fresh again."""
    throttle = _PollThrottle(clock=lambda: 100.0)

    throttle.too_soon("a-hash")
    assert throttle.too_soon("a-hash") is True, "the positive control — no forget, still too soon"

    throttle.forget("a-hash")
    assert throttle.too_soon("a-hash") is False, "forgetting drops the cadence entry entirely"


def test_forgetting_an_unknown_hash_does_not_raise() -> None:
    _PollThrottle().forget("never-seen")
