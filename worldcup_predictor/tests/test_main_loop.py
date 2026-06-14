"""Tests for the main polling loop and shutdown behavior (Phase 4)."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

MAIN_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = MAIN_DIR / "data"


def _runner_code() -> str:
    """Inline Python that mocks requests.get, sets POLL_INTERVAL=1, then calls main.main()."""
    return (
        f"import os, sys\n"
        f"os.environ['POLL_INTERVAL'] = '1'\n"
        f"os.environ['FOOTBALL_API_KEY'] = 'test_dummy_key'\n"
        f"sys.path.insert(0, {str(MAIN_DIR)!r})\n"
        f"os.chdir({str(MAIN_DIR)!r})\n"
        f"import requests\n"
        f"import src.constants\n"
        f"src.constants.API_TIMEOUT = 1\n"
        f"class _MockResp:\n"
        f"  status_code=200\n"
        f"  def json(self):\n"
        f"    return {{}}\n"
        f"  def raise_for_status(self):\n"
        f"    pass\n"
        f"  @property\n"
        f"  def ok(self):\n"
        f"    return True\n"
        f"requests.get = lambda url, **kw: _MockResp()\n"
        f"import main\n"
        f"main.main()\n"
    )


def _runner_code_with_flag(flag: str) -> str:
    """Inline Python that mocks requests.get, passes `flag` as CLI arg, then calls main.main()."""
    return (
        f"import os, sys\n"
        f"os.environ['POLL_INTERVAL'] = '1'\n"
        f"os.environ['FOOTBALL_API_KEY'] = 'test_dummy_key'\n"
        f"sys.path.insert(0, {str(MAIN_DIR)!r})\n"
        f"os.chdir({str(MAIN_DIR)!r})\n"
        f"sys.argv = ['main.py', {flag!r}]\n"
        f"import requests\n"
        f"import src.constants\n"
        f"src.constants.API_TIMEOUT = 1\n"
        f"class _MockResp:\n"
        f"  status_code=200\n"
        f"  def json(self):\n"
        f"    return {{}}\n"
        f"  def raise_for_status(self):\n"
        f"    pass\n"
        f"  @property\n"
        f"  def ok(self):\n"
        f"    return True\n"
        f"requests.get = lambda url, **kw: _MockResp()\n"
        f"import main\n"
        f"main.main()\n"
    )


def test_once_flag_runs_single_cycle():
    """--once runs a single fetch->simulate->print cycle, then exits (no polling loop)."""
    proc = subprocess.Popen(
        [sys.executable, "-u", "-c", _runner_code_with_flag("--once")],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        assert False, (
            f"--once should exit within 10s, did not. "
            f"stdout={stdout!r} stderr={stderr!r}"
        )
    # --once should exit cleanly (code 0)
    assert proc.returncode == 0, (
        f"--once should exit code 0, got {proc.returncode}. "
        f"stdout={stdout!r} stderr={stderr!r}"
    )
    # Must contain simulation output (confirms sim ran)
    assert "UPDATED PROBABILITIES" in stdout or "Initial probabilities" in stdout, (
        f"--once must print probability output. stdout={stdout!r}"
    )
    # Must NOT contain more than 1 "Polling..." heartbeat (confirms single _run_iteration call, no loop)
    heartbeat_count = stdout.count("Polling...")
    assert heartbeat_count <= 1, (
        f"--once should have at most 1 heartbeat, got {heartbeat_count}. stdout={stdout!r}"
    )


def test_main_loop_runs_iterations():
    """Loop should run multiple fetch cycles when poll interval is short.

    Current main.py has no loop -> 'Fetched' appears exactly once -> fails (>=2).
    """
    proc = subprocess.Popen(
        [sys.executable, "-u", "-c", _runner_code()],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        stdout, _ = proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, _ = proc.communicate()
    assert stdout.count("Fetched") >= 2, (
        f"Expected >=2 'Fetched' lines, got {stdout.count('Fetched')}: {stdout!r}"
    )


def test_main_loop_clean_shutdown():
    """Ctrl+C should print final probabilities banner before exit.

    Current main.py has no loop and no shutdown banner -> fails.
    """
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(
        [sys.executable, "-u", "-c", _runner_code()],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        **kwargs,
    )
    time.sleep(2)  # Let first iteration complete
    sig = signal.CTRL_BREAK_EVENT if sys.platform == "win32" else signal.SIGINT
    try:
        proc.send_signal(sig)
    except ProcessLookupError:
        pass  # Process already exited
    try:
        stdout, _ = proc.communicate(timeout=6)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, _ = proc.communicate()
    assert "FINAL CHAMPIONSHIP PROBABILITIES" in stdout, (
        f"Missing shutdown banner: {stdout!r}"
    )


def test_hourly_resim_triggers(monkeypatch):
    """When >3600s since last_sim_time, hourly re-sim runs without API call."""
    import time as time_module
    import main as main_mod

    fake_time = [5000.0]

    def mock_time():
        return fake_time[0]

    monkeypatch.setattr(time_module, "time", mock_time)

    def mock_sim(teams, bracket, played, iterations, seed=None):
        return {name: {"qf": 0.5, "sf": 0.3, "final": 0.1, "champion": 0.05} for name in teams}
    import src.simulation
    monkeypatch.setattr(src.simulation, "run_simulation", mock_sim)

    teams = {"Arg": {"elo": 2000}, "Bra": {"elo": 2000}}
    bracket = [
        {"match_id": "F", "round": "F", "team_a": "Arg", "team_b": "Bra",
         "source_matches": None, "winner": None},
    ]
    played = {}
    last_sim_time = 1000.0  # 5000 - 1000 = 4000 > 3600, triggers hourly re-sim
    last_request_time = 100.0

    new_sim, new_req, new_probs = main_mod._run_iteration(
        teams, bracket, played, "dummy_key", {},
        last_sim_time, last_request_time,
    )

    assert new_req == last_request_time, "Should NOT make API call during hourly re-sim"
    assert new_sim == fake_time[0], "Should update last_sim_time to current time"


def test_seed_propagates_through_run_iteration(monkeypatch):
    """seed parameter is passed through to run_simulation()."""
    import main as main_mod
    import src.simulation

    captured_seeds = []

    def mock_sim(teams, bracket, played, iterations=50000, seed=None):
        captured_seeds.append(seed)
        return {name: {"qf": 0.5, "sf": 0.3, "final": 0.1, "champion": 0.05} for name in teams}

    # Patch both module-level and local reference (main.py imports via `from ... import`)
    monkeypatch.setattr(src.simulation, "run_simulation", mock_sim)
    monkeypatch.setattr(main_mod, "run_simulation", mock_sim)

    teams = {"Arg": {"elo": 2000}, "Bra": {"elo": 2000}}
    bracket = [
        {"match_id": "F", "round": "FINAL", "team_a": "Arg", "team_b": "Bra",
         "source_matches": None, "winner": None},
    ]
    played = {}

    # Call _run_iteration with seed=42
    new_sim, new_req, probs = main_mod._run_iteration(
        teams, bracket, played, "dummy_key", {},
        last_sim_time=0.0, last_request_time=0.0,
        prev_probs=None, seed=42,
    )

    # run_simulation should have been called with seed=42
    assert len(captured_seeds) >= 1, "run_simulation should have been called"
    assert 42 in captured_seeds, f"seed=42 should be in captured_seeds: {captured_seeds}"
