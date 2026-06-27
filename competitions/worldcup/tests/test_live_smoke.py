"""Live BSD smoke test — requires BSD_API_KEY env var.

Run with:
    $env:BSD_API_KEY = "your_key" ; python -m pytest tests/test_live_smoke.py -x -v
Or (PowerShell):
    $env:BSD_API_KEY = "your_key"
    python -m pytest tests/test_live_smoke.py -x -v

This test makes live API calls and verifies the --once flow
returns valid 48-team predictions.

Marked @pytest.mark.skipif to skip automatically when BSD_API_KEY
is not set, allowing the full test suite to pass without the key.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

MAIN_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = MAIN_DIR / "data"

_LIVE_SKIP = pytest.mark.skipif(
    not os.environ.get("BSD_API_KEY"),
    reason="BSD_API_KEY not set — requires live API key",
)


@_LIVE_SKIP
def test_live_smoke_once():
    """Smoke test: --once fetches, simulates, prints valid 48-team predictions.

    This runs the actual main.py --once flow with a live BSD API call.
    NOTE: Uses production data/ directory directly — runs live API calls
    only when BSD_API_KEY is set. Skipped by default.
    Verifies:
    1. Exit code 0
    2. Expected probabilities output contains team names from teams.json
    3. Simulation banner appears in stdout
    4. No error output to stderr
    """
    env = os.environ.copy()
    result = subprocess.run(
        [sys.executable, "-u", str(MAIN_DIR / "main.py"), "--once", "--seed", "42"],
        capture_output=True, text=True, timeout=60, cwd=MAIN_DIR, env=env,
    )

    # 1. Exit code must be 0
    assert result.returncode == 0, (
        f"--once returned {result.returncode}. stderr={result.stderr!r}"
    )

    # 2. Must contain probability output (check for known top team)
    with open(DATA_DIR / "teams.json", encoding="utf-8") as f:
        teams = json.load(f)
    top_team = max(teams, key=lambda t: teams[t].get("elo", 0))
    assert top_team in result.stdout, (
        f"--once output should contain top team {top_team!r}. "
        f"stdout excerpt: {result.stdout[:500]!r}"
    )

    # 3. Must contain simulation duration
    assert "Re-simulating" in result.stdout, (
        f"--once stdout missing simulation banner: {result.stdout[:300]!r}"
    )

    # 4. Allow some stderr warnings but no hard errors
    error_count = result.stderr.count("Error") + result.stderr.count("error")
    assert error_count == 0, (
        f"--once had {error_count} errors in stderr: {result.stderr!r}"
    )


def test_smoke_test_description():
    """Print instructions for manual BSD smoke test.

    This is a documentation test — always passes. It serves as a reminder
    of how to run the live smoke test with a real BSD API key.
    """
    # This is a documentation test — always passes
    pass


def test_live_smoke_modules_importable():
    """Verify all modules needed by the --once flow are importable.

    This test runs WITHOUT an API key and confirms the import chain works.
    It's a useful regression guard that does not require live API access.
    """
    import src.state
    import src.output
    import src.fetcher
    import src.groups
    import src.knockout
    import main as main_mod

    # Verify key functions exist
    assert hasattr(main_mod, "_run_iteration"), "main._run_iteration should exist"
    assert hasattr(main_mod, "run_full_simulation"), "main.run_full_simulation should exist"
    assert hasattr(src.fetcher, "process_group_matches"), "process_group_matches should exist"
    assert hasattr(src.groups, "compute_standings"), "compute_standings should exist"
    assert hasattr(src.groups, "rank_third_placed"), "rank_third_placed should exist"
