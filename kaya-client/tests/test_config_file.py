"""PLAN §Config's file tier, the merge that keeps a hand-set key alive, and the redaction (KAN-551).

Two of these assertions are the card's named guards and both are mutation-tested:

- **A config write preserves keys ``config set`` has no flag for.** Tested with a key this package
  has never heard of as well as with ``max_text_chars``, because the rule is about unknown keys
  generally and a test using only the documented one would pass against a writer that had
  special-cased the key somebody remembered.
- **Nothing that renders a bearer may contain a fragment of one.** Checked against every contiguous
  fragment of **four** characters or more, in every format, the way
  `backend/tests/unit/test_log_redaction.py` does — a truncated token is still a token (Q41/Q42).
  Four rather than that file's eight because the shape being refused here is *specific*: the
  sibling tool prints ``set (…c_DE)``, and a window of eight would let exactly that through. It was
  a mutation that found this — a six-character window passed against a deliberate four-character
  leak — so the number is measured rather than chosen.

Every test here runs against a ``tmp_path`` config home, installed by the autouse fixture in
``conftest.py``. Without it these would write to whoever ran them.
"""

import json
from pathlib import Path

import pytest

from kaya_client import (
    DEFAULT_TEXT_LIMIT,
    Format,
    KayaError,
    MissingCredential,
    UsageError,
    api_url,
    config_path,
    max_text_chars,
    path_payload,
    read_settings_file,
    render,
    settings_payload,
    write_settings,
)
from kaya_client.config import (
    API_URL_ENV,
    CONFIG_HOME_ENV,
    DEFAULT_API_URL,
    DEFAULT_SOURCE,
    ENVIRONMENT_SOURCE,
    FILE_SOURCE,
    HOME_ENV,
    MAX_TEXT_CHARS_ENV,
    TOKEN_ENV,
    TOKEN_SET,
    TOKEN_UNSET,
    UNSET_SOURCE,
    file_key,
    token,
)

TOKEN = "kanban_pat_notarealtokenatall"
"""Pre-rebrand-shaped on purpose: ADR 0002 gives kaya no token format, and pandan still accepts
these, so the fixtures must not imply one exists."""

SECRET = "kanban_pat_FAKE0000aaaaBBBBccccDDDDeeee"
"""The token the **redaction** assertions use. Its tail is deliberate on two axes.

``FAKE…`` is `.gitleaks.toml`'s documented-placeholder shape, the same one
`backend/tests/unit/test_log_redaction.py` uses, so a fixture credential does not redden the secret
scan. And it carries **no English words**, for a reason the mutation found:
``notarealtokenatall`` contains the word ``token``, which is also a *key name* in this payload, so
any window narrow enough to catch a four-character leak would collide with the output's own
vocabulary. A fake credential that reads like prose makes a
redaction guard weaker exactly where it needs to be strongest."""


@pytest.fixture
def home(tmp_path: Path) -> dict[str, str]:
    """An environment with a config directory and nothing else set.

    A plain dict rather than ``monkeypatch``: every resolver takes ``env`` explicitly, so a test
    that passes one is exercising the same code path a shell does without touching the process.
    """
    return {CONFIG_HOME_ENV: str(tmp_path / "config")}


def written(env: dict[str, str]) -> dict:
    return json.loads(config_path(env).read_text(encoding="utf-8"))


def put(env: dict[str, str], values: dict) -> Path:
    """Write a config file by hand, the way a user editing it would."""
    path = config_path(env)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values), encoding="utf-8")
    return path


# ------------------------------------------------------------------------------ the path


def test_the_path_is_under_the_xdg_config_home(tmp_path: Path) -> None:
    env = {CONFIG_HOME_ENV: str(tmp_path)}

    assert config_path(env) == tmp_path / "kaya" / "config.json"


def test_home_is_the_fallback(tmp_path: Path) -> None:
    env = {HOME_ENV: str(tmp_path)}

    assert config_path(env) == tmp_path / ".config" / "kaya" / "config.json"


