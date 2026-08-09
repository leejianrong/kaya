"""`config {set,show,path}` end to end (KAN-551).

Three things this file exists to hold, none of which is visible in `kaya-client`'s own tests:

- **A config verb opens no session.** `config show` is what a person runs to find out they have no
  credential, so a version that needed one would be useless in the one case it is for.
- **A config verb prints through ``render`` like every other verb.** No local printer, no
  ``print()`` in a verb — ADR 0004's boundary in the place it is easiest to excuse breaking.
- **Nothing prints a bearer.** Asserted on the real bytes of stdout, over every fragment of
  **four** characters or more, in every format — four because that is the length of the sibling
  tool's ``set (…c_DE)`` hint, which is the specific shape being refused.

The autouse fixture in ``conftest.py`` points ``XDG_CONFIG_HOME`` and ``HOME`` at a ``tmp_path``.
Without it this file would rewrite the config of whoever ran it.
"""

import json
import os
from pathlib import Path

import pytest
from conftest import TOKEN
from kaya_client import config

from kaya_cli.__main__ import main

SECRET = "kanban_pat_FAKE0000aaaaBBBBccccDDDDeeee"
"""The token the redaction assertions use. ``FAKE…`` is `.gitleaks.toml`'s documented-placeholder
shape, and the tail carries no English words because the window below is narrow enough that a fake
credential containing the word ``token`` would collide with this payload's own key names.
``conftest.TOKEN`` stays the bearer the fake API expects."""


def config_file() -> Path:
    return config.config_path(os.environ)


def stored() -> dict:
    return json.loads(config_file().read_text(encoding="utf-8"))


def put(values: dict) -> Path:
    """A config file written by hand, which is how ``max_text_chars`` gets set at all."""
    path = config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values), encoding="utf-8")
    return path


def shown(capsys) -> dict[str, tuple[str, str]]:
    rows = json.loads(capsys.readouterr().out)["settings"]
    return {row["key"]: (row["value"], row["source"]) for row in rows}


def fragments_in(secret: str, text: str, least: int = 4) -> list[str]:
    """Every contiguous fragment of ``secret`` at least ``least`` characters long that appears.

    A truncated token is still a token (Q41/Q42), so the assertion cannot be about the whole
    string: the shape being refused is the sibling tool's ``set (…c_DE)``, which is four characters
    of a live credential — and a wider window demonstrably lets it through, which is how this
    number was arrived at.
    """
    pieces = {
        secret[start:stop]
        for start in range(len(secret))
        for stop in range(start + least, len(secret) + 1)
    }
    return sorted(piece for piece in pieces if piece in text)


# --------------------------------------------------------------------------- config show


def test_show_works_with_no_credential_and_no_file(capsys) -> None:
    """The case the verb exists for. A `config show` that needed a token to tell you that you have
    no token would be the CLI answering a question with the question."""
    assert main(["config", "show"]) == 0
    out = capsys.readouterr().out.splitlines()

    assert out[:3] == [
        "api_url         http://localhost:8000  default",
        "token           not set                unset",
        "max_text_chars  500                    default",
    ]


def test_show_opens_no_session(answering) -> None:
    """``fake_api`` replaces `verbs.open_client`, so an empty request log is proof that the config
    path never went near one — not merely that it did not send anything."""
    seen = answering(200, {"notes": []})

    assert main(["config", "show"]) == 0
    assert main(["config", "path"]) == 0
    assert seen == []


def test_show_is_structured_over_the_same_seam(capsys) -> None:
    """ADR 0005 §contract 1 is a promise about every verb, and a provisioning script wants this one
    in JSON more than most."""
    assert main(["config", "show", "--json"]) == 0

    assert shown(capsys)["api_url"] == ("http://localhost:8000", "default")


def test_show_names_the_tier_each_value_came_from(capsys, monkeypatch) -> None:
    put({"api_url": "https://filed.example"})
    monkeypatch.setenv(config.TOKEN_ENV, TOKEN)
    main(["config", "show", "--json"])
    reported = shown(capsys)

    assert reported["api_url"] == ("https://filed.example", "file")
    assert reported["token"] == ("set", "environment")


