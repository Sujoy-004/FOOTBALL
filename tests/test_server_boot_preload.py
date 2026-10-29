"""Verification of active server boot preload default and offline gating (D-01)."""

from __future__ import annotations

import os
import pytest
from web.server import build_arg_parser, configure_server_env


@pytest.fixture(autouse=True)
def isolate_env():
    orig = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(orig)


def test_server_cli_defaults_to_preload_all(monkeypatch):
    monkeypatch.delenv("FOOTBALL_PRELOAD_ALL", raising=False)
    monkeypatch.delenv("FOOTBALL_SNAPSHOT", raising=False)

    parser = build_arg_parser()
    args = parser.parse_args([])
    configure_server_env(args)

    assert os.environ.get("FOOTBALL_PRELOAD_ALL") == "1"
    assert os.environ.get("FOOTBALL_SNAPSHOT") is None


def test_server_cli_offline_flag(monkeypatch):
    monkeypatch.delenv("FOOTBALL_PRELOAD_ALL", raising=False)
    monkeypatch.delenv("FOOTBALL_SNAPSHOT", raising=False)

    parser = build_arg_parser()
    args = parser.parse_args(["--offline"])
    configure_server_env(args)

    assert os.environ.get("FOOTBALL_SNAPSHOT") == "1"
    assert os.environ.get("FOOTBALL_PRELOAD_ALL") is None


def test_server_cli_no_preload_flag(monkeypatch):
    monkeypatch.delenv("FOOTBALL_PRELOAD_ALL", raising=False)
    monkeypatch.delenv("FOOTBALL_SNAPSHOT", raising=False)

    parser = build_arg_parser()
    args = parser.parse_args(["--no-preload"])
    configure_server_env(args)

    assert os.environ.get("FOOTBALL_SNAPSHOT") is None
    assert os.environ.get("FOOTBALL_PRELOAD_ALL") is None