def test_the_xdg_variable_wins_over_home(tmp_path: Path) -> None:
    env = {CONFIG_HOME_ENV: str(tmp_path / "xdg"), HOME_ENV: str(tmp_path / "home")}

    assert config_path(env) == tmp_path / "xdg" / "kaya" / "config.json"


def test_an_environment_with_no_home_at_all_is_a_refusal() -> None:
    """Rather than a guess. A container with no ``HOME`` has no user configuration directory, and
    inventing one would put a credential somewhere nobody asked for."""
    with pytest.raises(KayaError, match=HOME_ENV):
        config_path({})


def test_resolution_still_works_with_no_home() -> None:
    """The refusal above must not take the environment tier down with it: a shell that configures
    everything through variables has no use for a config directory and must not need one."""
    assert api_url({API_URL_ENV: "https://kaya.example"}) == "https://kaya.example"
    assert token({TOKEN_ENV: TOKEN}) == TOKEN


# ------------------------------------------------------------------------- reading it


def test_no_file_is_no_settings_rather_than_an_error(home: dict[str, str]) -> None:
    """Configuring nothing is a supported way to run kaya; the defaults exist for it."""
    assert read_settings_file(home) == {}


def test_the_file_supplies_a_setting_the_environment_does_not(home: dict[str, str]) -> None:
    put(home, {"api_url": "https://filed.example"})

    assert api_url(home) == "https://filed.example"


def test_the_environment_wins_over_the_file(home: dict[str, str]) -> None:
    put(home, {"api_url": "https://filed.example"})
    env = {**home, API_URL_ENV: "https://exported.example"}

    assert api_url(env) == "https://exported.example"


def test_each_key_is_resolved_independently(home: dict[str, str]) -> None:
    """PLAN §Config's word. A shell that exports only the token must not thereby discard the
    ``api_url`` in the file — the tiers are consulted per key, not per source, and the tempting
    "whichever source is more complete wins" would silently change which deployment is addressed."""
    put(home, {"api_url": "https://filed.example", "token": "filed-token"})
    env = {**home, TOKEN_ENV: TOKEN}

    assert api_url(env) == "https://filed.example"
    assert token(env) == TOKEN


def test_a_token_in_the_file_is_a_credential(home: dict[str, str]) -> None:
    put(home, {"token": TOKEN})

    assert token(home) == TOKEN


def test_a_blank_value_in_the_file_does_not_mask_the_default(home: dict[str, str]) -> None:
    """The same reading the environment tier already takes: whitespace-only is a misconfiguration,
    not a value, and a blank bearer would reach the API and come back a `401`."""
    put(home, {"api_url": "   ", "token": ""})

    assert api_url(home) == DEFAULT_API_URL
    with pytest.raises(MissingCredential):
        token(home)


def test_the_text_limit_comes_from_the_file(home: dict[str, str]) -> None:
    put(home, {"max_text_chars": 120})

    assert max_text_chars(home) == 120


def test_a_json_number_and_a_json_string_resolve_alike(home: dict[str, str]) -> None:
    """JSON has numbers, so a hand-edited file may hold either. One parser, not two type-dependent
    paths that could disagree about what ``0`` means."""
    put(home, {"max_text_chars": "0"})
    assert max_text_chars(home) == 0

    put(home, {"max_text_chars": 0})
    assert max_text_chars(home) == 0


def test_a_bad_text_limit_in_the_file_names_the_file(home: dict[str, str]) -> None:
    """Two tiers can each hold a value, so "which of my configurations is wrong?" is the caller's
    next question and the message has to answer it."""
    put(home, {"max_text_chars": "lots"})

    with pytest.raises(UsageError, match="config file") as raised:
        max_text_chars(home)
    assert raised.value.arg == MAX_TEXT_CHARS_ENV


def test_a_malformed_file_is_a_refusal_not_a_shrug(home: dict[str, str]) -> None:
    """Ignoring it would let `note list` quietly address ``localhost`` while the file named
    production — and would let ``config set`` merge onto ``{}`` and overwrite the only surviving
    copy of what the user meant."""
    path = config_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"api_url": ', encoding="utf-8")

    with pytest.raises(KayaError, match="not valid JSON"):
        read_settings_file(home)
    with pytest.raises(KayaError):
        api_url(home)


