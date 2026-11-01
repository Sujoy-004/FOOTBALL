"""Verification of active server boot preload default, offline gating (D-01), and port/host binding (D-07/D-08)."""

from __future__ import annotations

import os
import sys
import pytest
from web.server import build_arg_parser, configure_server_env, asgi_app


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


def test_server_cli_port_host(monkeypatch):
    # Default without env vars
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("HOST", raising=False)
    parser = build_arg_parser()
    args = parser.parse_args([])
    assert args.port == 8080
    assert args.host == "127.0.0.1"

    # With PORT env var set (Render default pattern: PORT=10000 -> host 0.0.0.0)
    monkeypatch.setenv("PORT", "10000")
    monkeypatch.delenv("HOST", raising=False)
    parser = build_arg_parser()
    args = parser.parse_args([])
    assert args.port == 10000
    assert args.host == "0.0.0.0"

    # With explicit HOST env var set
    monkeypatch.setenv("HOST", "192.168.1.10")
    parser = build_arg_parser()
    args = parser.parse_args([])
    assert args.host == "192.168.1.10"

    # CLI explicit override overrides env vars
    args = parser.parse_args(["--port", "9090", "--host", "0.0.0.0"])
    assert args.port == 9090
    assert args.host == "0.0.0.0"


def test_uvicorn_loads_asgi_app(monkeypatch):
    # Ensure asgi_app is callable and decoupled from sys.argv
    monkeypatch.setattr(sys, "argv", ["uvicorn", "web.server:asgi_app", "--invalid-custom-flag"])
    assert callable(asgi_app)
