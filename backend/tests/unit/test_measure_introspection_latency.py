"""The one property of KAN-539's measurement script that has to hold in CI: **it needs no PAT.**

The script itself is not testable in this layer and is not meant to be — it exists precisely to do
the things the suite refuses to do (real pandan, real Postgres, real credential). What *is*
testable, and what would be genuinely dangerous to get wrong, is the credential path: where the
token is read from, and that the absence of one is a clean exit rather than a crash, a prompt, or
an environment variable somebody is tempted to add to a workflow file.

Loaded by path rather than imported, because `backend/scripts/` is not a package and should not
become one for a test's convenience.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "measure_introspection_latency.py"


@pytest.fixture(scope="module")
def script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("measure_introspection_latency", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_no_credential_anywhere_is_a_clean_exit(
    script: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A CI runner has no PAT and must never be given one, so this path must exit 0 and do nothing.

    "Does nothing" is the load-bearing half: exiting 0 after provisioning a Postgres container and
    calling pandan would be a pass that costs a minute and needs Docker.
    """
    monkeypatch.delenv(script.TOKEN_ENV, raising=False)
    monkeypatch.setattr(script, "PANDAN_CONFIG", tmp_path / "there-is-no-config-here.toml")

    assert script.main([]) == 0
    assert capsys.readouterr().out == "", "nothing was measured, so nothing is reported"


def test_the_environment_wins_over_the_config_file(
    script: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """So a second PAT can be measured without editing the `pandan` CLI's own config."""
    config = tmp_path / "config.toml"
    config.write_text('[pandan]\ntoken = "from-the-file"\napi_url = "https://from-the-file"\n')
    monkeypatch.setenv(script.TOKEN_ENV, "from-the-environment")
    monkeypatch.setenv("KAYA_PANDAN_URL", "https://from-the-environment/")

    assert script.load_credential(config_path=config) == "from-the-environment"
    assert script.load_origin(config_path=config) == "https://from-the-environment"


def test_the_pandan_cli_config_is_read_from_its_section(
    script: ModuleType, tmp_path: Path
) -> None:
    config = tmp_path / "config.toml"
    config.write_text('[pandan]\ntoken = "from-the-file"\napi_url = "https://from-the-file"\n')

    assert script.load_credential(env={}, config_path=config) == "from-the-file"
    assert script.load_origin(env={}, config_path=config) == "https://from-the-file"


def test_an_unreadable_config_is_the_same_as_no_config(script: ModuleType, tmp_path: Path) -> None:
    """A malformed file counts too: broken TOML must not stop the script saying "no PAT"."""
    broken = tmp_path / "config.toml"
    broken.write_text("this is not toml [[[")

    assert script.load_credential(env={}, config_path=broken) is None
    assert script.load_credential(env={}, config_path=tmp_path / "absent.toml") is None