def test_a_malformed_file_is_not_overwritten(home: dict[str, str]) -> None:
    """The refusal has to come *before* the write, or the guard above buys nothing."""
    path = config_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json at all", encoding="utf-8")

    with pytest.raises(KayaError):
        write_settings({API_URL_ENV: "https://kaya.example"}, home)
    assert path.read_text(encoding="utf-8") == "not json at all"


def test_a_file_holding_something_other_than_an_object_is_refused(home: dict[str, str]) -> None:
    put(home, ["api_url"])  # type: ignore[arg-type]

    with pytest.raises(KayaError, match="object of settings"):
        read_settings_file(home)


def test_no_diagnostic_about_the_file_contains_its_contents(home: dict[str, str]) -> None:
    """A config file holds a PAT, so the tempting "expected ``,`` near …" excerpt is a credential in
    an error message. The parser's own exception is dropped rather than chained, for the same
    reason."""
    path = config_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'{{"token": "{SECRET}", ', encoding="utf-8")

    with pytest.raises(KayaError) as raised:
        read_settings_file(home)
    reported = f"{raised.value} {raised.value.arg} {raised.value.__cause__}"

    assert not _fragments_in(SECRET, reported)


# ------------------------------------------------------------------------- writing it


def test_a_write_creates_the_file_and_its_directory(home: dict[str, str]) -> None:
    write_settings({API_URL_ENV: "https://kaya.example"}, home)

    assert written(home) == {"api_url": "https://kaya.example"}


def test_a_write_preserves_a_hand_set_key_it_has_no_flag_for(home: dict[str, str]) -> None:
    """**The card's named trap.** ``config set`` has no ``--max-text-chars``, and a writer that
    serialized only what it was passed would delete a value the user tuned by hand — silently, on
    an unrelated command, with the evidence gone."""
    put(home, {"max_text_chars": 120})

    write_settings({API_URL_ENV: "https://kaya.example"}, home)

    assert written(home) == {"max_text_chars": 120, "api_url": "https://kaya.example"}
    assert max_text_chars(home) == 120


def test_a_write_preserves_a_key_this_package_has_never_heard_of(home: dict[str, str]) -> None:
    """The rule is about unknown keys generally, and this is the half that cannot pass by accident.

    A writer that special-cased ``max_text_chars`` — the one key somebody would remember — would
    satisfy the test above and delete this one. Keys arrive from a later version of kaya, from a
    typo, and from a user leaving themselves a note; none of them is this writer's to discard.
    """
    put(home, {"future_setting": "keep me", "a_note_to_self": {"nested": [1, 2]}})

    write_settings({API_URL_ENV: "https://kaya.example"}, home)

    assert written(home) == {
        "future_setting": "keep me",
        "a_note_to_self": {"nested": [1, 2]},
        "api_url": "https://kaya.example",
    }


def test_a_write_replaces_a_key_it_does_name(home: dict[str, str]) -> None:
    """Preservation is not stickiness: the whole point of ``set`` is to change something."""
    put(home, {"api_url": "https://old.example"})

    write_settings({API_URL_ENV: "https://new.example"}, home)

    assert written(home)["api_url"] == "https://new.example"


def test_a_key_the_caller_did_not_name_is_not_written(home: dict[str, str]) -> None:
    """``None`` means "did not ask" and must not reach the file as a null."""
    write_settings({API_URL_ENV: "https://kaya.example", TOKEN_ENV: None}, home)

    assert "token" not in written(home)


def test_a_write_naming_nothing_is_a_usage_error(home: dict[str, str]) -> None:
    with pytest.raises(UsageError, match="nothing to set"):
        write_settings({API_URL_ENV: None, TOKEN_ENV: None}, home)


