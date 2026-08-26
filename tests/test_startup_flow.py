"""Startup flow — decision, secrecy, and never-prompt safety.

Exchange 4 v2: the interactive menu was removed. Normal execution NEVER
prompts and NEVER offers a choice that disables scraping; "snapshot" is
reachable only via FOOTBALL_SNAPSHOT=1 or a forced decision (tests).
"""

from __future__ import annotations

import sys
import types

import pytest

from web.startup import (
    StartupDecision,
    has_usable_fdo_key,
    run_startup_flow,
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    import web.startup as startup

    monkeypatch.setenv("FOOTBALL_DATA_ORG_KEY", "")
    monkeypatch.delenv("FOOTBALL_SNAPSHOT", raising=False)
    yield
    startup._last_decision = None


def test_configured_key_no_prompt(monkeypatch, capsys):
    monkeypatch.setenv("FOOTBALL_DATA_ORG_KEY", "realkey123456")

    d = run_startup_flow()
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


def test_never_prompts_and_never_decides_scraping_disabled():
    """The flow is prompt-free in every normal path; only an explicit
    override can produce a scraping-disabled ("snapshot") decision."""
    lines: list[str] = []
    d = run_startup_flow(echo=lines.append)
    transcript = "\n".join(lines)
    assert d.mode == "auto"
    assert "[1]" not in transcript and "[2]" not in transcript
    assert "Choose" not in transcript

    from web.startup import is_snapshot_mode
    assert is_snapshot_mode() is False


def test_snapshot_requires_explicit_env_override(monkeypatch):
    """FOOTBALL_SNAPSHOT=1 remains the only user-facing offline switch."""
    from web.startup import is_snapshot_mode

    monkeypatch.setenv("FOOTBALL_SNAPSHOT", "1")
    d = run_startup_flow(echo=lambda s: None)
    assert d.mode == "snapshot"
    assert is_snapshot_mode() is True


def test_non_interactive_defaults_to_auto_acquisition():
    """No TTY: the default policy is ATTEMPT fresh acquisition ("auto"),
    not silent snapshot. Provider failures later fall back to stored data
    with truthful stale reports; snapshot requires an explicit choice."""
    d = run_startup_flow()
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


def test_no_persistence_of_credentials(tmp_path, monkeypatch, capsys):
    """The banner path (no usable credential) must not create/modify env
    files and must not decide into scraping-disabled mode."""
    env_file = tmp_path / ".env"
    example_file = tmp_path / ".env.example"

    d = run_startup_flow(echo=lambda s: None)
    assert d.mode == "auto"
    assert d.fdo_key == ""
    assert not env_file.exists()
    assert not example_file.exists()


# .env / .env.example remain ignored & untouched by the flow itself
def test_env_files_still_gitignored(tmp_path):
    from pathlib import Path
    gitignore = (Path(__file__).resolve().parent.parent / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gitignore
