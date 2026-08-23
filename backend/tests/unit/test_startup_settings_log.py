"""KAN-968: `make up` can only put two environment variables in front of the app container
(`docker-compose.yml`'s `app` service — `DATABASE_URL`, `KAYA_PANDAN_URL`), so every other
``Settings`` field silently takes its default there however a caller spells the knob in their
shell, with nothing warning that it never arrived. This does not fix that — a value that never
reached the process cannot be named by inspecting the process — but it makes every value that
*did* take effect, in any run, visible in the startup log rather than requiring `printenv` inside
the container to discover it.

Two things have to be true about the mechanism, and this file is split across the two halves.

``app.config.effective_overrides`` is the pure half: which fields differ from their own declared
default, with ``database_url`` refused **structurally** because its default and every real value
embed a plaintext database password as URL userinfo — a field that could carry a credential is
excluded by name, not discovered by a pattern that could rot. ``Settings.model_construct`` builds
these without touching the process environment or the cached singleton, so the pure tests below
are hermetic against whatever the ambient shell happens to export.

``app.observability._log_effective_settings`` is the logging half, and it is deliberately *not*
trusted to be its own guarantee. Even though there is no token/bearer field on ``Settings`` to
leak — kaya holds no long-lived credential of its own; see ``app/config.py``'s module docstring
and ADR 0002 — the value still goes through ``get_logger`` → ``JsonFormatter`` → ``scrub``, the
same backstop ``tests/unit/test_log_redaction.py`` guards, before it reaches stdout. So this file's
defense-in-depth test puts a credential-shaped string into a field the allow-list does *not*
exclude (``pandan_url``, which is real configuration and not a secret on its own — it appears
verbatim in a `503` body) and proves the backstop, not the allow-list, is what stops it.
"""

import json

import pytest

from app.config import Settings, effective_overrides, get_settings
from app.observability import _log_effective_settings, configure_logging

TOKEN = "pandan_pat_FAKE0000aaaaBBBBccccDDDDeeeeFFFFgggg111"
"""Shaped like a real pandan PAT and never was one — same fixture as `test_log_redaction.py`."""


def captured_lines(capsys: pytest.CaptureFixture[str]) -> list[dict]:
    raw = capsys.readouterr().out
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def leaked_fragments(output: str, secret: str = TOKEN, width: int = 8) -> list[str]:
    """Every contiguous ``width``-character run of ``secret``'s random tail found in ``output``.

    Windows wholly inside the public ``pandan_pat_`` prefix are excluded — that prefix is
    documented in three ADRs and in ``.gitleaks.toml``, so a match on it alone is not a leak. Same
    technique as ``test_log_redaction.py``'s ``leaked_fragments``, kept local rather than imported
    across test modules.
    """
    windows = {
        secret[i : i + width]
        for i in range(len(secret) - width + 1)
        if i + width > len("pandan_pat_")
    }
    return sorted(window for window in windows if window in output)


# ------------------------------------------------------------- the pure half: effective_overrides


def test_every_field_at_its_default_reports_no_overrides() -> None:
    """The positive control: an unmodified ``Settings`` names nothing.

    Built with ``model_construct`` rather than ``Settings()``, so this is a claim about the
    function and not about whatever the test runner's own shell happens to export.
    """
    assert effective_overrides(Settings.model_construct()) == {}


def test_a_changed_field_is_named_with_its_new_value() -> None:
    settings = Settings.model_construct(card_resolution_connect_timeout_seconds=1.0)

    assert effective_overrides(settings) == {"card_resolution_connect_timeout_seconds": 1.0}


def test_several_changed_fields_are_all_named() -> None:
    settings = Settings.model_construct(
        card_resolution_connect_timeout_seconds=1.0,
        pandan_read_timeout_seconds=99.0,
        log_level="DEBUG",
    )

    assert effective_overrides(settings) == {
        "card_resolution_connect_timeout_seconds": 1.0,
        "pandan_read_timeout_seconds": 99.0,
        "log_level": "DEBUG",
    }


def test_database_url_is_never_named_even_though_it_differs_from_default() -> None:
    """The one field excluded on purpose: its value embeds a password, not just a hostname."""
    settings = Settings.model_construct(database_url="postgresql+psycopg://kaya:kaya@db:5432/kaya")

    assert "database_url" not in effective_overrides(settings)


def test_the_database_url_exclusion_is_not_hiding_behind_an_empty_diff() -> None:
    """Proves the exclusion test above can fail: the changed value really does differ from
    ``DEFAULT_DATABASE_URL`` (``localhost`` vs. ``db``), so its absence above is the allow-list
    working rather than the two URLs happening to be equal."""
    settings = Settings.model_construct(database_url="postgresql+psycopg://kaya:kaya@db:5432/kaya")

    assert settings.database_url != Settings.model_fields["database_url"].default


# ------------------------------------------------------------- the logging half: the startup line


def test_a_non_default_numeric_setting_is_reported_at_startup(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The behavioural half of KAN-968's fix: a value that *did* reach the process is visible in
    the log without shelling into a container to run ``printenv``."""
    configure_logging("INFO")
    settings = get_settings()
    original = settings.card_resolution_connect_timeout_seconds
    try:
        settings.card_resolution_connect_timeout_seconds = 1.0
        _log_effective_settings()

        line = captured_lines(capsys)[-1]
        assert line["settings_overrides"]["card_resolution_connect_timeout_seconds"] == 1.0
    finally:
        settings.card_resolution_connect_timeout_seconds = original


def test_settings_left_at_their_default_are_not_claimed_as_overrides(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The other half of the same line: a field nobody touched must not appear as though it had
    been, which would make the line as misleading as the silence it replaces."""
    configure_logging("INFO")
    settings = get_settings()
    original = settings.card_resolution_connect_timeout_seconds
    try:
        settings.card_resolution_connect_timeout_seconds = 1.0
        _log_effective_settings()

        line = captured_lines(capsys)[-1]
        assert "pandan_read_timeout_seconds" not in line["settings_overrides"]
    finally:
        settings.card_resolution_connect_timeout_seconds = original


def test_database_url_never_reaches_this_log_line_even_when_changed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = get_settings()
    original = settings.database_url
    try:
        settings.database_url = "postgresql+psycopg://kaya:kaya@db:5432/kaya"
        configure_logging("INFO")
        _log_effective_settings()

        raw = capsys.readouterr().out
        line = json.loads(raw)
        assert "database_url" not in line["settings_overrides"]
        assert "kaya:kaya@" not in raw, "a database credential reached the startup log"
    finally:
        settings.database_url = original


def test_a_credential_shaped_value_in_a_plain_field_is_still_scrubbed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Defense in depth (KAN-968's brief, explicitly): there is no token/bearer field on
    ``Settings`` today for a credential to occupy, but this line does not rely on that being true
    forever. ``pandan_url`` is real configuration and is **not** excluded by
    ``_EXCLUDED_FROM_STARTUP_LOG`` — it is safe to print on its own, which is exactly why it is the
    right field to prove the *backstop* on: if a credential-shaped string ever ends up here, the
    same ``scrub`` that guards every other log line in the app is what has to catch it, not this
    module's allow-list.
    """
    configure_logging("INFO")
    settings = get_settings()
    original = settings.pandan_url
    try:
        settings.pandan_url = f"https://pandan.example/?leaked=Bearer {TOKEN}"
        _log_effective_settings()

        raw = capsys.readouterr().out
        assert leaked_fragments(raw) == [], (
            f"a credential-shaped Settings value reached stdout unredacted: {leaked_fragments(raw)}"
        )
        assert "[redacted]" in raw
    finally:
        settings.pandan_url = original