def test_a_blank_value_is_refused_rather_than_stored(home: dict[str, str]) -> None:
    """A stored ``""`` is invisible in ``config show`` (blank is treated as unset at every tier), so
    accepting one would write a value that nothing reads and nothing reports."""
    with pytest.raises(UsageError, match="empty value"):
        write_settings({API_URL_ENV: "   "}, home)


def test_the_file_is_private(home: dict[str, str]) -> None:
    """It holds a PAT. ``0o600`` is set before the rename, so there is no window in which a
    world-readable file contains one."""
    write_settings({TOKEN_ENV: TOKEN}, home)

    assert config_path(home).stat().st_mode & 0o077 == 0


def test_a_write_leaves_no_temporary_file_behind(home: dict[str, str]) -> None:
    write_settings({API_URL_ENV: "https://kaya.example"}, home)
    path = config_path(home)

    assert [entry.name for entry in path.parent.iterdir()] == [path.name]


def test_the_environment_name_is_translated_to_the_file_key() -> None:
    """Mechanical, so a fourth setting cannot be resolved from the environment and invisible in the
    file because somebody forgot a lookup row."""
    assert file_key(API_URL_ENV) == "api_url"
    assert file_key(TOKEN_ENV) == "token"
    assert file_key(MAX_TEXT_CHARS_ENV) == "max_text_chars"


# --------------------------------------------------------------------- what show says


def rows(payload) -> dict[str, tuple[str, str]]:
    return {r["key"]: (r["value"], r["source"]) for r in payload.records}


def test_show_reports_the_defaults_when_nothing_is_configured(home: dict[str, str]) -> None:
    reported = rows(settings_payload(home))

    assert reported["api_url"] == (DEFAULT_API_URL, DEFAULT_SOURCE)
    assert reported["token"] == (TOKEN_UNSET, UNSET_SOURCE)
    assert reported["max_text_chars"] == (str(DEFAULT_TEXT_LIMIT), DEFAULT_SOURCE)


def test_show_names_the_tier_each_value_came_from(home: dict[str, str]) -> None:
    """The column that answers "I edited the file and nothing changed" without anybody reading a
    document about tier order."""
    put(home, {"api_url": "https://filed.example", "max_text_chars": 120})
    env = {**home, TOKEN_ENV: TOKEN}
    reported = rows(settings_payload(env))

    assert reported["api_url"] == ("https://filed.example", FILE_SOURCE)
    assert reported["token"] == (TOKEN_SET, ENVIRONMENT_SOURCE)
    assert reported["max_text_chars"] == ("120", FILE_SOURCE)


def test_show_reports_the_effective_text_limit(home: dict[str, str]) -> None:
    """SLICES §V2b, and the acceptance criterion KAN-547 could not meet without this file tier.
    ``0`` is a value — it disables truncation — so it must survive a falsy check."""
    put(home, {"max_text_chars": 250})
    assert rows(settings_payload(home))["max_text_chars"][0] == "250"

    env = {**home, MAX_TEXT_CHARS_ENV: "0"}
    assert rows(settings_payload(env))["max_text_chars"] == ("0", ENVIRONMENT_SOURCE)
    assert max_text_chars(env) == 0


def test_show_reports_the_same_number_the_truncator_uses(home: dict[str, str]) -> None:
    """Not a second reading of the same variables. A ``config show`` that computed the limit for
    itself could report a value ``render`` does not use, which is the one thing this verb must not
    do."""
    put(home, {"max_text_chars": 37})

    assert rows(settings_payload(home))["max_text_chars"][0] == str(max_text_chars(home))


def test_a_setting_show_cannot_resolve_is_a_refusal(home: dict[str, str]) -> None:
    """`config show` is the diagnostic verb, so it reports a broken setting *as broken* — naming
    the variable and the tier — rather than printing the unparsed string as if it worked."""
    put(home, {"max_text_chars": "lots"})

    with pytest.raises(UsageError, match=MAX_TEXT_CHARS_ENV):
        settings_payload(home)


# ------------------------------------------------------------------------ the redaction


