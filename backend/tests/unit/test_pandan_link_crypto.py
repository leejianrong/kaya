"""`encrypt_token`/`decrypt_token` (ADR 0012's amendment, KAN-1741) — no database, no FastAPI,
pure functions over strings, the same reason `test_pat_hashing.py`-style modules exist for
`app/identity/pat.py`'s own hashing.
"""

from app.identity.pandan_link import decrypt_token, encrypt_token

RAW = "pandan_pat_FAKEa-real-looking-secret-nobody-should-see"


def test_round_trips_with_the_same_secret() -> None:
    encrypted = encrypt_token(RAW, "one-secret")

    assert decrypt_token(encrypted, "one-secret") == RAW


def test_never_stores_the_plaintext() -> None:
    encrypted = encrypt_token(RAW, "one-secret")

    assert RAW not in encrypted


def test_a_different_secret_cannot_decrypt_it() -> None:
    """`KAYA_AUTH_SECRET` rotating is exactly this: the stored ciphertext survives, but nothing can
    read it back with the new value."""
    encrypted = encrypt_token(RAW, "one-secret")

    assert decrypt_token(encrypted, "a-different-secret") is None


def test_a_corrupted_ciphertext_is_none_not_an_exception() -> None:
    encrypted = encrypt_token(RAW, "one-secret")
    corrupted = encrypted[:-4] + "abcd"

    assert decrypt_token(corrupted, "one-secret") is None


def test_two_encryptions_of_the_same_token_are_not_identical_bytes() -> None:
    """Fernet includes a random IV and a timestamp in every token it mints — this is not a
    behavioural requirement kaya relies on, but a corrupted implementation that hashed instead of
    encrypted (or encrypted deterministically) would fail this and every property test above it in
    a way worth pinning explicitly."""
    first = encrypt_token(RAW, "one-secret")
    second = encrypt_token(RAW, "one-secret")

    assert first != second
    assert decrypt_token(first, "one-secret") == decrypt_token(second, "one-secret") == RAW
