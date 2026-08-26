"""Interactive startup flow — decision, secrecy, and non-interactive safety."""

from __future__ import annotations

import sys
import types

import pytest

from web.startup import (
    StartupDecision,
    has_usable_fdo_key,
    run_startup_flow,
)

SECRET = "entered-secret-key-abc123"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.setenv("FOOTBALL_DATA_ORG_KEY", "")
    monkeypatch.delenv("FOOTBALL_SNAPSHOT", raising=False)


def test_configured_key_no_prompt(monkeypatch, capsys):
    monkeypatch.setenv("FOOTBALL_DATA_ORG_KEY", "realkey123456")

    def _input(_prompt=""):
        raise AssertionError("must not prompt when a usable key is configured")

    d = run_startup_flow(
        input_fn=_input,
        validate_fn=lambda k: (True, None),
        interactive_fn=lambda: True,
    )
    assert isinstance(d, StartupDecision)
    assert d.mode == "live-configured"
    assert d.fdo_key == "realkey123456"
    out = capsys.readouterr().out
    assert "Live data provider configured." in out
    assert "Starting server..." in out
    assert "realkey123456" not in out  # key never echoed


def test_placeholder_and_missing_keys_are_not_usable():
    assert has_usable_fdo_key("") is False
    assert has_usable_fdo_key(None) is False
    assert has_usable_fdo_key("your_football_data_org_key_here") is False
    assert has_usable_fdo_key("Your_Key_Here") is False
    assert has_usable_fdo_key("realkey123456") is True


def test_interactive_enter_valid_key(capsys):
    lines: list[str] = []
    menus = iter(["1"])
    keys = iter([SECRET])
    prompts = []

    def input_fn(prompt=""):
        prompts.append(prompt)
        return next(menus)

    def key_input_fn(prompt=""):
        prompts.append(prompt)
        return next(keys)

    d = run_startup_flow(
        input_fn=input_fn,
        validate_fn=lambda k: (True, None),
        interactive_fn=lambda: True,
        echo=lines.append,
        key_input_fn=key_input_fn,
    )
    assert d.mode == "live-entered"
    assert d.fdo_key == SECRET
    transcript = "\n".join(lines)
    assert "Live API access confirmed." in transcript
    assert "Data refresh completed." in transcript
    assert "Starting server..." in transcript
    assert SECRET not in transcript  # entered key is never printed back


def test_invalid_key_safe_error_then_snapshot(capsys):
    lines: list[str] = []
    answers = iter(["1",       # main menu -> enter key
                    "1",       # failure sub-menu -> try another key
                    "2"])      # failure sub-menu -> snapshot
    keys = iter(["bad-key-1", "bad-key-2"])
    validate_calls = []

    def validate(key):
        validate_calls.append(key)
        return False, "HTTP 400: Your API token is invalid."

    d = run_startup_flow(
        input_fn=lambda prompt="": next(answers),
        validate_fn=validate,
        interactive_fn=lambda: True,
        echo=lines.append,
        key_input_fn=lambda prompt="": next(keys),
    )
    assert d.mode == "snapshot"
    assert validate_calls == ["bad-key-1", "bad-key-2"]
    transcript = "\n".join(lines)
    assert transcript.count("Live API validation/refresh failed:") == 2
    assert "HTTP 400: Your API token is invalid." in transcript
    assert "bad-key-1" not in transcript and "bad-key-2" not in transcript  # keys never echoed


def test_invalid_key_exit_option(capsys):
    answers = iter(["1", "3"])   # menu -> enter bad key -> exit
    with pytest.raises(SystemExit) as exc:
        run_startup_flow(
            input_fn=lambda prompt="": next(answers),
            validate_fn=lambda k: (False, "invalid"),
            interactive_fn=lambda: True,
            echo=lambda s: None,
            key_input_fn=lambda prompt="": "bad-key-9",
        )
    assert exc.value.code == 0


def test_non_interactive_defaults_to_auto_acquisition():
    """No TTY: the default policy is ATTEMPT fresh acquisition ("auto"),
    not silent snapshot. Provider failures later fall back to stored data
    with truthful stale reports; snapshot requires an explicit choice."""
    def _input(_prompt=""):
        raise AssertionError("must not prompt in non-interactive mode")

    def _validate(_k):
        raise AssertionError("must not attempt live validation in non-interactive mode")

    d = run_startup_flow(input_fn=_input,
                         validate_fn=_validate,
                         interactive_fn=lambda: False)
    assert d.mode == "auto"
    assert d.fdo_key == ""
    from web.startup import is_snapshot_mode
    assert is_snapshot_mode() is False


def test_apply_session_overrides_updates_process(monkeypatch):
    import web.startup as startup

    monkeypatch.setattr(startup.os, "environ", {})

    fake_wc = types.ModuleType("web.wc_app")
    fake_ucl = types.ModuleType("web.ucl_app")
    fake_wc.FOOTBALL_DATA_ORG_KEY = ""
    fake_ucl.FOOTBALL_DATA_ORG_KEY = ""
    monkeypatch.setitem(sys.modules, "web.wc_app", fake_wc)
    monkeypatch.setitem(sys.modules, "web.ucl_app", fake_ucl)

    startup.apply_session_overrides("sessionkey42")
    assert startup.os.environ["FOOTBALL_DATA_ORG_KEY"] == "sessionkey42"
    assert fake_wc.FOOTBALL_DATA_ORG_KEY == "sessionkey42"
    assert fake_ucl.FOOTBALL_DATA_ORG_KEY == "sessionkey42"


def test_no_persistence_of_entered_key(tmp_path, monkeypatch, capsys):
    """Entering a key that fails validation must not create/modify env files."""
    env_file = tmp_path / ".env"
    example_file = tmp_path / ".env.example"

    menus = iter(["1", "2"])
    keys = iter(["some-entered-key"])

    d = run_startup_flow(
        input_fn=lambda prompt="": next(menus),
        validate_fn=lambda k: (False, "invalid"),
        interactive_fn=lambda: True,
        echo=lambda s: None,
        key_input_fn=lambda prompt="": next(keys),
    )
    assert d.mode == "snapshot"
    assert not env_file.exists()
    assert not example_file.exists()


# .env / .env.example remain ignored & untouched by the flow itself
def test_env_files_still_gitignored(tmp_path):
    from pathlib import Path
    gitignore = (Path(__file__).resolve().parent.parent / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gitignore