def _fragments_in(secret: str, text: str, least: int = 4) -> list[str]:
    """Every contiguous fragment of ``secret`` of ``least`` characters or more that appears.

    The same technique as `backend/tests/unit/test_log_redaction.py`, with a narrower window. That
    file walks eight-character windows over a token in a *log line*, where the leak it fears is a
    whole or badly-truncated credential and eight is short enough to catch one without colliding
    with ordinary log text. Here the leak has a known shape and it is four characters long — the
    sibling tool's ``set (…c_DE)`` — so an eight-character window would pass against the exact
    thing being refused. It is safe to go this narrow only because ``SECRET`` is high-entropy; see
    its docstring.
    """
    fragments = {
        secret[start:stop]
        for start in range(len(secret))
        for stop in range(start + least, len(secret) + 1)
    }
    return sorted(fragment for fragment in fragments if fragment in text)


def test_the_fragment_check_can_fail() -> None:
    """The guard's own guard. An ``x in y`` assertion over an empty haystack passes vacuously, and
    a redaction test that could not fail is the blind guard PLAN §Testing warns about.

    The middle case is the one this window width exists for: **the sibling tool's four-character
    hint**. A six-character window passed against it, which a mutation demonstrated, and that is
    why this test names the shape rather than only "some fragment".
    """
    assert _fragments_in(SECRET, f"token is {SECRET[4:14]}")
    assert _fragments_in(SECRET, f"set (…{SECRET[-4:]})"), "pandan's own hint went unnoticed"
    assert not _fragments_in(SECRET, "token  set  environment  api_url  max_text_chars")


@pytest.mark.parametrize("fmt", [Format.HUMAN, Format.JSON, Format.TOON])
def test_no_rendering_of_the_settings_carries_a_fragment_of_the_token(
    home: dict[str, str], fmt: str
) -> None:
    """Every format, because the redaction is in the payload and not in a formatter — which is what
    makes it hold for `data` and for whatever V6 renders as well."""
    put(home, {"token": SECRET})
    env = {**home, TOKEN_ENV: SECRET}

    rendered = str(render(settings_payload(env), fmt=fmt))

    assert not _fragments_in(SECRET, rendered)
    assert TOKEN_SET in rendered


def test_the_token_row_says_only_whether_there_is_one(home: dict[str, str]) -> None:
    """Not a prefix, not a suffix, not a length. A length narrows a search, and a fragment is a
    credential; "is it *the right* token?" is answered by making a request, not by squinting."""
    put(home, {"token": SECRET})
    value, _ = rows(settings_payload(home))["token"]

    assert value == TOKEN_SET
    assert not _fragments_in(SECRET, value)
    assert str(len(SECRET)) not in value


def test_the_write_verb_returns_the_effective_settings_and_not_the_file(
    home: dict[str, str],
) -> None:
    """An exported variable outranks what was just written, and the row says so. A verb that echoed
    the file back would confirm a write that changes nothing about the next command."""
    env = {**home, API_URL_ENV: "https://exported.example"}

    reported = rows(write_settings({API_URL_ENV: "https://filed.example"}, env))

    assert written(env)["api_url"] == "https://filed.example"
    assert reported["api_url"] == ("https://exported.example", ENVIRONMENT_SOURCE)


# ---------------------------------------------------------------------- config path


def test_the_path_payload_reports_a_file_that_does_not_exist_yet(home: dict[str, str]) -> None:
    """It prints the path it *would* use rather than refusing. The moment the verb matters most is
    before the file exists — ``mkdir -p $(dirname $(kaya config path))`` has to work on a fresh
    machine — so a refusal would make the one useful case the one that fails."""
    payload = path_payload(home)

    assert payload.record == {"path": str(config_path(home)), "exists": False}


def test_the_path_payload_says_so_once_the_file_is_there(home: dict[str, str]) -> None:
    """``exists`` keeps it honest, so a script tells "here is where it goes" from "here is where it
    is" without stat-ing a path parsed out of an error message."""
    write_settings({API_URL_ENV: "https://kaya.example"}, home)

    assert path_payload(home).record["exists"] is True
