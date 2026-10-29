"""Contract verification for pyproject.toml coverage settings (HARD-04, D-02)."""

from __future__ import annotations

import pathlib
import tomllib
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_coverage_configuration_in_pyproject():
    pyproject_path = ROOT / "pyproject.toml"
    assert pyproject_path.exists(), "pyproject.toml not found"

    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    assert "tool" in data, "No [tool] in pyproject.toml"
    assert "coverage" in data["tool"], "No [tool.coverage] in pyproject.toml"

    cov = data["tool"]["coverage"]
    run_cfg = cov.get("run", {})
    report_cfg = cov.get("report", {})

    assert run_cfg.get("source") == ["football_core"], (
        f"Expected source ['football_core'], got {run_cfg.get('source')}"
    )
    omit = run_cfg.get("omit", [])
    assert "*/tests/*" in omit, f"Expected '*/tests/*' in omit: {omit}"
    assert "football_core/tests/*" in omit, f"Expected 'football_core/tests/*' in omit: {omit}"

    assert report_cfg.get("fail_under") == 70, (
        f"Expected fail_under == 70, got {report_cfg.get('fail_under')}"
    )
    assert report_cfg.get("show_missing") is True
