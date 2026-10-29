"""Contract verification for pyproject.toml coverage settings (HARD-04, D-02).

Two layers of contract:

1. Static: ``pyproject.toml`` must configure the explicit numeric coverage floor
   (``fail_under = 70``) on ``football_core``, omitting internal test directories
   so non-production helpers do not inflate core metrics (T-07-04).
2. Behavioral: the pytest-cov runner must honour that configuration — measured
   coverage of a core module must cleanly clear the floor, and a run measured
   below it must terminate non-zero (exit 1) with the floor shortfall printed
   (T-07-05).

Both behavioral probes run pytest in a subprocess with ``FOOTBALL_SNAPSHOT=1``
so they make zero network requests, per the project's offline policy.
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys
import tomllib
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

COV_FLOOR = 70


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

    assert report_cfg.get("fail_under") == COV_FLOOR, (
        f"Expected fail_under == {COV_FLOOR}, got {report_cfg.get('fail_under')}"
    )
    assert report_cfg.get("show_missing") is True


def _run_pytest_coverage(args: list[str]) -> subprocess.CompletedProcess[str]:
    env: dict[str, str] = {**os.environ, "FOOTBALL_SNAPSHOT": "1"}
    return subprocess.run(
        [sys.executable, "-m", "pytest", *args,
         "--color=no", "-p", "no:cacheprovider", "-q"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
        env=env,
        timeout=300,
        check=False,
    )


def test_coverage_report_execution_exceeds_floor():
    """Run coverage against a core module and verify measured coverage clears the floor."""
    proc = _run_pytest_coverage([
        "tests/test_domain_contracts.py",
        "--cov=football_core.domain",
        "--cov-fail-under=0",  # measure; enforcement is the sibling test's job
        "--cov-report=term",
    ])
    assert proc.returncode == 0, (
        f"Probe run failed (exit {proc.returncode}):\n{proc.stdout}\n{proc.stderr}"
    )
    match = re.search(r"^TOTAL\s+\d+\s+\d+\s+(\d+)%\s*$", proc.stdout, re.MULTILINE)
    assert match is not None, (
        f"No coverage TOTAL row found for football_core.domain:\n{proc.stdout}\n{proc.stderr}"
    )
    measured = int(match.group(1))
    assert measured >= COV_FLOOR, (
        f"Measured coverage of football_core.domain is {measured}%, "
        f"below the configured {COV_FLOOR}% floor"
    )


def test_coverage_runner_fails_below_floor():
    """A run measured below the configured floor must exit non-zero with the shortfall printed."""
    proc = _run_pytest_coverage([
        "tests/test_coverage_floor_contract.py::test_coverage_configuration_in_pyproject",
        "--cov=football_core",  # whole kernel; this node covers ~0% of it
        "--cov-report=term",
    ])
    assert proc.returncode != 0, (
        f"Expected non-zero exit when coverage falls below the {COV_FLOOR}% floor, got 0:\n"
        f"{proc.stdout}\n{proc.stderr}"
    )
    short_fall = re.search(
        r"Required test coverage of 70(?:\.0)?% not reached", proc.stdout
    ) or re.search(r"Required test coverage of 70(?:\.0)?% not reached", proc.stderr)
    assert short_fall is not None, (
        f"Coverage-floor shortfall message not printed:\n{proc.stdout}\n{proc.stderr}"
    )