def test_show_reports_the_effective_text_limit(capsys, monkeypatch) -> None:
    """SLICES §V2b's integration line, and KAN-547's acceptance criterion moved to this card
    because half of "effective" was the file tier this one builds."""
    put({"max_text_chars": 250})
    main(["config", "show", "--json"])
    assert shown(capsys)["max_text_chars"] == ("250", "file")

    monkeypatch.setenv(config.MAX_TEXT_CHARS_ENV, "0")
    main(["config", "show", "--json"])
    assert shown(capsys)["max_text_chars"] == ("0", "environment")


def test_the_reported_limit_is_the_one_that_truncates(capsys, answering) -> None:
    """The number `config show` prints and the number `render` cuts at are the same resolution, not
    two readings of the same variables — so this is checkable from outside, on one corpus."""
    put({"max_text_chars": 20})
    main(["config", "show", "--json"])
    assert shown(capsys)["max_text_chars"][0] == "20"

    answering(200, {"ref": "NOTE-12", "title": "t", "path": "", "body": "y" * 100})
    main(["note", "get", "NOTE-12"])

    assert "(truncated, 100 chars total" in capsys.readouterr().out


def test_zero_disables_truncation_everywhere(capsys, answering, monkeypatch) -> None:
    """SLICES §V2b's other integration line for this card, at the two ends it has to agree at."""
    monkeypatch.setenv(config.MAX_TEXT_CHARS_ENV, "0")
    answering(200, {"ref": "NOTE-12", "title": "t", "path": "", "body": "y" * 900})
    main(["note", "get", "NOTE-12"])

    assert "truncated" not in capsys.readouterr().out


# ---------------------------------------------------------------------------- the token


@pytest.mark.parametrize("fmt", ["human", "json", "toon"])
def test_no_format_of_show_prints_a_fragment_of_the_token(capsys, monkeypatch, fmt: str) -> None:
    """The rule that outranks everything else in a config layer. Checked on the real stdout, in
    every published format, from **both** tiers at once — an implementation that redacted the
    environment and forgot the file would pass a test that only exported one."""
    put({"token": SECRET})
    monkeypatch.setenv(config.TOKEN_ENV, SECRET)

    assert main(["config", "show", "--format", fmt]) == 0
    out = capsys.readouterr().out

    assert not fragments_in(SECRET, out)
    assert "set" in out


def test_the_fragment_check_can_fail() -> None:
    """The guard's own guard: an assertion that cannot fail is the blind guard PLAN §Testing warns
    about, and this one is a negative over a string that is usually short."""
    assert fragments_in(SECRET, f"token set (…{SECRET[-4:]})"), "pandan's own hint went unnoticed"
    assert not fragments_in(SECRET, "token  set  environment  api_url  max_text_chars")


def test_setting_a_token_does_not_echo_it(capsys) -> None:
    """`config set --token` is the one command that has the value in hand, which makes it the one
    command most likely to print it back as a confirmation."""
    assert main(["config", "set", "--token", SECRET]) == 0
    out = capsys.readouterr().out

    assert not fragments_in(SECRET, out)
    assert stored()["token"] == SECRET


def test_the_stored_token_is_not_world_readable() -> None:
    main(["config", "set", "--token", SECRET])

    assert config_file().stat().st_mode & 0o077 == 0


# ---------------------------------------------------------------------------- config set


def test_set_writes_the_file_and_reports_the_result(capsys) -> None:
    assert main(["config", "set", "--api-url", "https://kaya.example", "--json"]) == 0

    assert stored() == {"api_url": "https://kaya.example"}
    assert shown(capsys)["api_url"] == ("https://kaya.example", "file")


def test_set_preserves_a_hand_set_max_text_chars(capsys) -> None:
    """**The card's named trap, end to end.** ``config set`` has no ``--max-text-chars``; a writer
    that serialized only its own flags would delete a value the user tuned by hand, silently, on a
    command about something else."""
    put({"max_text_chars": 120})

    assert main(["config", "set", "--api-url", "https://kaya.example", "--json"]) == 0

    assert stored() == {"max_text_chars": 120, "api_url": "https://kaya.example"}
    assert shown(capsys)["max_text_chars"] == ("120", "file")


def test_set_preserves_a_key_the_cli_has_never_heard_of() -> None:
    """The half that cannot pass by accident. A writer special-casing the one documented key would
    satisfy the test above and still discard this."""
    put({"future_setting": "keep me"})

    main(["config", "set", "--api-url", "https://kaya.example"])

    assert stored()["future_setting"] == "keep me"


def test_set_with_nothing_to_set_is_a_usage_error(capsys) -> None:
    assert main(["config", "set"]) == 2
    assert capsys.readouterr().out.startswith("error\tusage\t")


def test_set_has_no_flag_for_the_text_limit(capsys) -> None:
    """Deliberate: it is a preference tuned once by hand, and giving every key a flag is how a
    config file becomes a second CLI. It is also what makes the preservation rule above real."""
    assert main(["config", "set", "--max-text-chars", "120"]) == 2
    assert "--max-text-chars" in capsys.readouterr().err


def test_a_malformed_file_is_reported_and_not_overwritten(capsys) -> None:
    """Merging onto ``{}`` would replace the only surviving copy of what the user meant."""
    path = config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{oops", encoding="utf-8")

    assert main(["config", "set", "--api-url", "https://kaya.example"]) == 1
    assert path.read_text(encoding="utf-8") == "{oops"
    assert capsys.readouterr().out.startswith("error\truntime\t")


# --------------------------------------------------------------------------- config path


def test_path_prints_where_the_file_would_go_before_it_exists(capsys) -> None:
    """``mkdir -p $(dirname $(kaya config path))`` has to work on a fresh machine, so the verb
    answers with a path rather than refusing in exactly the case it is most needed."""
    assert not config_file().exists()

    assert main(["config", "path", "--json"]) == 0

    assert json.loads(capsys.readouterr().out) == {"path": str(config_file()), "exists": False}


def test_path_says_when_the_file_is_there(capsys) -> None:
    main(["config", "set", "--api-url", "https://kaya.example"])
    capsys.readouterr()

    main(["config", "path", "--json"])

    assert json.loads(capsys.readouterr().out)["exists"] is True


def test_path_answers_even_when_the_configured_values_are_unusable(capsys) -> None:
    """**The escape hatch has to work precisely when everything else does not.**

    A config file holding ``"max_text_chars": "lots"`` is a value nothing can resolve, and the
    refusal that produces tells the caller to fix *the config file*. If the one verb whose entire
    job is to answer "which file?" refuses for the same reason, the caller is locked out of their
    own configuration with a message naming a thing they cannot find.

    Reporting a path does not require a text limit, so this must not merely be *ordered* correctly
    — nothing about `config path` may depend on the file's **contents** at all.
    """
    put({"max_text_chars": "lots", "api_url": "https://kaya.example"})

    assert main(["config", "path", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["path"] == str(config_file())


def test_a_refusal_about_a_file_value_names_the_file(capsys, answering) -> None:
    """"Fix the config file" is not actionable without saying which one.

    The path goes in the **message**, not in a new key: ``arg`` is "the first scalar extra a refusal
    carries" and `backend/tests/unit/test_error_extras_stay_addressable.py` guards that from the
    other side, so a second top-level scalar here would risk reddening a cross-package alarm to say
    something message text says for free. `read_settings_file`'s malformed-JSON refusal already
    names the path this way; this is the same wording for the same reason.
    """
    put({"max_text_chars": "lots"})
    answering(200, {"notes": []})

    assert main(["note", "list"]) == 2
    row = capsys.readouterr().out

    assert str(config_file()) in row
    assert row.split("\t")[3].rstrip("\n") == config.MAX_TEXT_CHARS_ENV


def test_path_answers_over_a_file_that_cannot_even_be_parsed(capsys) -> None:
    """The other way a file can be unusable. `config path` never reads the contents at all, which
    is what makes "the escape hatch works precisely when everything else does not" a property of
    the code rather than an ordering that a later edit could undo."""
    path = config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"api_url": ', encoding="utf-8")

    assert main(["config", "path"]) == 0
    assert str(path) in capsys.readouterr().out


def test_path_is_one_line_a_shell_can_use(capsys) -> None:
    """The human rendering of an entity puts the label first, so ``kaya config path | awk '{print
    $2}'`` works; the structured form is there for anything that wants it typed."""
    main(["config", "path"])
    out = capsys.readouterr().out.splitlines()

    assert out[0].startswith("path")
    assert str(config_file()) in out[0]
